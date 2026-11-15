import io
import os
import hashlib
import glob
import json
import mimetypes
from urllib.parse import quote
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import engine, Base, get_db, ensure_schema
from models import (
    get_active_period, MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail,
    SourceDataset, CounterpartyLine, ConfirmationRound, BankReply, DisputeItem, UploadHistory,
)
from seed import seed_database
from services.entity_resolution import EntityResolver
from services.rule_engine import (
    THRESHOLDS,
    WEIGHTS,
    PARAMETER_NAMES,
    PARAMETER_DETAILS,
    evaluate_and_sync_database,
    PUVA_CODES,
    MAX_PUVA_SCORE,
    STATUS_MEMENUHI,
    STATUS_TIDAK_MEMENUHI,
    STATUS_DATA_BELUM_LENGKAP,
)

from services.precheck import precheck_item
from services.real_ingest import (
    INGESTERS, SOURCES, QUOTE_SOURCES, IngestError, find_default_file, period_from_dates, default_dataset_dir,
)
from services import replies as replies_service
from services import counterparty as cp_service
from services.confirmation_workbook import build_confirmation_workbook, confirmation_file_name
from services import documents as documents_service

# Direktori penyimpanan unggahan bukti berkas bank
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Buat tabel dan jalankan auto-seeder saat startup jika belum ada data
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = next(get_db())
    try:
        seed_database(db=db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="PUVA EVAL-CORE API",
    description="Sistem Evaluasi Triwulanan Dealer Utama Pasar Uang & Pasar Valuta Asing (DU PUVA) - Bank Indonesia",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_period_unlocked(db: Session, period_id: Optional[int] = None) -> Optional[EvaluationPeriod]:
    """
    Tolak perubahan data jika snapshot periode evaluasi sudah dikunci.
    Mengembalikan periode yang dimaksud (atau periode terbaru bila period_id kosong).
    """
    query = db.query(EvaluationPeriod)
    period = (
        query.filter(EvaluationPeriod.id == period_id).first()
        if period_id
        else get_active_period(db)
    )
    if period and period.Is_Snapshot_Locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Snapshot evaluasi {period.Triwulan} sudah dikunci ({period.Snapshot_ID}). "
                "Buka kunci snapshot terlebih dahulu untuk mengubah data."
            ),
        )
    return period


# ==============================================================================
# 1. CORE & HEALTH ENDPOINTS
# ==============================================================================
@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "PUVA EVAL-CORE Backend Engine",
        "regulations": [
            "PBI No. 6 Tahun 2024 (Dealer Utama PUVA)",
            "PADG No. 23 Tahun 2024 (Tata Cara Evaluasi & Rekonsiliasi)",
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/settings/rules")
def get_rule_settings():
    """Mengembalikan konfigurasi threshold, bobot, dan nama parameter PUVA."""
    return {
        "thresholds": THRESHOLDS,
        "weights": WEIGHTS,
        "parameters": PARAMETER_NAMES,
        "details": PARAMETER_DETAILS,
    }


def _period_payload(period: EvaluationPeriod) -> Dict[str, Any]:
    working_days = json.loads(period.Working_Days_JSON) if period.Working_Days_JSON else []
    sessions = json.loads(period.MM_OIS_Sessions_JSON) if period.MM_OIS_Sessions_JSON else []
    return {
        "id": period.id,
        "tahun": period.Tahun,
        "triwulan": period.Triwulan,
        "active_threshold_stage": period.Active_Threshold_Stage,
        "is_active": bool(period.Is_Active),
        "is_snapshot_locked": period.Is_Snapshot_Locked,
        "locked_at": period.Locked_At,
        "working_days_count": len(working_days),
        "mm_ois_sessions_count": len(sessions),
        "working_days": working_days,
        "mm_ois_sessions": sessions,
    }


@app.get("/api/period")
def read_active_period(db: Session = Depends(get_db)):
    """Mengembalikan periode evaluasi yang aktif saat ini beserta kalender hari kerja & sesi MM OIS."""
    period = get_active_period(db)
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi")
    return _period_payload(period)


@app.get("/api/periods")
def list_periods(db: Session = Depends(get_db)):
    """Daftar seluruh periode evaluasi (terbaru lebih dulu)."""
    active = get_active_period(db)
    periods = db.query(EvaluationPeriod).order_by(EvaluationPeriod.Triwulan.desc()).all()
    out = []
    for p in periods:
        item = _period_payload(p)
        item["is_active"] = active is not None and p.id == active.id
        out.append(item)
    return out


@app.post("/api/periods/{period_id}/activate")
def activate_period(period_id: int, db: Session = Depends(get_db)):
    """Jadikan periode ini periode aktif untuk matriks, temuan, snapshot, dan dokumen."""
    period = db.query(EvaluationPeriod).filter(EvaluationPeriod.id == period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail=f"Periode id {period_id} tidak ditemukan.")
    _set_active_period(db, period)
    db.commit()
    return _period_payload(period)


def _set_active_period(db: Session, period: EvaluationPeriod) -> None:
    for p in db.query(EvaluationPeriod).all():
        p.Is_Active = p.id == period.id


def _get_or_create_period(db: Session, tahun: int, triwulan: str) -> EvaluationPeriod:
    period = db.query(EvaluationPeriod).filter(EvaluationPeriod.Triwulan == triwulan).first()
    if not period:
        # Tahap threshold yang berlaku saat ini: EARLY (keputusan DPPK, Nov 2026)
        period = EvaluationPeriod(Tahun=tahun, Triwulan=triwulan, Active_Threshold_Stage="EARLY", Is_Snapshot_Locked=False)
        db.add(period)
        db.flush()
    return period


@app.get("/api/banks")
def get_all_banks(db: Session = Depends(get_db)):
    """Mengembalikan daftar 21 Bank Dealer Utama beserta data master dan aliasing."""
    banks = db.query(MasterBank).order_by(MasterBank.Bank_ID).all()
    return [
        {
            "bank_id": b.Bank_ID,
            "masked_alias": b.Masked_Alias,
            "nama_resmi_bank": b.Nama_Resmi_Bank,
            "nama_singkat": b.Nama_Singkat,
            "kelompok_kbmi": b.Kelompok_KBMI,
            "sandi_bi": b.Sandi_BI,
            "kode_bbg": b.Kode_BBG,
            "no_urut_konfirmasi": b.No_Urut_Konfirmasi,
            "kode_bloomberg": b.Kode_Bloomberg,
            "kode_sppa_antasena": b.Kode_SPPA_Antasena,
        }
        for b in banks
    ]


# ==============================================================================
# 2. INGEST DATA RIL PER SUMBER (POST /api/ingest/{source})
# ==============================================================================
@app.post("/api/ingest/{source}")
async def ingest_real_source(
    source: str,
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Ingest data ril per sumber (format file kerja DPPK):
    - `bbg-repo` / `bbg-srbi` / `bbg-ois` -> B1 / B2 / B3 Kuotasi Bloomberg (worksheet Price Quotation Gen 2)
    - `srbi-ratio` -> B6 Rasio Penjualan SRBI Sekunder (rekap sekunder vs win perdana)
    - `repo-2m` / `srbi-3b` -> B7a / B7b rekap transaksi harian (Repo >= 2 minggu, SRBI sisa >= 3 bulan)
    - `mm-ois`     -> B8 Partisipasi Matchmaking OIS (sheet Kuotasi export DS Antasena)
    Bila `file` tidak dikirim, dipakai file dari folder dataset ril lokal (REAL_DATASET_DIR).
    Periode evaluasi ditentukan dari tanggal di dalam file, lalu dijadikan periode aktif.
    Hasil memuat cross-check terhadap rekap BI pada file yang sama.
    """
    if source not in INGESTERS:
        raise HTTPException(status_code=404, detail=f"Sumber '{source}' tidak dikenal. Pilihan: {list(INGESTERS)}")

    try:
        if file and file.filename:
            file_obj = io.BytesIO(await file.read())
            file_name = file.filename
        else:
            path = find_default_file(source)
            file_obj = path
            file_name = os.path.basename(path)
        result = INGESTERS[source](file_obj, EntityResolver(db))
        tahun, triwulan = period_from_dates(result["dates"])
    except IngestError as e:
        raise HTTPException(status_code=400, detail=str(e))

    period = _get_or_create_period(db, tahun, triwulan)
    ensure_period_unlocked(db, period.id)
    if result.get("working_days") and (source == "srbi-ratio" or not period.Working_Days_JSON):
        # Kalender hari kerja: rekap transaksi BI menjadi acuan; sumber lain hanya mengisi bila belum ada
        period.Working_Days_JSON = json.dumps(result["working_days"])
    if result.get("sessions"):
        period.MM_OIS_Sessions_JSON = json.dumps(result["sessions"])
    _set_active_period(db, period)

    # Item sanggahan yang sudah DITERIMA tetap berlaku saat sumber data diproses ulang
    for (b_id, src), acc in replies_service.accepted_overrides(db, period.id).items():
        if src == source and b_id in result.get("daily", {}):
            rate, det = replies_service.rate_with_overrides(source, result["daily"][b_id], acc)
            bd = result["breakdown"].setdefault(b_id, {}).setdefault(result["param"], {})
            bd.update({**det, "rate_sebelum_sanggahan": bd.get("rate"), "rate": rate, "sanggahan_diterima": len(acc)})
            result["raw_metrics"].setdefault(b_id, {})[result["param"]] = rate

    # Simpan data harian per bank (bahan workbook konfirmasi + jejak file sumber)
    db.query(SourceDataset).filter(SourceDataset.period_id == period.id, SourceDataset.Source == source).delete()
    for bank_id, payload in result.get("daily", {}).items():
        db.add(SourceDataset(period_id=period.id, Source=source, Bank_ID=bank_id,
                             Payload_JSON=json.dumps(payload), File_Name=file_name))
    upload = _record_upload(db, period.id, "SUMBER", source, file_name, file_obj, bool(file and file.filename),
                            f"{result['param']} untuk {len(result.get('daily', {}))} bank")

    sync_result = evaluate_and_sync_database(
        db=db,
        stage=period.Active_Threshold_Stage or "EARLY",
        period_id=period.id,
        raw_metrics=result["raw_metrics"],
        failed_transactions=result["failed"],
        breakdown_stats=result["breakdown"],
    )

    param = result["param"]
    db.add(AuditTrail(
        action=f"INGEST_{source.upper().replace('-', '_')}",
        performed_by="Petugas BI DPPK",
        details=(
            f"Ingest {SOURCES[source]['label']} ({param}) periode {triwulan} dari '{file_name}'. "
            f"Selisih vs rekap BI: {len(result['crosscheck'])}. Bank tak dikenal: {len(result['unknown_banks'])}."
        ),
    ))
    db.commit()

    per_bank = []
    for b in db.query(MasterBank).order_by(MasterBank.Bank_ID).all():
        per_bank.append({
            "bank_id": b.Bank_ID,
            "nama_singkat": b.Nama_Singkat,
            "masked_alias": b.Masked_Alias,
            "rate": result["raw_metrics"].get(b.Bank_ID, {}).get(param),
            "detail": result["breakdown"].get(b.Bank_ID, {}).get(param),
        })

    return {
        "status": "success",
        "source": source,
        "parameter": param,
        "file_name": file_name,
        "upload": upload,
        "period": _period_payload(period),
        "per_bank": per_bank,
        "crosscheck": {
            "available": result["crosscheck_available"],
            "differences": result["crosscheck"],
        },
        "unknown_banks": result["unknown_banks"],
        "source_notes": result.get("source_notes", []),
        "evaluation_summary": sync_result,
    }


def _record_upload(db: Session, period_id: Optional[int], kind: str, source: Optional[str], name: str, src: Any,
                   uploaded: bool, note: Optional[str] = None) -> Dict[str, Any]:
    """Catat file yang diproses beserta SHA-256; tandai bila isinya sama dengan versi sebelumnya untuk sumber yang sama."""
    if isinstance(src, (bytes, bytearray)):
        data = bytes(src)
    elif hasattr(src, "getvalue"):
        data = src.getvalue()
    else:
        with open(src, "rb") as fh:
            data = fh.read()
    digest = hashlib.sha256(data).hexdigest()
    prev = (db.query(UploadHistory)
            .filter(UploadHistory.Kind == kind, UploadHistory.Source == source, UploadHistory.File_Name == os.path.basename(name))
            .order_by(UploadHistory.id.desc()).first())
    db.add(UploadHistory(period_id=period_id, Kind=kind, Source=source, File_Name=os.path.basename(name), SHA256=digest,
                         Size_Bytes=len(data), Origin="UNGGAH" if uploaded else "LOKAL", Result_Note=note))
    return {"file": os.path.basename(name), "sha256": digest, "ukuran": len(data),
            "versi": "sama dengan sebelumnya" if prev and prev.SHA256 == digest else "berubah" if prev else "baru"}


@app.get("/api/uploads")
def list_uploads(kind: Optional[str] = None, limit: int = 200, db: Session = Depends(get_db)):
    """Riwayat file yang diproses (terbaru dulu) untuk periode aktif."""
    period = get_active_period(db)
    q = db.query(UploadHistory)
    if period is not None:
        q = q.filter((UploadHistory.period_id == period.id) | (UploadHistory.period_id.is_(None)))
    if kind:
        q = q.filter(UploadHistory.Kind == kind.upper())
    return [{
        "id": u.id, "kind": u.Kind, "source": u.Source, "file": u.File_Name, "sha256": u.SHA256,
        "ukuran": u.Size_Bytes, "asal": u.Origin, "oleh": u.Uploaded_By,
        "waktu": u.Uploaded_At.isoformat(timespec="seconds") if u.Uploaded_At else None, "catatan": u.Result_Note,
    } for u in q.order_by(UploadHistory.id.desc()).limit(limit)]


def _sync_counterparty(db: Session, period: EvaluationPeriod) -> Dict[str, Any]:
    metrics = cp_service.compute_metrics(db, period.id)
    sync = evaluate_and_sync_database(
        db=db,
        stage=period.Active_Threshold_Stage or "EARLY",
        period_id=period.id,
        raw_metrics=metrics["raw_metrics"],
        failed_transactions=metrics["failed"],
        breakdown_stats=metrics["breakdown"],
    )
    return {"metrics": metrics, "sync": sync}


def _counterparty_summary(db: Session, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for b in db.query(MasterBank).order_by(MasterBank.Bank_ID).all():
        bd = metrics["breakdown"].get(b.Bank_ID, {})
        rows.append({
            "bank_id": b.Bank_ID, "nama_singkat": b.Nama_Singkat, "masked_alias": b.Masked_Alias,
            "B4": bd.get("B4"), "B5": bd.get("B5"),
        })
    return rows


@app.post("/api/counterparty/ingest")
async def ingest_counterparty(
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
):
    """
    B4/B5 Counterparty line dari workbook konfirmasi.
    - Dengan `files`: tiap workbook (kiriman BI atau balasan bank) mengganti daftar line bank tsb.
    - Tanpa `files`: baca folder dataset ril lokal, `Konfirmasi Bank/*.xlsx` lalu balasan di `[Confirmed]*/**`.
    Periode = periode aktif (unggah data transaksi/kuotasi lebih dulu agar periode ril terbentuk).
    """
    period = get_active_period(db)
    if period is None:
        raise HTTPException(status_code=400, detail="Belum ada periode evaluasi.")
    if not period.Working_Days_JSON:
        raise HTTPException(status_code=400, detail="Periode aktif belum memuat data ril. Unggah data transaksi/kuotasi lebih dulu.")
    ensure_period_unlocked(db, period.id)

    if files:
        sources = [(f.filename, io.BytesIO(await f.read())) for f in files if f and f.filename]
    else:
        paths = cp_service.local_workbook_files(default_dataset_dir())
        if not paths:
            raise HTTPException(status_code=400, detail=f"Tidak ada workbook konfirmasi di folder dataset ril ({default_dataset_dir()}).")
        sources = [(p, p) for p in paths]

    applied = cp_service.apply_workbooks(db, period.id, sources, EntityResolver(db))
    uploads = [_record_upload(db, period.id, "COUNTERPARTY", None, name, src, bool(files)) for name, src in sources]
    result = _sync_counterparty(db, period)
    db.add(AuditTrail(
        action="INGEST_COUNTERPARTY",
        performed_by="Petugas BI DPPK",
        details=(f"Counterparty line periode {period.Triwulan}: {len(applied['applied'])} workbook diterapkan, "
                 f"{len(applied['skipped'])} dilewati."),
    ))
    db.commit()
    return {
        "status": "success",
        "period": _period_payload(period),
        "applied": applied["applied"],
        "skipped": applied["skipped"],
        "uploads": uploads,
        "per_bank": _counterparty_summary(db, result["metrics"]),
        "evaluation_summary": result["sync"],
    }


@app.get("/api/counterparty/{bank_id}")
def list_counterparty_lines(bank_id: str, db: Session = Depends(get_db)):
    """Daftar counterparty line bank pada periode aktif (untuk koreksi petugas)."""
    period = get_active_period(db)
    du_sandi = {b.Sandi_BI.zfill(3) for b in db.query(MasterBank).all() if b.Sandi_BI}
    lines = db.query(CounterpartyLine).filter(
        CounterpartyLine.period_id == period.id, CounterpartyLine.Bank_ID == bank_id
    ).order_by(CounterpartyLine.Instrument, CounterpartyLine.Counterparty_Sandi).all()
    return [{
        "id": l.id, "instrument": l.Instrument, "sandi": l.Counterparty_Sandi, "nama": l.Counterparty_Nama,
        "status": l.Status, "is_du": l.Counterparty_Sandi in du_sandi, "dihapus": cp_service.is_deleted(l.Status),
        "setelah_cutoff": cp_service.is_after_cutoff(l.Status),
        "source_file": l.Source_File, "dikonfirmasi_bank": l.Confirmed_By_Bank,
    } for l in lines]


@app.patch("/api/counterparty/lines/{line_id}")
def update_counterparty_line(line_id: int, status_value: str = Form("", alias="status"), db: Session = Depends(get_db)):
    """Koreksi status satu line oleh petugas BI (mis. menandai 'Dihapus'), lalu hitung ulang B4/B5."""
    line = db.get(CounterpartyLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Line tidak ditemukan.")
    ensure_period_unlocked(db, line.period_id)
    old = line.Status
    line.Status = status_value.strip() or None
    db.flush()
    period = db.get(EvaluationPeriod, line.period_id)
    result = _sync_counterparty(db, period)
    db.add(AuditTrail(
        action="CORRECT_COUNTERPARTY",
        performed_by="Petugas BI DPPK",
        details=f"{line.Bank_ID} {line.Instrument} {line.Counterparty_Nama}: status '{old}' -> '{line.Status}'.",
    ))
    db.commit()
    return {"status": "success", "breakdown": result["metrics"]["breakdown"].get(line.Bank_ID, {})}


@app.get("/api/confirmation/{bank_id}")
def download_confirmation_workbook(bank_id: str, db: Session = Depends(get_db)):
    """Workbook konfirmasi untuk satu bank (format template DPPK) dari data periode aktif."""
    bank = db.get(MasterBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Bank tidak ditemukan.")
    period = get_active_period(db)
    buf = build_confirmation_workbook(db, period, bank)
    name = confirmation_file_name(bank)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/confirmation-all")
def download_all_confirmation_workbooks(db: Session = Depends(get_db)):
    """ZIP berisi workbook konfirmasi ke-21 bank, bernama 'NN. Nama Bank.xlsx'."""
    import zipfile
    period = get_active_period(db)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for bank in db.query(MasterBank).order_by(MasterBank.No_Urut_Konfirmasi).all():
            z.writestr(confirmation_file_name(bank), build_confirmation_workbook(db, period, bank).getvalue())
    out.seek(0)
    return StreamingResponse(
        out, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="Konfirmasi Bank {period.Triwulan}.zip"'},
    )


# ==============================================================================
# 3. BALASAN BANK, RONDE KONFIRMASI & ITEM SANGGAHAN (Sprint 4)
# ==============================================================================


def _current_round(db: Session, period: EvaluationPeriod, create: bool = True) -> Optional[ConfirmationRound]:
    rnd = (db.query(ConfirmationRound).filter(ConfirmationRound.period_id == period.id)
           .order_by(ConfirmationRound.Round_No.desc()).first())
    if rnd is None and create:
        rnd = ConfirmationRound(period_id=period.id, Round_No=1, Note="Ronde pertama (dibuat otomatis saat impor balasan)")
        db.add(rnd)
        db.flush()
    return rnd


def _round_payload(r: ConfirmationRound) -> Dict[str, Any]:
    return {"round_no": r.Round_No, "opened_at": r.Opened_At.isoformat() if r.Opened_At else None,
            "deadline": r.Deadline, "note": r.Note}


def _real_period_or_400(db: Session) -> EvaluationPeriod:
    period = get_active_period(db)
    if period is None or not period.Working_Days_JSON:
        raise HTTPException(status_code=400, detail="Periode aktif belum memuat data ril. Proses file sumber terlebih dahulu.")
    ensure_period_unlocked(db, period.id)
    return period


def _history(item: DisputeItem, event: str, by: str, text: Optional[str] = None) -> None:
    hist = json.loads(item.History_JSON or "[]")
    hist.append({"at": datetime.utcnow().isoformat(timespec="seconds"), "ronde": item.Last_Round,
                 "event": event, "oleh": by, "catatan": text})
    item.History_JSON = json.dumps(hist)


def _upsert_items(db: Session, period: EvaluationPeriod, bank_id: str, items: List[Dict[str, Any]],
                  file_name: str, round_no: int) -> Dict[str, int]:
    """Simpan item sanggahan; item yang sama (bank, sumber, tanggal, tenor) diperbarui, bukan diduplikasi."""
    created = updated = reopened = 0
    for it in items:
        row = db.query(DisputeItem).filter(
            DisputeItem.period_id == period.id, DisputeItem.Bank_ID == bank_id,
            DisputeItem.Source == it["source"], DisputeItem.Tanggal == it["tanggal"], DisputeItem.Tenor == it["tenor"],
        ).first()
        if row is None:
            row = DisputeItem(
                period_id=period.id, Bank_ID=bank_id, Parameter_Code=it["param"], Source=it["source"],
                Tanggal=it["tanggal"], Tenor=it["tenor"], Nilai_BI=it["nilai_bi"], Nilai_Bank=it["nilai_bank"],
                Klaim_Bank_JSON=json.dumps(it["klaim"]) if it.get("klaim") else None,
                Keterangan_Bank=it["keterangan"], Source_File=file_name,
                Round_No=round_no, Last_Round=round_no, Status="OPEN",
            )
            db.add(row)
            _history(row, "DIAJUKAN", f"Bank ({bank_id})", it["keterangan"])
            created += 1
        else:
            if it["nilai_bank"] != "klaim di catatan/bukti" or not row.Nilai_Bank:
                row.Nilai_Bank = it["nilai_bank"]
            if it.get("klaim"):
                row.Klaim_Bank_JSON = json.dumps(it["klaim"])
            if it["keterangan"] and it["keterangan"] not in (row.Keterangan_Bank or ""):
                row.Keterangan_Bank = "; ".join(x for x in (row.Keterangan_Bank, it["keterangan"]) if x)[:2000]
            row.Source_File = file_name
            if round_no > row.Last_Round:
                row.Last_Round = round_no
                if row.Status == "DITOLAK":
                    row.Status = "OPEN"  # bank kembali menyanggah pada ronde baru
                    _history(row, "DIAJUKAN_ULANG", f"Bank ({bank_id})", it["keterangan"])
                    reopened += 1
            updated += 1
        db.flush()
    return {"baru": created, "diperbarui": updated, "dibuka_ulang": reopened}


def _apply_dispute_rate(db: Session, period: EvaluationPeriod, bank_id: str, source: str) -> Optional[Dict[str, Any]]:
    """Hitung ulang nilai parameter dari data harian BI + item DITERIMA, lalu sinkronkan matriks."""
    ds = db.query(SourceDataset).filter(SourceDataset.period_id == period.id, SourceDataset.Source == source,
                                        SourceDataset.Bank_ID == bank_id).first()
    if ds is None:
        return None
    acc = replies_service.accepted_overrides(db, period.id, bank_id).get((bank_id, source), [])
    rate, detail = replies_service.rate_with_overrides(source, json.loads(ds.Payload_JSON), acc)
    param = replies_service.PARAM_OF[source]
    entry = db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id,
                                             BankScoreMatrix.Bank_ID == bank_id).first()
    current = json.loads(entry.detail_metrics_json or "{}").get(param, {}) if entry else {}
    if "rate_sebelum_sanggahan" not in current:
        current["rate_sebelum_sanggahan"] = current.get("rate")
    current.update(detail)
    current["rate"] = rate
    current["sanggahan_diterima"] = len(acc)
    evaluate_and_sync_database(
        db=db, stage=period.Active_Threshold_Stage or "EARLY", period_id=period.id,
        raw_metrics={bank_id: {param: rate}}, breakdown_stats={bank_id: {param: current}},
    )
    return {"param": param, "rate": rate, "sanggahan_diterima": len(acc)}


def _reply_files_local() -> List[str]:
    root = default_dataset_dir()
    folders = [p for p in glob.glob(os.path.join(glob.escape(root), "*Confirmed*")) if os.path.isdir(p)]
    files = []
    for f in folders:
        for dirpath, _, names in os.walk(f):
            files += [os.path.join(dirpath, n) for n in names if not n.startswith("~$")]
    return sorted(files)


@app.get("/api/rounds")
def list_rounds(db: Session = Depends(get_db)):
    period = get_active_period(db)
    rows = (db.query(ConfirmationRound).filter(ConfirmationRound.period_id == period.id)
            .order_by(ConfirmationRound.Round_No).all()) if period else []
    return [_round_payload(r) for r in rows]


@app.post("/api/rounds")
def open_round(deadline: Optional[str] = Form(None), note: Optional[str] = Form(None), db: Session = Depends(get_db)):
    """Buka ronde konfirmasi baru (mis. setelah tanggapan BI dikirim ulang ke bank) dengan tenggat balasan."""
    period = _real_period_or_400(db)
    last = _current_round(db, period, create=False)
    rnd = ConfirmationRound(period_id=period.id, Round_No=(last.Round_No + 1) if last else 1,
                            Deadline=(deadline or None), Note=note)
    db.add(rnd)
    db.add(AuditTrail(action="OPEN_CONFIRMATION_ROUND", performed_by="Petugas BI DPPK",
                      details=f"Ronde konfirmasi {rnd.Round_No} {period.Triwulan} dibuka; tenggat {deadline or '-'}."))
    db.commit()
    return _round_payload(rnd)


@app.post("/api/replies/ingest")
async def ingest_bank_replies(
    files: Optional[List[UploadFile]] = File(None),
    bank_id: Optional[str] = Form(None, description="Paksa bank pemilik file unggahan (opsional)"),
    db: Session = Depends(get_db),
):
    """
    Impor balasan bank pada ronde berjalan: workbook dibandingkan dengan data harian BI per tanggal,
    bukti (PDF/gambar) dilampirkan, file yang tidak bisa diproses ditandai perlu tindakan manual.
    Tanpa `files`, dipakai folder balasan lokal (`[Confirmed] ...`) pada dataset ril.
    """
    period = _real_period_or_400(db)
    rnd = _current_round(db, period)
    resolver = EntityResolver(db)
    forced = db.get(MasterBank, bank_id) if bank_id else None

    # (nama file, sumber bytes/path, path tersimpan)
    entries: List[Tuple[str, Any, Optional[str]]] = []
    if files:
        target_dir = os.path.join(UPLOADS_DIR, "replies", period.Triwulan)
        os.makedirs(target_dir, exist_ok=True)
        for f in files:
            if not f.filename:
                continue
            data = await f.read()
            path = os.path.join(target_dir, os.path.basename(f.filename))
            with open(path, "wb") as out:
                out.write(data)
            entries.append((os.path.basename(f.filename), path, path))
    else:
        entries = [(os.path.basename(p), p, p) for p in _reply_files_local()]
    if not entries:
        raise HTTPException(status_code=400, detail="Tidak ada file balasan yang ditemukan.")

    # Kelompokkan per bank; bank file unggahan dikenali dari nama folder/file, isi sheet, atau pilihan petugas
    by_bank: Dict[str, Dict[str, list]] = {}
    unassigned = []
    opened: Dict[str, Any] = {}
    for name, src, stored in entries:
        kind = replies_service.file_kind(name)
        bank = forced or replies_service.bank_for_path(stored, resolver, db)
        if bank is None and kind == "WORKBOOK":
            try:
                opened[stored] = replies_service.read_workbook(stored)
                bank = replies_service.bank_from_sheets(opened[stored], resolver)
            except ValueError:
                pass
        if bank is None:
            unassigned.append({"file": name, "alasan": "bank pengirim tidak dikenali"})
            continue
        by_bank.setdefault(bank.Bank_ID, {"WORKBOOK": [], "BUKTI": [], "MANUAL": []})[kind].append((name, stored))

    for b_id, groups in by_bank.items():
        for k in groups:
            for n, stored in groups[k]:
                _record_upload(db, period.id, "BALASAN", b_id, n, stored, bool(files), f"ronde {rnd.Round_No}, {k.lower()}")

    # Pemetaan sheet manual dari impor sebelumnya tetap dipakai untuk file yang sama
    saved_maps: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in db.query(BankReply).filter(BankReply.period_id == period.id, BankReply.Kind == "WORKBOOK"):
        m = json.loads(r.Summary_JSON or "{}").get("pemetaan_manual")
        if m:
            saved_maps[(r.Bank_ID, r.File_Name)] = m

    summary = []
    for b_id, groups in sorted(by_bank.items()):
        evidence = [n for n, _ in groups["BUKTI"]]
        # Ronde sama + file sama -> ganti catatan lama (impor ulang idempoten)
        names = [n for k in groups for n, _ in groups[k]]
        db.query(BankReply).filter(BankReply.period_id == period.id, BankReply.Round_No == rnd.Round_No,
                                   BankReply.Bank_ID == b_id, BankReply.File_Name.in_(names)).delete(synchronize_session=False)
        bank_sum = {"bank_id": b_id, "workbook": [], "bukti": evidence, "manual": [], "item": {"baru": 0, "diperbarui": 0, "dibuka_ulang": 0}}
        for n, stored in groups["BUKTI"]:
            db.add(BankReply(period_id=period.id, Round_No=rnd.Round_No, Bank_ID=b_id, File_Name=n,
                             Stored_Path=stored, Kind="BUKTI"))
        for n, stored in groups["MANUAL"]:
            reason = replies_service.manual_reason(n)
            bank_sum["manual"].append({"file": n, "alasan": reason})
            db.add(BankReply(period_id=period.id, Round_No=rnd.Round_No, Bank_ID=b_id, File_Name=n,
                             Stored_Path=stored, Kind="MANUAL", Status_Note=reason))
        for n, stored in groups["WORKBOOK"]:
            try:
                sheets = opened.get(stored) or replies_service.read_workbook(stored)
            except ValueError as e:
                bank_sum["manual"].append({"file": n, "alasan": str(e)})
                db.add(BankReply(period_id=period.id, Round_No=rnd.Round_No, Bank_ID=b_id, File_Name=n,
                                 Stored_Path=stored, Kind="MANUAL", Status_Note=str(e)))
                continue
            overrides = saved_maps.get((b_id, n), {})
            wb_sum, counts, note = _process_reply_workbook(db, period, rnd.Round_No, b_id, n, sheets, evidence, overrides)
            for k in ("baru", "diperbarui", "dibuka_ulang"):
                bank_sum["item"][k] += counts[k]
            bank_sum["workbook"].append(wb_sum)
            db.add(BankReply(period_id=period.id, Round_No=rnd.Round_No, Bank_ID=b_id, File_Name=n,
                             Stored_Path=stored, Kind="WORKBOOK", Summary_JSON=json.dumps(wb_sum), Status_Note=note))
        summary.append(bank_sum)

    total_new = sum(s["item"]["baru"] for s in summary)
    db.add(AuditTrail(
        action="IMPORT_BANK_REPLIES", performed_by="Petugas BI DPPK",
        details=(f"Impor balasan ronde {rnd.Round_No} {period.Triwulan}: {len(entries)} file dari {len(summary)} bank; "
                 f"{total_new} item sanggahan baru; "
                 f"{sum(len(s['manual']) for s in summary)} file perlu tindakan manual."),
    ))
    db.commit()
    return {"status": "success", "round": _round_payload(rnd), "per_bank": summary, "unassigned": unassigned}


def _process_reply_workbook(db: Session, period: EvaluationPeriod, round_no: int, bank_id: str, file_name: str,
                            sheets: Dict[str, Any], evidence: List[str], overrides: Dict[str, str]):
    """Baca satu workbook balasan (dengan pemetaan sheet manual bila ada) dan simpan item sanggahannya."""
    year = int(json.loads(period.Working_Days_JSON)[0][:4])
    parsed = replies_service.parse_reply(sheets, overrides)
    diff = replies_service.diff_reply(db, period.id, bank_id, parsed, evidence, year)
    counts = _upsert_items(db, period, bank_id, diff["items"], file_name, round_no)
    wb_sum = {"file": file_name, "sheet": parsed["mapping"], "item": len(diff["items"]),
              "selisih_info": diff["info"], "catatan_bank": sorted({x for v in diff["notes"].values() for x in v}),
              **({"pemetaan_manual": overrides} if overrides else {})}
    note = None if parsed["data"] else "tidak memuat sheet kewajiban harian (mis. hanya counterparty)"
    return wb_sum, {**counts, "_keys": {(i["source"], i["tanggal"], i["tenor"]) for i in diff["items"]}}, note


@app.get("/api/replies/sheet-kinds")
def list_sheet_kinds():
    """Pilihan jenis sheet untuk pemetaan manual."""
    return [{"key": k, "label": v} for k, v in replies_service.SHEET_KINDS.items()]


@app.post("/api/replies/{reply_id}/mapping")
def remap_reply_workbook(reply_id: int, mapping: str = Form(..., description='JSON {"nama sheet": "jenis" | "abaikan"}'),
                         db: Session = Depends(get_db)):
    """
    Pemetaan sheet manual oleh petugas untuk workbook yang nama sheetnya tidak dikenali (E6-1).
    Workbook diproses ulang; item OPEN dari file ini yang tidak lagi terbentuk dihapus.
    """
    reply = db.get(BankReply, reply_id)
    if reply is None or reply.Kind != "WORKBOOK":
        raise HTTPException(status_code=404, detail="Workbook balasan tidak ditemukan.")
    period = db.get(EvaluationPeriod, reply.period_id)
    ensure_period_unlocked(db, period.id)
    try:
        overrides = {k: v for k, v in json.loads(mapping).items() if v}
    except ValueError:
        raise HTTPException(status_code=400, detail="Format pemetaan tidak valid.")
    bad = [v for v in overrides.values() if v not in replies_service.SHEET_KINDS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Jenis sheet tidak dikenal: {bad}")
    try:
        sheets = replies_service.read_workbook(reply.Stored_Path)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Workbook tidak dapat dibuka: {e}")
    unknown = [k for k in overrides if k not in sheets]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Sheet tidak ada di workbook: {unknown}")

    evidence = [r.File_Name for r in db.query(BankReply).filter(
        BankReply.period_id == period.id, BankReply.Bank_ID == reply.Bank_ID, BankReply.Kind == "BUKTI")]
    wb_sum, counts, note = _process_reply_workbook(db, period, reply.Round_No, reply.Bank_ID, reply.File_Name,
                                                   sheets, evidence, overrides)
    keys = counts.pop("_keys")
    stale = [it for it in db.query(DisputeItem).filter(
        DisputeItem.period_id == period.id, DisputeItem.Bank_ID == reply.Bank_ID,
        DisputeItem.Source_File == reply.File_Name, DisputeItem.Status == "OPEN")
        if (it.Source, it.Tanggal, it.Tenor) not in keys and len(json.loads(it.History_JSON or "[]")) <= 1]
    for it in stale:
        db.delete(it)
    reply.Summary_JSON, reply.Status_Note = json.dumps(wb_sum), note
    db.add(AuditTrail(action="REMAP_REPLY_SHEETS", performed_by="Petugas BI DPPK",
                      details=f"Pemetaan sheet manual {reply.Bank_ID} '{reply.File_Name}': {overrides}; "
                              f"{counts['baru']} item baru, {len(stale)} item dihapus."))
    db.commit()
    return {"status": "success", "summary": wb_sum, "item": {**counts, "dihapus": len(stale)}}


@app.get("/api/replies")
def list_bank_replies(db: Session = Depends(get_db)):
    """File balasan per bank pada periode aktif (workbook, bukti, perlu tindakan manual)."""
    period = get_active_period(db)
    if period is None:
        return []
    rows = db.query(BankReply).filter(BankReply.period_id == period.id).order_by(BankReply.Bank_ID, BankReply.Round_No).all()
    return [{
        "id": r.id, "bank_id": r.Bank_ID, "round_no": r.Round_No, "file": r.File_Name, "kind": r.Kind,
        "status_note": r.Status_Note, "summary": json.loads(r.Summary_JSON) if r.Summary_JSON else None,
        "received_at": r.Received_At.isoformat() if r.Received_At else None,
    } for r in rows]


@app.get("/api/replies/{reply_id}/file")
def get_reply_file(reply_id: int, db: Session = Depends(get_db)):
    """Berkas balasan/bukti untuk pratinjau in-app (PDF/gambar tampil inline)."""
    r = db.get(BankReply, reply_id)
    if r is None or not r.Stored_Path or not os.path.isfile(r.Stored_Path):
        raise HTTPException(status_code=404, detail="Berkas tidak ditemukan.")
    media = mimetypes.guess_type(r.File_Name)[0] or "application/octet-stream"
    return FileResponse(r.Stored_Path, media_type=media,
                        headers={"Content-Disposition": f'inline; filename="{quote(r.File_Name)}"'})


@app.get("/api/disputes")
def list_dispute_items(bank_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """
    Item sanggahan per tanggal, dikelompokkan per bank & parameter, lengkap dengan pre-check PADG,
    dampak bila diterima, dan tanda eskalasi (diperdebatkan >= 2 ronde).
    """
    period = get_active_period(db)
    if period is None:
        return {"round": None, "groups": []}
    stage = period.Active_Threshold_Stage or "EARLY"
    q = db.query(DisputeItem).filter(DisputeItem.period_id == period.id)
    if bank_id:
        q = q.filter(DisputeItem.Bank_ID == bank_id)
    items = q.order_by(DisputeItem.Bank_ID, DisputeItem.Parameter_Code, DisputeItem.Tanggal, DisputeItem.Tenor).all()
    banks = {b.Bank_ID: b for b in db.query(MasterBank).all()}
    evidence = {}
    for r in db.query(BankReply).filter(BankReply.period_id == period.id, BankReply.Kind == "BUKTI"):
        evidence.setdefault(r.Bank_ID, []).append({"id": r.id, "file": r.File_Name})
    matrix = {m.Bank_ID: m for m in db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id)}

    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for it in items:
        key = (it.Bank_ID, it.Source)
        if key not in groups:
            ds = db.query(SourceDataset).filter(SourceDataset.period_id == period.id, SourceDataset.Source == it.Source,
                                                SourceDataset.Bank_ID == it.Bank_ID).first()
            payload = json.loads(ds.Payload_JSON) if ds else None
            all_items = [x for x in items if (x.Bank_ID, x.Source) == key]
            accepted = [x for x in all_items if x.Status == "DITERIMA"]
            open_ = [x for x in all_items if x.Status == "OPEN"]
            rate_base = replies_service.rate_with_overrides(it.Source, payload, [])[0] if payload else None
            rate_now = replies_service.rate_with_overrides(it.Source, payload, accepted)[0] if payload else None
            rate_all = replies_service.rate_with_overrides(it.Source, payload, accepted + open_)[0] if payload else None
            m = matrix.get(it.Bank_ID)
            b = banks[it.Bank_ID]
            groups[key] = {
                "bank_id": it.Bank_ID, "nama_singkat": b.Nama_Singkat, "masked_alias": b.Masked_Alias,
                "parameter_code": it.Parameter_Code, "source": it.Source,
                "label": replies_service.SOURCE_LABEL[it.Source],
                "threshold": THRESHOLDS[stage].get(it.Parameter_Code, 80.0),
                "rate_rekap_bi": rate_base, "rate_sekarang": rate_now, "rate_jika_semua_diterima": rate_all,
                "status_parameter": None if m is None else getattr(m, f"{it.Parameter_Code.lower()}_passed"),
                "bukti": evidence.get(it.Bank_ID, []),
                "items": [], "_payload": payload, "_accepted": accepted, "_all": all_items,
            }
        g = groups[key]
        max_bps = None
        if it.Source in QUOTE_SOURCES and it.Tenor:
            max_bps = next((t["max_bps"] for t in QUOTE_SOURCES[it.Source]["tenors"] if t["key"] == it.Tenor), None)
        # Dampak dihitung bersama tenor lain pada tanggal yang sama: hari baru memenuhi bila semua tenornya diterima
        same_day = [x for x in g["_all"] if x.Tanggal == it.Tanggal and x.Status != "DITOLAK"]
        rate_one = (replies_service.rate_with_overrides(it.Source, g["_payload"], g["_accepted"] + same_day)[0]
                    if g["_payload"] and it.Status != "DITERIMA" else g["rate_sekarang"])
        pre = precheck_item(
            {"nilai_bi": it.Nilai_BI, "nilai_bank": it.Nilai_Bank, "keterangan": it.Keterangan_Bank}, max_bps,
            {"param": it.Parameter_Code, "rate_now": g["rate_sekarang"], "rate_if_accepted": rate_one,
             "threshold": g["threshold"], "same_day": len(same_day)},
        )
        g["items"].append({
            "id": it.id, "tanggal": it.Tanggal, "tenor": it.Tenor,
            "tenor_label": replies_service.TENOR_LABEL.get(it.Tenor or "", it.Tenor),
            "nilai_bi": it.Nilai_BI, "nilai_bank": it.Nilai_Bank, "keterangan_bank": it.Keterangan_Bank,
            "source_file": it.Source_File, "round_no": it.Round_No, "last_round": it.Last_Round,
            "status": it.Status, "decided_by": it.Decided_By, "decision_note": it.Decision_Note,
            "decided_at": it.Decided_At.isoformat() if it.Decided_At else None,
            "history": json.loads(it.History_JSON or "[]"), "precheck": pre,
            "perlu_keputusan_pimpinan": replies_service.needs_escalation(it),
        })
    out = []
    for g in groups.values():
        g.pop("_payload"), g.pop("_accepted"), g.pop("_all")
        g["jumlah"] = {s: sum(1 for x in g["items"] if x["status"] == s) for s in ("OPEN", "DITERIMA", "DITOLAK")}
        out.append(g)
    rnd = _current_round(db, period, create=False)
    return {"round": _round_payload(rnd) if rnd else None, "stage": stage, "groups": out}


@app.post("/api/disputes/{item_id}/decide")
def decide_dispute_item(
    item_id: int,
    decision: str = Form(..., description="DITERIMA, DITOLAK, atau OPEN (batalkan keputusan)"),
    note: Optional[str] = Form(None),
    verified_by: Optional[str] = Form("Petugas BI DPPK"),
    db: Session = Depends(get_db),
):
    """Keputusan petugas per item; nilai parameter dihitung ulang dari data harian + item yang diterima."""
    dec = decision.upper().strip()
    if dec not in ("DITERIMA", "DITOLAK", "OPEN"):
        raise HTTPException(status_code=400, detail="Keputusan harus DITERIMA, DITOLAK, atau OPEN.")
    item = db.get(DisputeItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item sanggahan tidak ditemukan.")
    period = ensure_period_unlocked(db, item.period_id)
    officer = verified_by or "Petugas BI DPPK"
    old = item.Status
    item.Status = dec
    item.Decided_By = None if dec == "OPEN" else officer
    item.Decided_At = None if dec == "OPEN" else datetime.utcnow()
    item.Decision_Note = note
    _history(item, {"DITERIMA": "DITERIMA", "DITOLAK": "DITOLAK", "OPEN": "KEPUTUSAN_DIBATALKAN"}[dec], officer, note)
    db.flush()
    result = _apply_dispute_rate(db, period, item.Bank_ID, item.Source)
    db.add(AuditTrail(
        action=f"DISPUTE_ITEM_{dec}", performed_by=officer,
        details=(f"{item.Bank_ID} {item.Parameter_Code} {item.Tanggal or '(agregat)'} {item.Tenor or ''}: {old} -> {dec}. "
                 f"Nilai {item.Parameter_Code} kini {result['rate'] if result else '-'}%. Catatan: {note or '-'}"),
    ))
    db.commit()
    return {"status": "success", "item_id": item.id, "decision": dec, "parameter": result}


@app.post("/api/disputes/manual")
def add_manual_dispute(
    bank_id: str = Form(...),
    source: str = Form(..., description="bbg-repo, bbg-srbi, bbg-ois, repo-2m, srbi-3b, mm-ois"),
    tanggal: str = Form(...),
    tenor: Optional[str] = Form(None),
    keterangan: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Catat sanggahan yang tidak terbaca otomatis (mis. disampaikan lewat surat/email atau file ber-password).
    Hanya untuk hari yang menurut data BI memang tidak memenuhi.
    """
    period = _real_period_or_400(db)
    if source not in replies_service.PARAM_OF or source == "srbi-ratio":
        raise HTTPException(status_code=400, detail="Sumber tidak valid untuk sanggahan per tanggal.")
    ds = db.query(SourceDataset).filter(SourceDataset.period_id == period.id, SourceDataset.Source == source,
                                        SourceDataset.Bank_ID == bank_id).first()
    if ds is None:
        raise HTTPException(status_code=400, detail="Data harian BI untuk bank & sumber ini belum ada.")
    bad = replies_service.invalid_on(source, json.loads(ds.Payload_JSON), tanggal)
    if tenor:
        bad = [b for b in bad if b[0] == tenor]
    if not bad:
        raise HTTPException(status_code=400, detail=f"Menurut data BI, {tanggal} sudah memenuhi; tidak ada yang perlu disanggah.")
    rnd = _current_round(db, period)
    counts = _upsert_items(db, period, bank_id, [
        {"source": source, "param": replies_service.PARAM_OF[source], "tanggal": tanggal, "tenor": t,
         "nilai_bi": v, "nilai_bank": "klaim manual (dicatat petugas)", "keterangan": keterangan, "klaim": None}
        for t, v in bad
    ], "dicatat manual", rnd.Round_No)
    db.add(AuditTrail(action="DISPUTE_ITEM_MANUAL", performed_by="Petugas BI DPPK",
                      details=f"Sanggahan manual {bank_id} {source} {tanggal}: {keterangan}"))
    db.commit()
    return {"status": "success", **counts}


@app.post("/api/evaluation/recalculate")
def recalculate_evaluation(
    stage: str = Query("EARLY", description="Tahap threshold: EARLY, INTERMEDIATE, END_STATE"),
    period_id: Optional[int] = Query(None, description="ID periode evaluasi (opsional)"),
    db: Session = Depends(get_db),
):
    """
    Evaluasi Threshold Dinamis PADG No. 23/2024:
    - Membandingkan nilai realisasi mentah dengan ambang batas (EARLY / INTERMEDIATE / END_STATE).
    - Menghitung skor bobot penuh jika lolos atau 0 jika gagal.
    - Menghitung total skor PUVA (maks 60%) dan status akhir bank.
    - Otomatis membuat atau memperbarui tiket temuan di FindingTicket untuk transaksi yang melanggar batas aturan.
    """
    stage_upper = stage.upper()
    if stage_upper not in THRESHOLDS:
        raise HTTPException(
            status_code=400,
            detail=f"Tahap threshold tidak valid. Pilihan yang tersedia: {list(THRESHOLDS.keys())}"
        )

    ensure_period_unlocked(db, period_id)
    sync_result = evaluate_and_sync_database(
        db=db,
        stage=stage_upper,
        period_id=period_id,
    )

    return {
        "status": "success",
        "message": f"Evaluasi matriks berhasil dihitung ulang menggunakan tahap ambang batas: {stage_upper}.",
        "data": sync_result,
    }


# ==============================================================================
# 4. MATRIKS SKOR & FINDINGS
# ==============================================================================
@app.get("/api/matrix")
def get_score_matrix(
    stage: str = Query("EARLY", description="(Diabaikan) tahap mengikuti periode aktif"),
    db: Session = Depends(get_db)
):
    """
    Matriks skor 21 Bank DU pada periode aktif: nilai realisasi sebelum threshold
    (null = sumber data belum diunggah), status lolos/gagal, skor berbobot, total PUVA (maks 60%).
    """
    period = get_active_period(db)
    if not period:
        return []
    records = (
        db.query(BankScoreMatrix).join(MasterBank)
        .filter(BankScoreMatrix.period_id == period.id)
        .order_by(MasterBank.Bank_ID).all()
    )
    results = []
    for r in records:
        b = r.bank
        detail_metrics = json.loads(r.detail_metrics_json) if r.detail_metrics_json else {}
        results.append({
            "bank_id": r.Bank_ID,
            "masked_alias": b.Masked_Alias,
            "nama_resmi_bank": b.Nama_Resmi_Bank,
            "nama_singkat": b.Nama_Singkat,
            "kelompok_kbmi": b.Kelompok_KBMI,
            "period": period.Triwulan,
            "raw_metrics": {c: getattr(r, f"{c.lower()}_raw") for c in PUVA_CODES},
            "passed_flags": {c: getattr(r, f"{c.lower()}_passed") for c in PUVA_CODES},
            "weighted_scores": {c: getattr(r, f"{c.lower()}_score") for c in PUVA_CODES},
            "total_puva_score": r.total_puva_score,
            "max_puva_score": MAX_PUVA_SCORE,
            "compliance_status": r.compliance_status,
            "detail_metrics": detail_metrics,
        })
    return results


@app.get("/api/findings")
def get_finding_tickets(
    bank_id: Optional[str] = Query(None, description="Filter berdasarkan Bank_ID spesifik"),
    db: Session = Depends(get_db)
):
    """Mengembalikan daftar tiket temuan dan sanggahan bank DU pada periode aktif."""
    query = db.query(FindingTicket).join(MasterBank)
    period = get_active_period(db)
    if period:
        query = query.filter(FindingTicket.period_id == period.id)
    if bank_id:
        query = query.filter(FindingTicket.Bank_ID == bank_id)
    tickets = query.order_by(FindingTicket.Finding_ID).all()
    results = []
    for t in tickets:
        b = t.bank
        detail_gugur = json.loads(t.Detail_Transaksi_Gugur) if t.Detail_Transaksi_Gugur else []
        results.append({
            "finding_id": t.Finding_ID,
            "bank_id": t.Bank_ID,
            "masked_alias": b.Masked_Alias,
            "nama_resmi_bank": b.Nama_Resmi_Bank,
            "parameter_code": t.Parameter_Code,
            "nilai_rekap_bi": t.Nilai_Rekap_BI,
            "detail_transaksi_gugur": detail_gugur,
            "nilai_klaim_bank": t.Nilai_Klaim_Bank,
            "alasan_sanggahan": t.Alasan_Sanggahan,
            "file_bukti_name": t.File_Bukti_Name,
            "ai_recommendation_status": t.AI_Recommendation_Status,
            "ai_analysis_text": t.AI_Analysis_Text,
            "bi_decision_status": t.BI_Decision_Status,
            "verified_by": t.Verified_By,
            "updated_at": t.Updated_At,
        })
    return results


@app.get("/api/audit-trail")
def get_audit_trail_logs(limit: int = Query(20), db: Session = Depends(get_db)):
    """Mengembalikan riwayat audit trail aktivitas verifikasi dan sistem evaluasi."""
    logs = db.query(AuditTrail).order_by(AuditTrail.id.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "timestamp": l.timestamp.isoformat(),
            "action": l.action,
            "performed_by": l.performed_by,
            "details": l.details,
        }
        for l in logs
    ]


# ==============================================================================
# 5. SNAPSHOT LOCKING & RE-OPENING
# ==============================================================================
class SnapshotLockRequest(BaseModel):
    locked_by: Optional[str] = "Tim Evaluasi DPPK"
    notes: Optional[str] = None


@app.get("/api/snapshot/status")
def get_snapshot_status(db: Session = Depends(get_db)):
    """
    Mengembalikan status penguncian snapshot evaluasi saat ini.
    """
    period = get_active_period(db)
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi.")

    matrices = db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id).all()
    full_pass = sum(1 for m in matrices if m.compliance_status == STATUS_MEMENUHI)
    tidak_memenuhi = sum(1 for m in matrices if m.compliance_status == STATUS_TIDAK_MEMENUHI)
    belum_lengkap = sum(1 for m in matrices if m.compliance_status == STATUS_DATA_BELUM_LENGKAP)

    return {
        "period": period.Triwulan,
        "stage": period.Active_Threshold_Stage,
        "is_locked": period.Is_Snapshot_Locked,
        "locked_at": period.Locked_At.isoformat() if period.Locked_At else None,
        "locked_by": period.Locked_By,
        "snapshot_id": period.Snapshot_ID,
        "summary": {
            "total_banks": len(matrices),
            "full_pass": full_pass,
            "tidak_memenuhi": tidak_memenuhi,
            "data_belum_lengkap": belum_lengkap,
        },
    }


@app.post("/api/snapshot/lock")
def lock_evaluation_snapshot(
    payload: Optional[SnapshotLockRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Membekukan versi akhir data evaluasi (Snapshot Locking):
    - Mengunci periode sehingga versi evaluasi immutable.
    - Menghasilkan Snapshot ID (e.g. SNP-2026Q2-FINAL).
    - Mencatat di Audit Trail.
    """
    period = get_active_period(db)
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi.")

    matrices = db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id).all()
    tickets = db.query(FindingTicket).filter(FindingTicket.period_id == period.id).all()

    snapshot_data = {
        "snapshot_id": f"SNP-{period.Triwulan}-FINAL",
        "period": period.Triwulan,
        "stage": period.Active_Threshold_Stage,
        "locked_at": datetime.utcnow().isoformat(),
        "locked_by": payload.locked_by if payload and payload.locked_by else "Tim Evaluasi DPPK",
        "total_banks": len(matrices),
        "matrices": [
            {
                "bank_id": m.Bank_ID,
                "compliance_status": m.compliance_status,
                "total_puva": m.total_puva_score,
            }
            for m in matrices
        ],
        "findings": [
            {
                "finding_id": t.Finding_ID,
                "bank_id": t.Bank_ID,
                "status": t.BI_Decision_Status,
            }
            for t in tickets
        ],
    }

    period.Is_Snapshot_Locked = True
    period.Locked_At = datetime.utcnow()
    period.Locked_By = payload.locked_by if payload and payload.locked_by else "Tim Evaluasi DPPK"
    period.Snapshot_ID = f"SNP-{period.Triwulan}-FINAL"
    period.Snapshot_Data_JSON = json.dumps(snapshot_data)

    audit = AuditTrail(
        action="SNAPSHOT_LOCKED",
        performed_by=period.Locked_By,
        details=f"Snapshot evaluasi {period.Triwulan} berhasil dikunci dengan ID {period.Snapshot_ID}.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": f"Snapshot evaluasi {period.Triwulan} berhasil dikunci.",
        "snapshot_id": period.Snapshot_ID,
        "locked_at": period.Locked_At.isoformat(),
        "locked_by": period.Locked_By,
    }


@app.post("/api/snapshot/unlock")
def unlock_evaluation_snapshot(db: Session = Depends(get_db)):
    """
    Membuka kembali kunci snapshot evaluasi untuk keperluan simulasi ulang / koreksi lanjutan.
    """
    period = get_active_period(db)
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi.")

    prev_snapshot_id = period.Snapshot_ID
    period.Is_Snapshot_Locked = False
    period.Locked_At = None
    period.Locked_By = None
    period.Snapshot_ID = None
    period.Snapshot_Data_JSON = None

    audit = AuditTrail(
        action="SNAPSHOT_UNLOCKED",
        performed_by="Tim Evaluasi DPPK",
        details=f"Kunci snapshot evaluasi {period.Triwulan} (sebelumnya {prev_snapshot_id}) dibuka kembali.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": f"Snapshot evaluasi {period.Triwulan} berhasil dibuka kembali (Re-opened).",
        "is_locked": False,
    }


# ==============================================================================
# 6. DOKUMEN AKHIR (format dokumen ril DPPK): M.02, M.01, lampiran, surat, matriks Excel
# ==============================================================================
def _document_period(db: Session) -> EvaluationPeriod:
    period = get_active_period(db)
    if period is None or not period.Working_Days_JSON:
        raise HTTPException(status_code=400, detail="Periode aktif belum memuat data ril. Proses file sumber terlebih dahulu.")
    return period


@app.get("/api/documents/preview")
def documents_preview(db: Session = Depends(get_db)):
    """Isi dokumen akhir (matriks, keterangan, kalimat memo, eskalasi) untuk pratinjau di UI."""
    period = _document_period(db)
    ev = documents_service.build_evaluation(db, period)
    return {**ev, "memo": documents_service.memo_points(ev),
            "files": {k: documents_service.file_name(k, ev) for k in [*documents_service.DOC_KINDS, "paket"]}}


@app.get("/api/documents/{kind}")
def documents_download(kind: str, db: Session = Depends(get_db)):
    """Unduh satu dokumen (m02, m02-lampiran, m01, m01-lampiran, surat, matriks) atau paket zip semuanya."""
    if kind not in documents_service.DOC_KINDS and kind != "paket":
        raise HTTPException(status_code=404, detail=f"Jenis dokumen tidak dikenal: {kind}")
    period = _document_period(db)
    ev = documents_service.build_evaluation(db, period)
    stream, name, media = documents_service.generate(kind, ev, db, period)
    db.add(AuditTrail(
        action="GENERATE_DOCUMENT", performed_by="Tim Evaluasi DPPK",
        details=f"{name} ({'snapshot terkunci' if period.Is_Snapshot_Locked else 'DRAFT, snapshot belum dikunci'})",
    ))
    db.commit()
    return StreamingResponse(stream, media_type=media, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
