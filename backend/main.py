import io
import os
import re
import json
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import engine, Base, get_db, ensure_schema
from models import get_active_period, MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
from seed import seed_database, get_dataset_folder
from services.entity_resolution import EntityResolver
from services.rule_engine import (
    THRESHOLDS,
    WEIGHTS,
    PARAMETER_NAMES,
    PARAMETER_DETAILS,
    calculate_puva_raw_metrics,
    evaluate_and_sync_database,
    compute_matrix_scores,
    matrix_to_raw,
    canonical_code,
    parse_claim_percent,
    PUVA_CODES,
    MAX_PUVA_SCORE,
    STATUS_MEMENUHI,
    STATUS_TIDAK_MEMENUHI,
    STATUS_DATA_BELUM_LENGKAP,
)

# Periode dataset sample sintetis (dipakai parser lama untuk B1-B5, B7 sampai parser data ril selesai)
SAMPLE_PERIOD = "2026-Q2"
from services.worksheet_splitter import generate_bank_worksheet
from services.ai_reconciliation import analyze_dispute_with_ai
from services.real_ingest import INGESTERS, SOURCES, IngestError, find_default_file, period_from_dates
from services.doc_generator import (
    generate_memo_docx,
    generate_attachments_xlsx,
    get_memo_preview_data,
)

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
        seed_database(db=db, force_reseed=False)
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
        "is_sample_data": period.Triwulan == SAMPLE_PERIOD,
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


@app.get("/api/etl/entities")
def get_entity_resolution_map(db: Session = Depends(get_db)):
    """Menampilkan tabel referensi Entity Resolution untuk pencocokan multi-sumber."""
    resolver = EntityResolver(db)
    return {
        "total_banks": len(resolver.banks),
        "entities": resolver.get_resolution_table(),
    }


# ==============================================================================
# 2. SMART ETL & MULTI-SOURCE PARSER (POST /api/etl/upload)
# ==============================================================================
@app.post("/api/etl/upload")
async def upload_and_process_etl(
    file_quotes: Optional[UploadFile] = File(None),
    file_survey: Optional[UploadFile] = File(None),
    file_hartis: Optional[UploadFile] = File(None),
    file_antasena: Optional[UploadFile] = File(None),
    use_sample_datasets: bool = Form(False),
    stage: str = Form("EARLY"),
    db: Session = Depends(get_db),
):
    """
    Parser Multi-Sumber Smart ETL:
    - Menerima upload file Excel mentah (Bloomberg/SPPA, Survey, HARTIS, DS Antasena)
      atau membaca ulang dari folder sample dataset (untuk Live Demo).
    - Melakukan Entity Resolution otomatis mencocokkan ticker/kode/nama ke Bank_ID (DU-01 s.d. DU-21).
    - Menghitung 9 Indikator PUVA (B1 - B8) berdasarkan 60 hari kerja.
    - Mengupdate matriks skor dan tiket temuan di database.
    """
    sample_period = _get_or_create_period(db, 2026, SAMPLE_PERIOD)
    ensure_period_unlocked(db, sample_period.id)
    resolver = EntityResolver(db)
    dataset_dir = get_dataset_folder()

    try:
        # 1. Baca File Quotes (Bloomberg & SPPA - B1, B2, B3)
        if file_quotes and file_quotes.filename:
            content = await file_quotes.read()
            df_quotes = pd.read_excel(io.BytesIO(content))
        else:
            df_quotes = pd.read_excel(os.path.join(dataset_dir, "01_Raw_Kuotasi_Bloomberg_SPPA.xlsx"))

        # 2. Baca File Survey (Counterparty Line - B4, B5)
        if file_survey and file_survey.filename:
            content = await file_survey.read()
            df_survey = pd.read_excel(io.BytesIO(content))
        else:
            df_survey = pd.read_excel(os.path.join(dataset_dir, "02_Raw_Survey_Counterparty_Line.xlsx"))

        # 3. Baca File HARTIS (Lelang Perdana & Sekunder - B6, B7a, B7b)
        if file_hartis and file_hartis.filename:
            content = await file_hartis.read()
            hartis_bytes = io.BytesIO(content)
            df_hartis_p = pd.read_excel(hartis_bytes, sheet_name="Lelang_Perdana_SRBI")
            hartis_bytes.seek(0)
            df_hartis_s = pd.read_excel(hartis_bytes, sheet_name="Transaksi_Pasar_Sekunder")
        else:
            f03_path = os.path.join(dataset_dir, "03_Raw_HARTIS_Transaksi.xlsx")
            df_hartis_p = pd.read_excel(f03_path, sheet_name="Lelang_Perdana_SRBI")
            df_hartis_s = pd.read_excel(f03_path, sheet_name="Transaksi_Pasar_Sekunder")

        # 4. Baca File Antasena (Matchmaking OIS - B8)
        if file_antasena and file_antasena.filename:
            content = await file_antasena.read()
            df_antasena = pd.read_excel(io.BytesIO(content))
        else:
            df_antasena = pd.read_excel(os.path.join(dataset_dir, "04_Raw_DS_Antasena_Matchmaking_OIS.xlsx"))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gagal membaca file Excel input: {str(e)}"
        )

    # Jalankan Rule Engine kalkulasi mentah
    raw_metrics, failed_tx, breakdown_stats = calculate_puva_raw_metrics(
        df_quotes=df_quotes,
        df_survey=df_survey,
        df_hartis_p=df_hartis_p,
        df_hartis_s=df_hartis_s,
        df_antasena=df_antasena,
        resolver=resolver,
        total_working_days=60,
    )

    # Sinkronisasi ke Database SQLite
    sync_result = evaluate_and_sync_database(
        db=db,
        stage=stage,
        period_id=sample_period.id,
        raw_metrics=raw_metrics,
        failed_transactions=failed_tx,
        breakdown_stats=breakdown_stats,
    )

    # Catat ke Audit Trail
    audit = AuditTrail(
        action="ETL_PIPELINE_EXECUTED",
        performed_by="Smart ETL Multi-Source Parser",
        details=f"Proses ETL sukses. Baris kuotasi: {len(df_quotes)}, baris HARTIS sekunder: {len(df_hartis_s)}. Tahap: {stage.upper()}.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": "Data mentah multi-sumber berhasil diproses dan disinkronkan ke Database Evaluasi PUVA.",
        "processed_rows": {
            "quotes_bloomberg_sppa": len(df_quotes),
            "survey_counterparty": len(df_survey),
            "hartis_primary": len(df_hartis_p),
            "hartis_secondary": len(df_hartis_s),
            "antasena_matchmaking": len(df_antasena),
        },
        "evaluation_summary": sync_result,
        "sample_disputes_verified": len(failed_tx),
    }


# ==============================================================================
# 3. DYNAMIC THRESHOLD EVALUATION (POST /api/evaluation/recalculate)
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


# ==============================================================================
# 5. TAHAP 4: BANK SANGGAHAN SUBMISSION & AI RECONCILIATION CENTER
# ==============================================================================

@app.post("/api/disputes/submit")
async def submit_bank_dispute(
    finding_id: str = Form(...),
    nilai_klaim_bank: str = Form(...),
    alasan_sanggahan: str = Form(...),
    file_bukti: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Mode Portal DU: Bank mengajukan klarifikasi / sanggahan atas suatu Finding_ID
    lengkap dengan angka klaim, narasi alasan, dan berkas bukti (.pdf/.xlsx/.png).
    """
    ticket = db.query(FindingTicket).filter(FindingTicket.Finding_ID == finding_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Tiket Temuan '{finding_id}' tidak ditemukan.")
    ensure_period_unlocked(db, ticket.period_id)

    # Simpan berkas bukti jika ada
    saved_filename = ticket.File_Bukti_Name
    if file_bukti and file_bukti.filename:
        clean_fn = f"{finding_id}_{os.path.basename(file_bukti.filename)}"
        target_path = os.path.join(UPLOADS_DIR, clean_fn)
        with open(target_path, "wb") as f_out:
            shutil.copyfileobj(file_bukti.file, f_out)
        saved_filename = clean_fn

    # Update tiket sanggahan
    ticket.Nilai_Klaim_Bank = nilai_klaim_bank
    ticket.Alasan_Sanggahan = alasan_sanggahan
    ticket.File_Bukti_Name = saved_filename
    ticket.BI_Decision_Status = "PENDING_REVIEW"
    ticket.Updated_At = datetime.utcnow()

    # Catat ke Audit Trail
    audit = AuditTrail(
        action="DISPUTE_SUBMITTED",
        performed_by=f"Bank DU ({ticket.Bank_ID})",
        details=f"Pengajuan sanggahan untuk {finding_id} ({ticket.Parameter_Code}): Klaim '{nilai_klaim_bank}', Berkas: '{saved_filename or 'Tidak ada'}'.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": f"Sanggahan untuk tiket {finding_id} berhasil diajukan dan berstatus PENDING_REVIEW.",
        "data": {
            "finding_id": ticket.Finding_ID,
            "bank_id": ticket.Bank_ID,
            "parameter_code": ticket.Parameter_Code,
            "nilai_klaim_bank": ticket.Nilai_Klaim_Bank,
            "alasan_sanggahan": ticket.Alasan_Sanggahan,
            "file_bukti_name": ticket.File_Bukti_Name,
            "bi_decision_status": ticket.BI_Decision_Status,
            "updated_at": ticket.Updated_At.isoformat(),
        },
    }


@app.post("/api/reconciliation/{finding_id}/analyze")
def analyze_finding_with_ai(finding_id: str, db: Session = Depends(get_db)):
    """
    AI Evidence Checker:
    Memeriksa klaim bank dan bukti dokumen terhadap aturan mutlak PADG No. 23/2024.
    Menggunakan Gemini API jika GEMINI_API_KEY tersedia,
    atau Fallback Deterministic Rule Analyzer.
    Nama bank di-masking ke alias demi kerahasiaan perbankan.
    """
    ticket = db.query(FindingTicket).join(MasterBank).filter(FindingTicket.Finding_ID == finding_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Tiket Temuan '{finding_id}' tidak ditemukan.")

    period = ensure_period_unlocked(db, ticket.period_id)
    stage = period.Active_Threshold_Stage if period else "EARLY"

    failed_details = json.loads(ticket.Detail_Transaksi_Gugur) if ticket.Detail_Transaksi_Gugur else []

    # Jalankan AI Evidence Checker
    ai_result = analyze_dispute_with_ai(
        finding_id=ticket.Finding_ID,
        bank_alias=ticket.bank.Masked_Alias,
        parameter_code=ticket.Parameter_Code,
        rekap_bi=ticket.Nilai_Rekap_BI,
        klaim_bank=ticket.Nilai_Klaim_Bank,
        alasan_sanggahan=ticket.Alasan_Sanggahan,
        file_bukti_name=ticket.File_Bukti_Name,
        failed_details=failed_details,
        stage=stage,
    )

    # Simpan hasil AI ke tiket
    ticket.AI_Recommendation_Status = ai_result["recommendation_status"]
    ticket.AI_Analysis_Text = ai_result["analysis_text"]
    ticket.Updated_At = datetime.utcnow()

    # Catat di Audit Trail
    audit = AuditTrail(
        action="AI_VERIFICATION_ANALYSIS",
        performed_by=f"AI Engine ({ai_result.get('engine_used', 'Gemini')})",
        details=f"Analisis verifikasi bukti untuk {finding_id}: Status {ai_result['recommendation_status']}.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "finding_id": ticket.Finding_ID,
        "bank_alias": ticket.bank.Masked_Alias,
        "ai_result": ai_result,
        "updated_at": ticket.Updated_At.isoformat(),
    }


@app.post("/api/reconciliation/{finding_id}/decide")
def decide_finding_dispute(
    finding_id: str,
    decision: str = Form(..., description="'APPROVED' atau 'REJECTED'"),
    verified_by: Optional[str] = Form("Petugas BI DPPK"),
    notes: Optional[str] = Form(None),
    approved_value: Optional[float] = Form(None, description="Nilai realisasi (%) yang ditetapkan petugas. Default: angka klaim bank."),
    db: Session = Depends(get_db),
):
    """
    Kontrol Human-in-the-Loop Petugas BI:
    Mengeksekusi keputusan final ('APPROVED' atau 'REJECTED'):
    - Jika APPROVED: nilai realisasi parameter diganti dengan nilai yang disetujui
      (approved_value, atau angka klaim bank), lalu skor dihitung ulang terhadap threshold
      aktif. Parameter hanya menjadi lolos bila nilai tersebut memang memenuhi threshold.
    - Jika REJECTED: Mempertahankan temuan dan mencatat penolakan di Audit Trail.
    """
    dec_upper = decision.upper().strip()
    if dec_upper not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Keputusan harus berupa 'APPROVED' atau 'REJECTED'.")

    ticket = db.query(FindingTicket).join(MasterBank).filter(FindingTicket.Finding_ID == finding_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Tiket Temuan '{finding_id}' tidak ditemukan.")

    period = ensure_period_unlocked(db, ticket.period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi.")
    stage = period.Active_Threshold_Stage or "EARLY"

    # Matriks skor bank pada periode yang sama dengan tiket
    matrix_entry = db.query(BankScoreMatrix).filter(
        BankScoreMatrix.Bank_ID == ticket.Bank_ID,
        BankScoreMatrix.period_id == period.id,
    ).first()
    if not matrix_entry:
        raise HTTPException(status_code=404, detail=f"Matriks skor {ticket.Bank_ID} untuk periode {period.Triwulan} tidak ditemukan.")

    param_code = canonical_code(ticket.Parameter_Code)
    threshold_val = THRESHOLDS.get(stage, THRESHOLDS["EARLY"]).get(param_code, 80.0)
    officer = verified_by or "Petugas BI DPPK"

    if dec_upper == "APPROVED":
        # 1. Tentukan nilai yang disetujui: input petugas > angka klaim bank
        final_val = approved_value
        if final_val is None:
            final_val = parse_claim_percent(ticket.Nilai_Klaim_Bank)
        if final_val is None:
            raise HTTPException(
                status_code=400,
                detail="Klaim bank tidak memuat angka persentase. Isi 'approved_value' (nilai realisasi yang disetujui) untuk menyetujui sanggahan.",
            )
        if not 0.0 <= final_val <= 100.0:
            raise HTTPException(status_code=400, detail="Nilai yang disetujui harus berada di rentang 0 - 100%.")

        # 2. Terapkan nilai lalu hitung ulang seluruh skor dengan Rule Engine
        raw = matrix_to_raw(matrix_entry)
        raw[param_code] = max(raw.get(param_code, 0.0), final_val)
        scores = compute_matrix_scores(raw, stage=stage)
        for k, v in scores.items():
            if hasattr(matrix_entry, k):
                setattr(matrix_entry, k, v)
        matrix_entry.updated_at = datetime.utcnow()

        ticket.Approved_Value = final_val
        now_passed = scores.get(f"{param_code.lower()}_passed", False)
        audit_detail = (
            f"Petugas {officer} MENYETUJUI sanggahan {ticket.Finding_ID} ({ticket.bank.Masked_Alias}). "
            f"Parameter {param_code} disesuaikan menjadi {raw[param_code]:.2f}% "
            f"({'LOLOS' if now_passed else 'tetap DI BAWAH'} threshold {stage} {threshold_val:.1f}%). "
            f"Skor PUVA baru: {matrix_entry.total_puva_score}% (Status: {matrix_entry.compliance_status})."
        )
    else:
        ticket.Approved_Value = None
        audit_detail = (
            f"Petugas {officer} MENOLAK sanggahan {ticket.Finding_ID} ({ticket.bank.Masked_Alias}). "
            f"Status temuan dipertahankan. Catatan: '{notes or 'Tidak memenuhi ketentuan PADG No. 23/2024'}'."
        )

    ticket.BI_Decision_Status = dec_upper
    ticket.Verified_By = officer
    ticket.Updated_At = datetime.utcnow()

    # Catat di Audit Trail
    audit = AuditTrail(
        action=f"DISPUTE_DECISION_{dec_upper}",
        performed_by=ticket.Verified_By,
        details=audit_detail,
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": f"Keputusan '{dec_upper}' untuk tiket {finding_id} berhasil diterapkan.",
        "data": {
            "finding_id": ticket.Finding_ID,
            "decision": ticket.BI_Decision_Status,
            "verified_by": ticket.Verified_By,
            "updated_bank_matrix": {
                "bank_id": matrix_entry.Bank_ID,
                "alias": ticket.bank.Masked_Alias,
                "total_puva_score": matrix_entry.total_puva_score,
                "compliance_status": matrix_entry.compliance_status,
            },
        },
    }


# ==============================================================================
# 6. EWS AUTOMATED NOTIFICATION & AUDIT TRAIL ENDPOINTS
# ==============================================================================

@app.post("/api/notifications/ews/send-reminder")
def send_ews_reminder(bank_id: str = Form(...), db: Session = Depends(get_db)):
    """
    Simulasi pengiriman email pengingat Early Warning System (EWS) otomatis
    kepada tim kepatuhan Dealer Utama terkait parameter yang di bawah ambang batas.
    """
    bank = db.query(MasterBank).filter(MasterBank.Bank_ID == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Bank '{bank_id}' tidak ditemukan.")

    period = get_active_period(db)
    matrix_entry = db.query(BankScoreMatrix).filter(
        BankScoreMatrix.Bank_ID == bank.Bank_ID,
        BankScoreMatrix.period_id == (period.id if period else None),
    ).first()

    # Kumpulkan parameter yang gugur (None = data belum ada, bukan gugur)
    failed_params = []
    if matrix_entry:
        for p in PUVA_CODES:
            if getattr(matrix_entry, f"{p.lower()}_passed", None) is False:
                failed_params.append(p)

    recipient = f"compliance.puva@{bank.Kode_SPPA_Antasena.lower()}.co.id"
    subject = f"[PERINGATAN DINI - EWS BI] Pemenuhan Kewajiban Dealer Utama PUVA {bank.Masked_Alias}"

    audit = AuditTrail(
        action="EWS_REMINDER_EMAIL_SENT",
        performed_by="System Early Warning Notifier",
        details=f"Email EWS otomatis terkirim ke {recipient}. Parameter perhatian: {', '.join(failed_params) if failed_params else 'Nihil'}.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "message": f"Email pengingat EWS resmi berhasil dikirimkan ke Tim Kepatuhan {bank.Masked_Alias}.",
        "delivery_receipt": {
            "recipient": recipient,
            "bank_id": bank.Bank_ID,
            "bank_alias": bank.Masked_Alias,
            "subject": subject,
            "failed_parameters": failed_params,
            "sent_at": datetime.utcnow().isoformat(),
        },
    }


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
# 7. AUTO-SPLITTER WORKSHEET PER BANK (GET /api/export/worksheet/{bank_id})
# ==============================================================================
@app.get("/api/export/worksheet/{bank_id}")
def export_single_bank_worksheet(bank_id: str, db: Session = Depends(get_db)):
    """
    Auto-Splitter Worksheet Per Bank:
    Menghasilkan file Excel resmi (.xlsx) khusus 1 bank DU yang berisi:
    1. Sheet 'Ringkasan_Evaluasi': Skor B1-B8 PUVA & OM serta rekomendasi kelulusan.
    2. Sheet 'Daftar_Temuan': Tiket Finding_ID sanggahan.
    3. Sheet 'Transaksi_Gugur': Rincian baris transaksi mentah yang didiskualifikasi oleh aturan PADG.
    """
    bank = db.query(MasterBank).filter(MasterBank.Bank_ID == bank_id).first()
    if not bank:
        bank = db.query(MasterBank).filter(MasterBank.Masked_Alias == bank_id).first()
    if not bank:
        raise HTTPException(
            status_code=404,
            detail=f"Bank Dealer Utama dengan ID atau Alias '{bank_id}' tidak ditemukan."
        )

    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"

    try:
        excel_stream = generate_bank_worksheet(db, bank.Bank_ID)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kesalahan saat menghasilkan worksheet: {str(e)}"
        )

    clean_alias = bank.Masked_Alias.replace(" ", "_")
    filename = f"Worksheet_Evaluasi_PUVA_{clean_alias}_{bank.Bank_ID}_{triwulan_str}.xlsx"

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


# ==============================================================================
# 8. SNAPSHOT LOCKING & RE-OPENING
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
# 9. AUTOMATED DOCUMENT GENERATOR (WORD M.02 / M.01 & EXCEL 3-LAMPIRAN)
# ==============================================================================
class MemoGenerateRequest(BaseModel):
    custom_narration: Optional[str] = None
    masked: Optional[bool] = False


@app.get("/api/export/preview/{memo_type}")
def get_memo_preview(
    memo_type: str,
    masked: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Mengembalikan data struktural memorandum (M.02 atau M.01) untuk live preview di web UI.
    """
    preview = get_memo_preview_data(db, memo_type=memo_type, masked=masked)
    return preview


@app.get("/api/export/memo/{memo_type}")
def export_memo_word_get(
    memo_type: str,
    masked: bool = Query(False),
    narration: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Menghasilkan file Microsoft Word (.docx) resmi:
    - M.02: Memorandum Evaluasi ke Pimpinan DPPK
    - M.01: Memorandum Pengantar Hasil Evaluasi ke DSMM
    """
    memo_type_clean = memo_type.lower()
    if memo_type_clean not in ["m02", "m01"]:
        raise HTTPException(status_code=400, detail="memo_type harus berupa 'm02' atau 'm01'.")

    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"

    try:
        docx_stream = generate_memo_docx(
            db=db,
            memo_type=memo_type_clean,
            custom_narration=narration,
            masked=masked,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kesalahan saat membuat memorandum Word: {str(e)}",
        )

    code_label = "M02_DPPK" if memo_type_clean == "m02" else "M01_DSMM"
    filename = f"Memorandum_{code_label}_Evaluasi_PUVA_{triwulan_str}.docx"

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    return StreamingResponse(
        docx_stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.post("/api/export/memo/{memo_type}/generate")
def export_memo_word_post(
    memo_type: str,
    payload: MemoGenerateRequest,
    db: Session = Depends(get_db),
):
    """
    Menghasilkan file Word (.docx) dengan narasi eksekutif kustom yang diedit pengguna pada UI.
    """
    return export_memo_word_get(
        memo_type=memo_type,
        masked=payload.masked or False,
        narration=payload.custom_narration,
        db=db,
    )


@app.get("/api/export/attachments")
def export_official_attachments(
    masked: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Menghasilkan file Microsoft Excel (.xlsx) Paket 3 Lampiran Resmi:
    - Sheet 1: Lampiran 1 - Sebelum Threshold (Capaian Mentah)
    - Sheet 2: Lampiran 2 - Setelah Threshold (Skor Terbobot & Komposit)
    - Sheet 3: Lampiran 3 - Tindak Lanjut (Status Kepatuhan & Rekomendasi Sanksi/Pembinaan)
    """
    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"

    try:
        excel_stream = generate_attachments_xlsx(db=db, masked=masked)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kesalahan saat menghasilkan berkas lampiran Excel: {str(e)}",
        )

    filename = f"Paket_3_Lampiran_Resmi_PUVA_{triwulan_str}.xlsx"

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
