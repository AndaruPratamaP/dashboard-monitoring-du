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

from database import engine, Base, get_db
from models import MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
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
)
from services.worksheet_splitter import generate_bank_worksheet
from services.ai_reconciliation import analyze_dispute_with_ai
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
    """Mengembalikan konfigurasi threshold, bobot, dan nama parameter PUVA & OM."""
    return {
        "thresholds": THRESHOLDS,
        "weights": WEIGHTS,
        "parameters": PARAMETER_NAMES,
        "details": PARAMETER_DETAILS,
    }


@app.get("/api/period")
def get_active_period(db: Session = Depends(get_db)):
    """Mengembalikan periode evaluasi yang aktif saat ini."""
    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi")
    return {
        "id": period.id,
        "tahun": period.Tahun,
        "triwulan": period.Triwulan,
        "active_threshold_stage": period.Active_Threshold_Stage,
        "is_snapshot_locked": period.Is_Snapshot_Locked,
        "locked_at": period.Locked_At,
    }


@app.get("/api/banks")
def get_all_banks(db: Session = Depends(get_db)):
    """Mengembalikan daftar 21 Bank Dealer Utama beserta data master dan aliasing."""
    banks = db.query(MasterBank).order_by(MasterBank.Bank_ID).all()
    return [
        {
            "bank_id": b.Bank_ID,
            "masked_alias": b.Masked_Alias,
            "nama_resmi_bank": b.Nama_Resmi_Bank,
            "kelompok_kbmi": b.Kelompok_KBMI,
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
    - Menghitung skor komposit (PUVA maks 60% + OM maks 40%) dan status rekomendasi akhir.
    - Otomatis membuat atau memperbarui tiket temuan di FindingTicket untuk transaksi yang melanggar batas aturan.
    """
    stage_upper = stage.upper()
    if stage_upper not in THRESHOLDS:
        raise HTTPException(
            status_code=400,
            detail=f"Tahap threshold tidak valid. Pilihan yang tersedia: {list(THRESHOLDS.keys())}"
        )

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
    stage: str = Query("EARLY", description="Stage threshold: EARLY, INTERMEDIATE, END_STATE"),
    db: Session = Depends(get_db)
):
    """
    Mengembalikan seluruh matriks skor 21 Bank DU (PUVA + OM) lengkap dengan
    nilai mentah sebelum threshold, status lolos/gagal, skor berbobot, dan status kepatuhan.
    """
    records = db.query(BankScoreMatrix).join(MasterBank).order_by(MasterBank.Bank_ID).all()
    results = []
    for r in records:
        b = r.bank
        detail_metrics = json.loads(r.detail_metrics_json) if r.detail_metrics_json else {}
        results.append({
            "bank_id": r.Bank_ID,
            "masked_alias": b.Masked_Alias,
            "nama_resmi_bank": b.Nama_Resmi_Bank,
            "kelompok_kbmi": b.Kelompok_KBMI,
            "raw_metrics": {
                "B1": r.b1_raw, "B2": r.b2_raw, "B3": r.b3_raw,
                "B4": r.b4_raw, "B5": r.b5_raw,
                "B6": r.b6_raw, "B7a": r.b7a_raw, "B7b": r.b7b_raw, "B8": r.b8_raw,
                "OM1": r.om1_raw, "OM2": r.om2_raw, "OM3": r.om3_raw,
            },
            "passed_flags": {
                "B1": r.b1_passed, "B2": r.b2_passed, "B3": r.b3_passed,
                "B4": r.b4_passed, "B5": r.b5_passed,
                "B6": r.b6_passed, "B7a": r.b7a_passed, "B7b": r.b7b_passed, "B8": r.b8_passed,
                "OM1": r.om1_passed, "OM2": r.om2_passed, "OM3": r.om3_passed,
            },
            "weighted_scores": {
                "B1": r.b1_score, "B2": r.b2_score, "B3": r.b3_score,
                "B4": r.b4_score, "B5": r.b5_score,
                "B6": r.b6_score, "B7a": r.b7a_score, "B7b": r.b7b_score, "B8": r.b8_score,
                "OM1": r.om1_score, "OM2": r.om2_score, "OM3": r.om3_score,
            },
            "total_puva_score": r.total_puva_score,
            "total_om_score": r.total_om_score,
            "composite_score": r.composite_score,
            "compliance_status": r.compliance_status,
            "detail_metrics": detail_metrics,
        })
    return results


@app.get("/api/findings")
def get_finding_tickets(
    bank_id: Optional[str] = Query(None, description="Filter berdasarkan Bank_ID spesifik"),
    db: Session = Depends(get_db)
):
    """Mengembalikan daftar tiket temuan dan sanggahan bank DU."""
    query = db.query(FindingTicket).join(MasterBank)
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
    Menggunakan google-genai (Gemini 2.5 Flash) jika GEMINI_API_KEY tersedia,
    atau Fallback Deterministic Rule Analyzer.
    Nama bank di-masking ke alias demi kerahasiaan perbankan.
    """
    ticket = db.query(FindingTicket).join(MasterBank).filter(FindingTicket.Finding_ID == finding_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Tiket Temuan '{finding_id}' tidak ditemukan.")

    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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
    db: Session = Depends(get_db),
):
    """
    Kontrol Human-in-the-Loop Petugas BI:
    Mengeksekusi keputusan final ('APPROVED' atau 'REJECTED'):
    - Jika APPROVED: Otomatis memperbarui nilai pemenuhan bank menjadi lolos threshold,
      menghitung ulang skor subtotal PUVA & komposit, serta mencatat di Audit Trail.
    - Jika REJECTED: Mempertahankan temuan dan mencatat penolakan di Audit Trail.
    """
    dec_upper = decision.upper().strip()
    if dec_upper not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Keputusan harus berupa 'APPROVED' atau 'REJECTED'.")

    ticket = db.query(FindingTicket).join(MasterBank).filter(FindingTicket.Finding_ID == finding_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Tiket Temuan '{finding_id}' tidak ditemukan.")

    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
    stage = period.Active_Threshold_Stage if period else "EARLY"

    ticket.BI_Decision_Status = dec_upper
    ticket.Verified_By = verified_by or "Petugas BI DPPK"
    ticket.Updated_At = datetime.utcnow()

    # Ambil matriks skor bank yang bersangkutan
    matrix_entry = db.query(BankScoreMatrix).filter(
        BankScoreMatrix.Bank_ID == ticket.Bank_ID
    ).order_by(BankScoreMatrix.id.desc()).first()

    param_code = ticket.Parameter_Code.strip().upper()
    param_key = param_code.lower()

    if dec_upper == "APPROVED":
        # 1. Ekstrak nilai angka klaim jika ada (misal '85.00%' -> 85.0)
        claimed_val = None
        if ticket.Nilai_Klaim_Bank:
            match = re.search(r"(\d+(?:\.\d+)?)", ticket.Nilai_Klaim_Bank)
            if match:
                claimed_val = float(match.group(1))

        # Jika tidak ditemukan angka klaim, set nilai di atas ambang batas stage aktif
        threshold_val = THRESHOLDS.get(stage, THRESHOLDS["EARLY"]).get(param_code, 80.0)
        final_val = claimed_val if claimed_val and claimed_val >= threshold_val else (threshold_val + 2.0)

        # 2. Update kolom di BankScoreMatrix
        if hasattr(matrix_entry, f"{param_key}_raw"):
            setattr(matrix_entry, f"{param_key}_raw", final_val)
        if hasattr(matrix_entry, f"{param_key}_passed"):
            setattr(matrix_entry, f"{param_key}_passed", True)
        if hasattr(matrix_entry, f"{param_key}_score"):
            setattr(matrix_entry, f"{param_key}_score", WEIGHTS.get(param_code, 0.0))

        # 3. Hitung ulang total PUVA, OM, dan komposit
        puva_codes = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]
        new_puva = 0.0
        for code in puva_codes:
            ck = code.lower()
            new_puva += getattr(matrix_entry, f"{ck}_score", 0.0)

        om_total = getattr(matrix_entry, "total_om_score", 40.0) or 40.0
        composite = round(new_puva + om_total, 2)

        if composite >= 100.0:
            compliance = "MEMENUHI"
        elif composite >= 90.0:
            compliance = "PEMBINAAN_DSMM"
        else:
            compliance = "SANKSI_TEGURAN"

        matrix_entry.total_puva_score = round(new_puva, 2)
        matrix_entry.composite_score = composite
        matrix_entry.compliance_status = compliance
        matrix_entry.updated_at = datetime.utcnow()

        audit_detail = (
            f"Petugas {ticket.Verified_By} MENYETUJUI sanggahan {ticket.Finding_ID} ({ticket.bank.Masked_Alias}). "
            f"Parameter {param_code} disesuaikan menjadi {final_val}%. Skor PUVA baru: {matrix_entry.total_puva_score}% (Status: {compliance})."
        )
    else:
        audit_detail = (
            f"Petugas {ticket.Verified_By} MENOLAK sanggahan {ticket.Finding_ID} ({ticket.bank.Masked_Alias}). "
            f"Status temuan dipertahankan. Catatan: '{notes or 'Tidak memenuhi ketentuan PADG No. 23/2024'}."
        )

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
                "composite_score": matrix_entry.composite_score,
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

    matrix_entry = db.query(BankScoreMatrix).filter(BankScoreMatrix.Bank_ID == bank.Bank_ID).first()

    # Kumpulkan parameter yang gugur
    failed_params = []
    if matrix_entry:
        for p in ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]:
            if not getattr(matrix_entry, f"{p.lower()}_passed", True):
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

    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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
    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
    if not period:
        raise HTTPException(status_code=404, detail="Periode evaluasi belum diinisialisasi.")

    matrices = db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id).all()
    full_pass = sum(1 for m in matrices if m.compliance_status == "MEMENUHI")
    pembinaan = sum(1 for m in matrices if m.compliance_status == "PEMBINAAN_DSMM")
    sanksi = sum(1 for m in matrices if m.compliance_status == "SANKSI_TEGURAN")

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
            "pembinaan": pembinaan,
            "sanksi": sanksi,
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
    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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
                "composite_score": m.composite_score,
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
    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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

    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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
    period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
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
