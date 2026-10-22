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

from database import engine, SessionLocal, Base
from models import MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
from rule_engine import compute_matrix_scores

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


def seed_database(db: Session = None, force_reseed: bool = False):
    """
    Eksekusi seeding dataset realistis PUVA Triwulan II 2026.
    """
    should_close_db = False
    if db is None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        should_close_db = True

    try:
        # Cek apakah sudah ada data jika tidak force_reseed
        existing_banks = db.query(MasterBank).count()
        if existing_banks >= 21 and not force_reseed:
            logger.info("Database sudah memiliki 21 bank DU. Lewati proses seeding.")
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

        # Insert 21 Bank
        bank_map = {}
        for _, row in df_banks.iterrows():
            bank = db.query(MasterBank).filter(MasterBank.Bank_ID == row["Bank_ID"]).first()
            if not bank:
                bank = MasterBank(
                    Bank_ID=row["Bank_ID"],
                    Masked_Alias=row["Masked_Alias"],
                    Nama_Resmi_Bank=row["Nama_Resmi_Bank"],
                    Kelompok_KBMI=row["Kelompok_KBMI"],
                    Kode_Bloomberg=row["Kode_Bloomberg"],
                    Kode_SPPA_Antasena=row["Kode_SPPA_Antasena"],
                )
                db.add(bank)
            bank_map[row["Bank_ID"]] = row
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

        # Siapkan kamus detail transaksi gugur untuk tiket temuan
        failed_tx_details = {}

        # ==============================================================================
        # 3. KALKULASI PARAMETER PUVA UNTUK 21 BANK
        # ==============================================================================
        for _, bank_row in df_banks.iterrows():
            b_id = bank_row["Bank_ID"]
            alias = bank_row["Masked_Alias"]
            nama = bank_row["Nama_Resmi_Bank"]
            b_code = bank_row["Kode_Bloomberg"]
            s_code = bank_row["Kode_SPPA_Antasena"]

            # --- Parameter B1 (Kuotasi Repo - SPPA) ---
            # Tenors: O/N (spread <= 5), 1W (spread <= 20), 1M (spread <= 20)
            q_b1 = df_quotes[(df_quotes["Kode_Partisipan"] == s_code) & (df_quotes["Instrumen"] == "REPO")]
            b1_valid_days = 0
            for day, grp in q_b1.groupby("Tanggal_Kuotasi"):
                valid = True
                for _, r in grp.iterrows():
                    t = r["Tenor_atau_Seri"]
                    sp = r["Spread_Bps"]
                    if t == "O/N" and sp > 5.0:
                        valid = False
                    elif t in ["1W", "1M"] and sp > 20.0:
                        valid = False
                if valid and len(grp) >= 3:
                    b1_valid_days += 1
            b1_raw = round((b1_valid_days / total_working_days) * 100, 2)

            # --- Parameter B2 (Kuotasi SRBI - Bloomberg) ---
            # Seri tradable, spread <= 20 bps
            q_b2 = df_quotes[(df_quotes["Kode_Partisipan"] == b_code) & (df_quotes["Instrumen"] == "SRBI")]
            b2_valid_days = 0
            b2_failed_list = []
            for day, grp in q_b2.groupby("Tanggal_Kuotasi"):
                day_valid = True
                for _, r in grp.iterrows():
                    if r["Spread_Bps"] > 20.0:
                        day_valid = False
                        b2_failed_list.append({
                            "tanggal": str(day),
                            "instrumen": "SRBI",
                            "seri": str(r["Tenor_atau_Seri"]),
                            "bid_rate": float(r["Bid_Rate"]),
                            "ask_rate": float(r["Ask_Rate"]),
                            "spread_bps": float(r["Spread_Bps"]),
                            "alasan": f"Spread {r['Spread_Bps']} bps melanggar batas maksimal 20 bps (PADG No. 23/2024)"
                        })
                if day_valid:
                    b2_valid_days += 1
            b2_raw = round((b2_valid_days / total_working_days) * 100, 2)
            if b2_failed_list:
                failed_tx_details[f"{b_id}-B2"] = b2_failed_list

            # --- Parameter B3 (Kuotasi OIS - Bloomberg) ---
            # Tenors: 1M & 3M, spread <= 20 bps
            q_b3 = df_quotes[(df_quotes["Kode_Partisipan"] == b_code) & (df_quotes["Instrumen"] == "OIS")]
            b3_valid_days = 0
            b3_failed_list = []
            for day, grp in q_b3.groupby("Tanggal_Kuotasi"):
                day_valid = True
                for _, r in grp.iterrows():
                    if r["Spread_Bps"] > 20.0:
                        day_valid = False
                        b3_failed_list.append({
                            "tanggal": str(day),
                            "instrumen": "OIS",
                            "tenor": str(r["Tenor_atau_Seri"]),
                            "bid_rate": float(r["Bid_Rate"]),
                            "ask_rate": float(r["Ask_Rate"]),
                            "spread_bps": float(r["Spread_Bps"]),
                            "alasan": f"Spread tenor {r['Tenor_atau_Seri']} sebesar {r['Spread_Bps']} bps > 20 bps"
                        })
                if day_valid and len(grp) >= 2:
                    b3_valid_days += 1
            b3_raw = round((b3_valid_days / total_working_days) * 100, 2)
            if b3_failed_list:
                failed_tx_details[f"{b_id}-B3"] = b3_failed_list

            # --- Parameter B4 & B5 (Survey Counterparty Line) ---
            surv_match = df_survey[df_survey["Nama_Bank_Pelapor"] == nama]
            if not surv_match.empty:
                s_rec = surv_match.iloc[0]
                r_du = s_rec["Jml_Line_Repo_Bank_DU"]
                r_non = s_rec["Jml_Line_Repo_Bank_Non_DU"]
                ois_du = s_rec["Jml_Line_OIS_Bank_DU"]
            else:
                r_du, r_non, ois_du = 15, 30, 15

            b4_raw = round(min(100.0, ((min(r_du, 10)/10.0 + min(r_non, 10)/10.0)/2.0)*100), 2)
            b5_raw = round(min(100.0, (ois_du/10.0)*100), 2)

            if b4_raw < 50.0:
                failed_tx_details[f"{b_id}-B4"] = [{
                    "parameter": "Counterparty Line Repo",
                    "realisasi_line_du": int(r_du),
                    "target_line_du": 10,
                    "realisasi_line_non_du": int(r_non),
                    "target_line_non_du": 10,
                    "alasan": f"Hanya memiliki {r_du} line DU dan {r_non} line Non-DU (di bawah batas minimal 10 DU & 10 Non-DU)"
                }]

            # --- Parameter B6 (Penjualan SRBI Sekunder >= 30% Win Perdana) ---
            win_series = df_hartis_p[df_hartis_p["Nama_Bank_HARTIS"] == nama]["Total_Volume_Win_SRBI_Miliar_Rp"]
            win_vol = float(win_series.sum()) if not win_series.empty else 1000.0
            target_sales = 0.30 * win_vol

            sec_srbi = df_hartis_s[(df_hartis_s["Nama_Bank_HARTIS"] == nama) & (df_hartis_s["Instrumen"] == "SRBI_SEKUNDER")]
            actual_sales = float(sec_srbi["Volume_Miliar_Rp"].sum()) if not sec_srbi.empty else 0.0

            b6_raw = round(min(100.0, (actual_sales / target_sales) * 100), 2) if target_sales > 0 else 100.0
            if b6_raw < 80.0:
                failed_tx_details[f"{b_id}-B6"] = [{
                    "volume_win_perdana": win_vol,
                    "target_penjualan_sekunder_30pct": target_sales,
                    "realisasi_penjualan_sekunder": actual_sales,
                    "kekurangan_volume": target_sales - actual_sales,
                    "rasio_terhadap_target": f"{b6_raw}%",
                    "alasan": f"Realisasi penjualan Rp {actual_sales:.1f} Miliar (19.5% dari Win) < target 30% (Rp {target_sales:.1f} Miliar)"
                }]

            # --- Parameter B7a (Repo Sekunder: Tenor >= 14 Hari di 60% HK = 36 HK) ---
            sec_repo_valid = df_hartis_s[
                (df_hartis_s["Nama_Bank_HARTIS"] == nama) &
                (df_hartis_s["Instrumen"] == "REPO_SEKUNDER") &
                (df_hartis_s["Tenor_Hari"] >= 14)
            ]
            valid_repo_days = sec_repo_valid["Tanggal_Transaksi"].nunique()
            b7a_raw = round(min(100.0, (valid_repo_days / 36.0) * 100), 2)

            # Deteksi transaksi repo yang gugur (tenor < 14 hari)
            sec_repo_invalid = df_hartis_s[
                (df_hartis_s["Nama_Bank_HARTIS"] == nama) &
                (df_hartis_s["Instrumen"] == "REPO_SEKUNDER") &
                (df_hartis_s["Tenor_Hari"] < 14)
            ]
            if not sec_repo_invalid.empty:
                b7a_failed_list = []
                for _, r_inv in sec_repo_invalid.iterrows():
                    b7a_failed_list.append({
                        "deal_id": str(r_inv["Deal_ID"]),
                        "tanggal": str(r_inv["Tanggal_Transaksi"]),
                        "tenor_hari": int(r_inv["Tenor_Hari"]),
                        "volume_miliar_rp": float(r_inv["Volume_Miliar_Rp"]),
                        "alasan": f"Tenor {int(r_inv['Tenor_Hari'])} hari di bawah batas minimal 14 hari (2 minggu) sesuai PADG No. 23/2024"
                    })
                failed_tx_details[f"{b_id}-B7a"] = b7a_failed_list

            # --- Parameter B7b (SRBI Sekunder: Sisa Tenor 3 Bulan di 60% HK = 36 HK) ---
            sec_srbi_b7 = df_hartis_s[
                (df_hartis_s["Nama_Bank_HARTIS"] == nama) &
                (df_hartis_s["Instrumen"] == "SRBI_SEKUNDER") &
                (df_hartis_s["Sisa_Jangka_Waktu_Bulan"] >= 3.0)
            ]
            valid_srbi_days = sec_srbi_b7["Tanggal_Transaksi"].nunique()
            b7b_raw = round(min(100.0, (valid_srbi_days / 36.0) * 100), 2)

            # --- Parameter B8 (Antasena Matchmaking OIS: 12 Sesi) ---
            ant_valid = df_antasena[
                (df_antasena["Kode_Bank_Antasena"] == s_code) &
                (df_antasena["Status_Partisipasi"] == "HADIR & KUOTASI AKTIF")
            ]
            b8_raw = round(min(100.0, (len(ant_valid) / 12.0) * 100), 2)

            # Slot Operasi Moneter (OM) Default 100% untuk Live Demo
            om_dict = {"OM1": 100.0, "OM2": 100.0, "OM3": 100.0}

            raw_dict = {
                "B1": b1_raw, "B2": b2_raw, "B3": b3_raw,
                "B4": b4_raw, "B5": b5_raw,
                "B6": b6_raw, "B7a": b7a_raw, "B7b": b7b_raw, "B8": b8_raw,
                **om_dict
            }

            # Hitung skor berdasarkan Rule Engine untuk tahap "EARLY"
            scores = compute_matrix_scores(raw_dict, stage="EARLY")

            # JSON detail pembentuk nilai untuk Slide-over Drawer UI
            metrics_breakdown = {
                "B1": {"valid_days": b1_valid_days, "total_days": total_working_days, "rate": b1_raw},
                "B2": {"valid_days": b2_valid_days, "total_days": total_working_days, "rate": b2_raw},
                "B3": {"valid_days": b3_valid_days, "total_days": total_working_days, "rate": b3_raw},
                "B4": {"line_du": int(r_du), "line_non_du": int(r_non), "target_du": 10, "target_non_du": 10, "rate": b4_raw},
                "B5": {"line_du": int(ois_du), "target_du": 10, "rate": b5_raw},
                "B6": {"win_perdana": win_vol, "target_sales": target_sales, "actual_sales": actual_sales, "rate": b6_raw},
                "B7a": {"valid_days": valid_repo_days, "target_days": 36, "rate": b7a_raw},
                "B7b": {"valid_days": valid_srbi_days, "target_days": 36, "rate": b7b_raw},
                "B8": {"valid_sessions": len(ant_valid), "total_sessions": 12, "rate": b8_raw},
            }

            # Simpan atau update ke BankScoreMatrix
            matrix_entry = db.query(BankScoreMatrix).filter(
                BankScoreMatrix.period_id == period.id,
                BankScoreMatrix.Bank_ID == b_id
            ).first()

            if not matrix_entry:
                matrix_entry = BankScoreMatrix(
                    period_id=period.id,
                    Bank_ID=b_id,
                )
                db.add(matrix_entry)

            # Assign atribut
            for k, v in scores.items():
                if hasattr(matrix_entry, k):
                    setattr(matrix_entry, k, v)

            matrix_entry.detail_metrics_json = json.dumps(metrics_breakdown)
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
