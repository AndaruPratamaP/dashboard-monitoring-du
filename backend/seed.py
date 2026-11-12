"""
Database Auto-Seeder untuk PUVA EVAL-CORE
Membaca 6 file Excel dari folder sample_datasets_puva_2026Q2 dan mengisi tabel SQLite.
"""

import os
import json
import logging
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base, ensure_schema
from models import MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
from services.rule_engine import compute_matrix_scores, calculate_puva_raw_metrics
from services.entity_resolution import EntityResolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")


def get_dataset_folder():
    """Cari folder sample_datasets_puva_2026Q2 di backend atau root workspace."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "sample_datasets_puva_2026Q2"),
        os.path.join(base_dir, "..", "sample_datasets_puva_2026Q2"),
        os.path.join(os.getcwd(), "sample_datasets_puva_2026Q2"),
    ]
    for path in candidates:
        if os.path.exists(path) and os.path.isdir(path):
            return os.path.abspath(path)
    raise FileNotFoundError("Folder 'sample_datasets_puva_2026Q2' tidak ditemukan di kandidat direktori.")


MASTER_BANK_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "master_bank_du.json")


def sync_master_banks(db: Session) -> int:
    """
    Upsert master 21 Bank DU dari backend/data/master_bank_du.json (idempoten).
    Dipanggil setiap startup agar database lama ikut mendapat sandi BI, kode BBG, dan alias.
    """
    with open(MASTER_BANK_JSON, encoding="utf-8") as f:
        banks = json.load(f)["banks"]
    for b in banks:
        bank = db.query(MasterBank).filter(MasterBank.Bank_ID == b["bank_id"]).first()
        if not bank:
            bank = MasterBank(Bank_ID=b["bank_id"])
            db.add(bank)
        bank.Masked_Alias = b["masked_alias"]
        bank.Nama_Resmi_Bank = b["nama_resmi"]
        bank.Nama_Singkat = b["nama_singkat"]
        bank.Kelompok_KBMI = b["kelompok_kbmi"]
        bank.Sandi_BI = b["sandi_bi"]
        bank.Kode_BBG = b["kode_bbg"]
        bank.No_Urut_Konfirmasi = b["no_urut_konfirmasi"]
        bank.Aliases_JSON = json.dumps(b.get("aliases", []))
        # Kolom lama (dipakai parser sample dataset) tetap diisi
        old_codes = b.get("aliases", [])
        bank.Kode_Bloomberg = next((a for a in old_codes if a.endswith(" IJ")), b["kode_bbg"])
        bank.Kode_SPPA_Antasena = old_codes[1] if len(old_codes) > 1 else b["nama_singkat"].upper()
    db.commit()
    return len(banks)


def seed_database(db: Session = None, force_reseed: bool = False):
    """
    Eksekusi seeding dataset realistis PUVA Triwulan II 2026.
    """
    should_close_db = False
    if db is None:
        Base.metadata.create_all(bind=engine)
        ensure_schema()
        db = SessionLocal()
        should_close_db = True

    try:
        sync_master_banks(db)

        # Cek apakah sudah ada data jika tidak force_reseed
        # Master bank selalu disinkronkan; seeding data sample hanya bila belum ada periode evaluasi
        if db.query(EvaluationPeriod).count() > 0 and not force_reseed:
            logger.info("Database sudah memiliki periode evaluasi. Lewati seeding data sample.")
            return

        logger.info("Memulai proses seeding database PUVA EVAL-CORE...")
        dataset_dir = get_dataset_folder()
        logger.info(f"Menggunakan dataset dari: {dataset_dir}")

        # Jika force reseed, bersihkan data lama
        if force_reseed:
            db.query(FindingTicket).delete()
            db.query(BankScoreMatrix).delete()
            db.query(EvaluationPeriod).delete()
            db.query(MasterBank).delete()
            db.commit()
            sync_master_banks(db)

        # ==============================================================================
        # 1. FILE 00: MASTER REFERENSI & EVALUATION PERIOD
        # ==============================================================================
        f00_path = os.path.join(dataset_dir, "00_Master_Referensi_PUVA.xlsx")
        df_banks = pd.read_excel(f00_path, sheet_name="Master_21_Bank_DU")
        df_kalender = pd.read_excel(f00_path, sheet_name="Kalender_Kerja_Q2")
        total_working_days = len(df_kalender)

        # Buat Periode Evaluasi Q2 2026
        period = db.query(EvaluationPeriod).filter(EvaluationPeriod.Triwulan == "2026-Q2").first()
        if not period:
            period = EvaluationPeriod(
                Tahun=2026,
                Triwulan="2026-Q2",
                Active_Threshold_Stage="EARLY",
                Is_Snapshot_Locked=False,
                Locked_At=None,
            )
            db.add(period)
            db.flush()

        # Master 21 Bank sudah disinkronkan dari master_bank_du.json (sync_master_banks)
        db.flush()

        # ==============================================================================
        # 2. BACA FILE RAW KUOTASI, SURVEY, HARTIS, & ANTASENA
        # ==============================================================================
        f01_path = os.path.join(dataset_dir, "01_Raw_Kuotasi_Bloomberg_SPPA.xlsx")
        df_quotes = pd.read_excel(f01_path)

        f02_path = os.path.join(dataset_dir, "02_Raw_Survey_Counterparty_Line.xlsx")
        df_survey = pd.read_excel(f02_path)

        f03_path = os.path.join(dataset_dir, "03_Raw_HARTIS_Transaksi.xlsx")
        df_hartis_p = pd.read_excel(f03_path, sheet_name="Lelang_Perdana_SRBI")
        df_hartis_s = pd.read_excel(f03_path, sheet_name="Transaksi_Pasar_Sekunder")

        f04_path = os.path.join(dataset_dir, "04_Raw_DS_Antasena_Matchmaking_OIS.xlsx")
        df_antasena = pd.read_excel(f04_path)

        # ==============================================================================
        # 3. KALKULASI PARAMETER PUVA UNTUK 21 BANK (memakai Rule Engine yang sama dengan ETL)
        # ==============================================================================
        resolver = EntityResolver(db)
        raw_metrics, failed_tx_details, breakdown_stats = calculate_puva_raw_metrics(
            df_quotes=df_quotes,
            df_survey=df_survey,
            df_hartis_p=df_hartis_p,
            df_hartis_s=df_hartis_s,
            df_antasena=df_antasena,
            resolver=resolver,
            total_working_days=total_working_days,
        )

        for b_id, bank_raw in raw_metrics.items():
            raw_dict = dict(bank_raw)
            scores = compute_matrix_scores(raw_dict, stage="EARLY")

            matrix_entry = db.query(BankScoreMatrix).filter(
                BankScoreMatrix.period_id == period.id,
                BankScoreMatrix.Bank_ID == b_id
            ).first()
            if not matrix_entry:
                matrix_entry = BankScoreMatrix(period_id=period.id, Bank_ID=b_id)
                db.add(matrix_entry)

            for k, v in scores.items():
                if hasattr(matrix_entry, k):
                    setattr(matrix_entry, k, v)

            matrix_entry.detail_metrics_json = json.dumps(breakdown_stats.get(b_id, {}))
            matrix_entry.updated_at = datetime.utcnow()

        db.flush()

        # ==============================================================================
        # 4. FILE 05: SIMULASI SANGGAHAN & FINDING TICKETS
        # ==============================================================================
        f05_path = os.path.join(dataset_dir, "05_Simulasi_Sanggahan_Bank_DU.xlsx")
        df_disputes = pd.read_excel(f05_path)

        for _, disp in df_disputes.iterrows():
            f_id = disp["Finding_ID"]
            b_id = disp["Bank_ID"]
            param_raw = str(disp["Parameter"]).split("-")[0].strip()  # misal 'B2' dari 'B2 - Kuotasi Harga SRBI'
            
            # Cocokkan rincian transaksi gugur dari hasil kalkulasi di atas
            lookup_key = f"{b_id}-{param_raw}"
            gugur_data = failed_tx_details.get(lookup_key, [])
            gugur_json = json.dumps(gugur_data) if gugur_data else None

            ticket = db.query(FindingTicket).filter(FindingTicket.Finding_ID == f_id).first()
            if not ticket:
                ticket = FindingTicket(
                    Finding_ID=f_id,
                    period_id=period.id,
                    Bank_ID=b_id,
                    Parameter_Code=param_raw,
                    Nilai_Rekap_BI=str(disp["Rekap_Awal_BI"]),
                    Detail_Transaksi_Gugur=gugur_json,
                    Nilai_Klaim_Bank=str(disp["Klaim_Bank"]),
                    Alasan_Sanggahan=str(disp["Alasan_Sanggahan_Bank"]),
                    File_Bukti_Name=str(disp["Nama_File_Bukti"]),
                    AI_Recommendation_Status="RECOMMEND_APPROVE" if "APPROVE" in str(disp["Rekomendasi_AI_Expected"]) else "RECOMMEND_REJECT" if "REJECT" in str(disp["Rekomendasi_AI_Expected"]) else "PARTIAL_REVIEW",
                    AI_Analysis_Text=str(disp["Rekomendasi_AI_Expected"]),
                    BI_Decision_Status="OPEN",
                    Verified_By=None,
                    Updated_At=datetime.utcnow(),
                )
                db.add(ticket)

        # Tambahkan catatan di Audit Trail
        audit = AuditTrail(
            action="INITIAL_SEEDING",
            performed_by="System Auto-Seeder",
            details="Seeding data lengkap 21 Bank Dealer Utama PUVA, Score Matrix Q2 2026, dan 5 Finding Tickets sanggahan berhasil dilakukan.",
        )
        db.add(audit)
        db.commit()

        logger.info("Seeding data berhasil diselesaikan dengan sempurna! 21 Bank, Matrix Skor, dan 5 Finding Tickets siap untuk Live Demo.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error saat menjalankan seeding: {e}", exc_info=True)
        raise e
    finally:
        if should_close_db:
            db.close()


if __name__ == "__main__":
    seed_database(force_reseed=True)
