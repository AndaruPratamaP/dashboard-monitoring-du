"""
Rule Engine Evaluasi Dealer Utama PUVA
Berdasarkan PADG No. 23 Tahun 2024 & PBI No. 6 Tahun 2024
Departemen Pengembangan Pasar Keuangan (DPPK) Bank Indonesia
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from sqlalchemy.orm import Session

from models import MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
from services.entity_resolution import EntityResolver

logger = logging.getLogger("rule_engine")

# 1. AMBANG BATAS (THRESHOLDS) BERDASARKAN TAHAP
THRESHOLDS = {
    "EARLY": {
        "B1": 80.0, "B2": 80.0, "B3": 80.0,
        "B4": 50.0, "B5": 50.0,
        "B6": 80.0, "B7a": 80.0, "B7b": 80.0, "B8": 80.0,
        "OM1": 70.0, "OM2": 85.0, "OM3": 60.0,
    },
    "INTERMEDIATE": {
        "B1": 85.0, "B2": 85.0, "B3": 85.0,
        "B4": 70.0, "B5": 70.0,
        "B6": 85.0, "B7a": 85.0, "B7b": 85.0, "B8": 85.0,
        "OM1": 80.0, "OM2": 90.0, "OM3": 60.0,
    },
    "END_STATE": {
        "B1": 90.0, "B2": 90.0, "B3": 90.0,
        "B4": 80.0, "B5": 80.0,
        "B6": 90.0, "B7a": 90.0, "B7b": 90.0, "B8": 90.0,
        "OM1": 90.0, "OM2": 95.0, "OM3": 60.0,
    },
}

# 2. BOBOT PENILAIAN INDIKATOR
WEIGHTS = {
    "B1": 2.5,   # Kuotasi Harga Repo
    "B2": 2.5,   # Kuotasi Harga SRBI
    "B3": 2.5,   # Kuotasi Harga OIS
    "B4": 7.5,   # Counterparty Line Repo
    "B5": 2.5,   # Counterparty Line OIS
    "B6": 7.5,   # Penjualan SRBI Pasar Sekunder
    "B7a": 20.0, # Transaksi Repo Pasar Sekunder
    "B7b": 5.0,  # Transaksi SRBI Pasar Sekunder
    "B8": 10.0,  # Matchmaking OIS
    "OM1": 15.0, # Penawaran Lelang OPT
    "OM2": 20.0, # Volume Win SRBI
    "OM3": 5.0,  # Penawaran Lelang BI-FRN
}

PARAMETER_NAMES = {
    "B1": "Kuotasi Harga Repo",
    "B2": "Kuotasi Harga SRBI",
    "B3": "Kuotasi Harga OIS",
    "B4": "Counterparty Line Repo",
    "B5": "Counterparty Line OIS",
    "B6": "Penjualan SRBI Pasar Sekunder",
    "B7a": "Transaksi Repo Pasar Sekunder",
    "B7b": "Transaksi SRBI Pasar Sekunder",
    "B8": "Matchmaking OIS",
    "OM1": "Penawaran Lelang OPT",
    "OM2": "Volume Win SRBI",
    "OM3": "Penawaran Lelang BI-FRN",
}

PARAMETER_DETAILS = {
    "B1": "Setiap hari kerja; spread maks. 5 bps (O/N) & maks. 20 bps (1W, 1M)",
    "B2": "Setiap hari kerja; seri SRBI tradable; spread maks. 20 bps",
    "B3": "Setiap hari kerja; tenor 1M & 3M; spread maks. 20 bps",
    "B4": "Minimal 10 bank DU dan 10 bank non-DU pada akhir periode",
    "B5": "Minimal 10 bank DU pada akhir periode",
    "B6": "Minimal 30% dari volume win pada lelang pasar perdana (status SETTLED)",
    "B7a": "Tenor minimal 2 minggu (>=14 hari), minimal 60% hari kerja (36 hari)",
    "B7b": "Sisa jangka waktu minimal 3 bulan, minimal 60% hari kerja (36 hari)",
    "B8": "Tenor 1M dan 3M pada setiap sesi matchmaking OIS (6 periode)",
    "OM1": "Penawaran pada setiap hari lelang OPT",
    "OM2": "Volume win SRBI (KBMI 4 min. 3%, KBMI lain min. 1%)",
    "OM3": "Penawaran pada setiap hari lelang BI-FRN",
}


def calculate_puva_raw_metrics(
    df_quotes: pd.DataFrame,
    df_survey: pd.DataFrame,
    df_hartis_p: pd.DataFrame,
    df_hartis_s: pd.DataFrame,
    df_antasena: pd.DataFrame,
    resolver: EntityResolver,
    total_working_days: int = 60,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    """
    Kalkulasi 9 parameter mentah PUVA (B1 - B8) untuk 21 Bank DU.
    Mengembalikan:
    1. raw_metrics: {Bank_ID: {B1: float, B2: float, ..., B8: float}}
    2. failed_transactions: {f"{Bank_ID}-{Param}": [detail transaksi/kuotasi yang melanggar batas aturan]}
    3. breakdown_stats: {Bank_ID: {B1: {...}, B2: {...}, ...}} untuk slide-over drawer UI
    """
    raw_metrics: Dict[str, Dict[str, float]] = {}
    failed_transactions: Dict[str, List[Dict[str, Any]]] = {}
    breakdown_stats: Dict[str, Dict[str, Any]] = {}

    target_working_days_sec = round(0.60 * total_working_days)  # 36 hari kerja

    for bank in resolver.banks:
        b_id = bank.Bank_ID
        alias = bank.Masked_Alias
        b_code = bank.Kode_Bloomberg
        s_code = bank.Kode_SPPA_Antasena
        nama = bank.Nama_Resmi_Bank

        # ----------------------------------------------------------------------
        # B1: Kuotasi REPO (SPPA) - O/N <= 5 bps, 1W & 1M <= 20 bps
        # ----------------------------------------------------------------------
        q_b1 = df_quotes[
            (df_quotes["Instrumen"] == "REPO") &
            (df_quotes["Kode_Partisipan"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        b1_valid_days = 0
        b1_failed_list = []
        for day, grp in q_b1.groupby("Tanggal_Kuotasi"):
            day_valid = True
            for _, r in grp.iterrows():
                t = str(r["Tenor_atau_Seri"]).strip()
                sp = float(r["Spread_Bps"])
                if t == "O/N" and sp > 5.0:
                    day_valid = False
                    b1_failed_list.append({
                        "tanggal": str(day), "platform": "SPPA", "tenor": t,
                        "spread_bps": sp, "max_allowed_bps": 5.0,
                        "alasan": f"Spread tenor O/N ({sp} bps) melebihi batas maksimal 5 bps"
                    })
                elif t in ["1W", "1M"] and sp > 20.0:
                    day_valid = False
                    b1_failed_list.append({
                        "tanggal": str(day), "platform": "SPPA", "tenor": t,
                        "spread_bps": sp, "max_allowed_bps": 20.0,
                        "alasan": f"Spread tenor {t} ({sp} bps) melebihi batas maksimal 20 bps"
                    })
            if day_valid and len(grp) >= 3:
                b1_valid_days += 1
        b1_raw = round((b1_valid_days / total_working_days) * 100.0, 2)
        if b1_failed_list:
            failed_transactions[f"{b_id}-B1"] = b1_failed_list

        # ----------------------------------------------------------------------
        # B2: Kuotasi SRBI (Bloomberg) - Seri tradable, spread <= 20 bps
        # (Skenario: Bank A / BRI gagal di 14 hari kerja -> 46/60 = 76.67%)
        # ----------------------------------------------------------------------
        q_b2 = df_quotes[
            (df_quotes["Instrumen"] == "SRBI") &
            (df_quotes["Kode_Partisipan"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        b2_valid_days = 0
        b2_failed_list = []
        for day, grp in q_b2.groupby("Tanggal_Kuotasi"):
            day_valid = True
            for _, r in grp.iterrows():
                sp = float(r["Spread_Bps"])
                if sp > 20.0:
                    day_valid = False
                    b2_failed_list.append({
                        "tanggal": str(day), "platform": "Bloomberg", "seri": str(r["Tenor_atau_Seri"]),
                        "bid_rate": float(r["Bid_Rate"]), "ask_rate": float(r["Ask_Rate"]),
                        "spread_bps": sp, "max_allowed_bps": 20.0,
                        "alasan": f"Spread {sp} bps melebihi batas maksimum 20 bps (PADG No. 23/2024)"
                    })
            if day_valid and len(grp) >= 1:
                b2_valid_days += 1
        b2_raw = round((b2_valid_days / total_working_days) * 100.0, 2)
        if b2_failed_list:
            failed_transactions[f"{b_id}-B2"] = b2_failed_list

        # ----------------------------------------------------------------------
        # B3: Kuotasi OIS (Bloomberg) - Tenor 1M & 3M, spread <= 20 bps
        # (Skenario: Bank B / Mandiri hanya 13 hari valid -> 13/60 = 21.67%)
        # ----------------------------------------------------------------------
        q_b3 = df_quotes[
            (df_quotes["Instrumen"] == "OIS") &
            (df_quotes["Kode_Partisipan"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        b3_valid_days = 0
        b3_failed_list = []
        for day, grp in q_b3.groupby("Tanggal_Kuotasi"):
            day_valid = True
            for _, r in grp.iterrows():
                t = str(r["Tenor_atau_Seri"]).strip()
                sp = float(r["Spread_Bps"])
                if sp > 20.0:
                    day_valid = False
                    b3_failed_list.append({
                        "tanggal": str(day), "platform": "Bloomberg", "tenor": t,
                        "bid_rate": float(r["Bid_Rate"]), "ask_rate": float(r["Ask_Rate"]),
                        "spread_bps": sp, "max_allowed_bps": 20.0,
                        "alasan": f"Spread tenor {t} sebesar {sp} bps melebihi batas maksimal 20 bps"
                    })
            if day_valid and len(grp) >= 2:
                b3_valid_days += 1
        b3_raw = round((b3_valid_days / total_working_days) * 100.0, 2)
        if b3_failed_list:
            failed_transactions[f"{b_id}-B3"] = b3_failed_list

        # ----------------------------------------------------------------------
        # B4 & B5: Survey Counterparty Line
        # B4: min 10 DU & 10 Non-DU -> Rasio = (min(DU/10, 1)*50% + min(NonDU/10, 1)*50%)
        # (Skenario: Bank N punya 5 DU & 4 Non-DU -> 25% + 20% = 45.00%)
        # B5: min 10 DU -> Rasio = min(DU/10, 1) * 100%
        # ----------------------------------------------------------------------
        surv_match = df_survey[df_survey["Nama_Bank_Pelapor"].apply(lambda x: resolver.resolve(x) == bank)]
        if not surv_match.empty:
            s_row = surv_match.iloc[0]
            r_du = float(s_row["Jml_Line_Repo_Bank_DU"])
            r_non = float(s_row["Jml_Line_Repo_Bank_Non_DU"])
            ois_du = float(s_row["Jml_Line_OIS_Bank_DU"])
        else:
            r_du, r_non, ois_du = 15.0, 35.0, 15.0

        b4_raw = round((min(r_du / 10.0, 1.0) * 50.0 + min(r_non / 10.0, 1.0) * 50.0), 2)
        b5_raw = round(min(100.0, (ois_du / 10.0) * 100.0), 2)

        if b4_raw < 50.0:
            failed_transactions[f"{b_id}-B4"] = [{
                "parameter": "Counterparty Line Repo",
                "realisasi_line_du": int(r_du), "target_line_du": 10,
                "realisasi_line_non_du": int(r_non), "target_line_non_du": 10,
                "alasan": f"Hanya memiliki {int(r_du)} line DU dan {int(r_non)} line Non-DU (di bawah target minimal 10 DU & 10 Non-DU)"
            }]
        if b5_raw < 50.0:
            failed_transactions[f"{b_id}-B5"] = [{
                "parameter": "Counterparty Line OIS",
                "realisasi_line_du": int(ois_du), "target_line_du": 10,
                "alasan": f"Hanya memiliki {int(ois_du)} line OIS Bank DU (di bawah target minimal 10 Bank DU)"
            }]

        # ----------------------------------------------------------------------
        # B6: Penjualan SRBI Sekunder >= 30% dari Volume Win Perdana
        # Rasio Pemenuhan = min((Persen_Jual / 30%), 100%)
        # (Skenario: Bank D menjual 195 M dari 1000 M win = 19.5% -> rasio 65.00%)
        # ----------------------------------------------------------------------
        win_rows = df_hartis_p[df_hartis_p["Nama_Bank_HARTIS"].apply(lambda x: resolver.resolve(x) == bank)]
        win_vol = float(win_rows["Total_Volume_Win_SRBI_Miliar_Rp"].sum()) if not win_rows.empty else 1000.0
        target_sales = 0.30 * win_vol

        sec_srbi = df_hartis_s[
            (df_hartis_s["Instrumen"] == "SRBI_SEKUNDER") &
            (df_hartis_s["Status_Settlement"] == "SETTLED") &
            (df_hartis_s["Nama_Bank_HARTIS"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        actual_sales = float(sec_srbi["Volume_Miliar_Rp"].sum()) if not sec_srbi.empty else 0.0
        pct_sales_of_win = (actual_sales / win_vol * 100.0) if win_vol > 0 else 0.0

        b6_raw = round(min(100.0, (pct_sales_of_win / 30.0) * 100.0), 2) if target_sales > 0 else 100.0
        if b6_raw < 80.0:
            failed_transactions[f"{b_id}-B6"] = [{
                "volume_win_perdana": win_vol,
                "target_kewajiban_30pct": target_sales,
                "realisasi_penjualan_sekunder": actual_sales,
                "persentase_terhadap_win": f"{pct_sales_of_win:.2f}%",
                "kekurangan_volume": round(target_sales - actual_sales, 2),
                "rasio_pemenuhan": f"{b6_raw:.2f}%",
                "alasan": f"Penjualan SRBI sekunder Rp {actual_sales:.1f} M ({pct_sales_of_win:.2f}% dari win) di bawah kewajiban minimal 30% (Rp {target_sales:.1f} M)"
            }]

        # ----------------------------------------------------------------------
        # B7a: Transaksi Repo Sekunder Tenor >= 14 Hari di 60% HK (36 hari)
        # (Skenario: Bank R memiliki 38 hari, namun 12 hari tenornya 7 hari -> 26/36 = 72.22%)
        # ----------------------------------------------------------------------
        sec_repo_all = df_hartis_s[
            (df_hartis_s["Instrumen"] == "REPO_SEKUNDER") &
            (df_hartis_s["Status_Settlement"] == "SETTLED") &
            (df_hartis_s["Nama_Bank_HARTIS"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        sec_repo_valid = sec_repo_all[sec_repo_all["Tenor_Hari"] >= 14]
        valid_repo_days = sec_repo_valid["Tanggal_Transaksi"].nunique()
        b7a_raw = round(min(100.0, (valid_repo_days / target_working_days_sec) * 100.0), 2)

        sec_repo_invalid = sec_repo_all[sec_repo_all["Tenor_Hari"] < 14]
        if not sec_repo_invalid.empty:
            b7a_failed_list = []
            for _, r_inv in sec_repo_invalid.iterrows():
                b7a_failed_list.append({
                    "deal_id": str(r_inv["Deal_ID"]),
                    "tanggal": str(r_inv["Tanggal_Transaksi"]),
                    "instrumen": "REPO_SEKUNDER",
                    "peran": str(r_inv["Peran"]),
                    "tenor_hari": int(r_inv["Tenor_Hari"]),
                    "min_allowed_tenor": 14,
                    "volume_miliar_rp": float(r_inv["Volume_Miliar_Rp"]),
                    "alasan": f"Tenor transaksi {int(r_inv['Tenor_Hari'])} hari di bawah batas minimal 14 hari (2 minggu) sesuai PADG No. 23/2024"
                })
            failed_transactions[f"{b_id}-B7a"] = b7a_failed_list

        # ----------------------------------------------------------------------
        # B7b: Transaksi SRBI Sekunder Sisa Tenor >= 3 Bulan di 60% HK (36 hari)
        # ----------------------------------------------------------------------
        sec_srbi_all = df_hartis_s[
            (df_hartis_s["Instrumen"] == "SRBI_SEKUNDER") &
            (df_hartis_s["Status_Settlement"] == "SETTLED") &
            (df_hartis_s["Nama_Bank_HARTIS"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        sec_srbi_valid = sec_srbi_all[sec_srbi_all["Sisa_Jangka_Waktu_Bulan"] >= 3.0]
        valid_srbi_days = sec_srbi_valid["Tanggal_Transaksi"].nunique()
        b7b_raw = round(min(100.0, (valid_srbi_days / target_working_days_sec) * 100.0), 2)

        # ----------------------------------------------------------------------
        # B8: Matchmaking OIS (6 Periode x 2 Tenor = 12 Sesi)
        # ----------------------------------------------------------------------
        ant_valid = df_antasena[
            (df_antasena["Status_Partisipasi"] == "HADIR & KUOTASI AKTIF") &
            (df_antasena["Kode_Bank_Antasena"].apply(lambda x: resolver.resolve(x) == bank))
        ]
        b8_raw = round(min(100.0, (len(ant_valid) / 12.0) * 100.0), 2)

        raw_metrics[b_id] = {
            "B1": b1_raw, "B2": b2_raw, "B3": b3_raw,
            "B4": b4_raw, "B5": b5_raw,
            "B6": b6_raw, "B7a": b7a_raw, "B7b": b7b_raw, "B8": b8_raw,
            "OM1": 100.0, "OM2": 100.0, "OM3": 100.0,  # Default slot OM untuk Live Demo
        }

        breakdown_stats[b_id] = {
            "B1": {"valid_days": b1_valid_days, "total_days": total_working_days, "rate": b1_raw},
            "B2": {"valid_days": b2_valid_days, "total_days": total_working_days, "rate": b2_raw},
            "B3": {"valid_days": b3_valid_days, "total_days": total_working_days, "rate": b3_raw},
            "B4": {"line_du": int(r_du), "line_non_du": int(r_non), "target_du": 10, "target_non_du": 10, "rate": b4_raw},
            "B5": {"line_du": int(ois_du), "target_du": 10, "rate": b5_raw},
            "B6": {"win_perdana": win_vol, "target_sales": target_sales, "actual_sales": actual_sales, "rate": b6_raw},
            "B7a": {"valid_days": valid_repo_days, "target_days": target_working_days_sec, "rate": b7a_raw},
            "B7b": {"valid_days": valid_srbi_days, "target_days": target_working_days_sec, "rate": b7b_raw},
            "B8": {"valid_sessions": len(ant_valid), "total_sessions": 12, "rate": b8_raw},
        }

    return raw_metrics, failed_transactions, breakdown_stats


def evaluate_parameter(param_code: str, raw_value: float, stage: str = "EARLY") -> Dict[str, Any]:
    """
    Evaluasi satu indikator terhadap threshold aktif.
    Jika lolos (raw >= threshold) -> skor = bobot.
    Jika gagal -> skor = 0.
    """
    st = stage.upper() if stage.upper() in THRESHOLDS else "EARLY"
    threshold = THRESHOLDS[st].get(param_code, 80.0)
    weight = WEIGHTS.get(param_code, 0.0)

    passed = round(raw_value, 2) >= round(threshold, 2)
    score = weight if passed else 0.0

    return {
        "parameter_code": param_code,
        "name": PARAMETER_NAMES.get(param_code, param_code),
        "raw_value": round(raw_value, 2),
        "threshold": threshold,
        "weight": weight,
        "passed": passed,
        "score": score,
    }


def compute_matrix_scores(raw_dict: dict, stage: str = "EARLY") -> Dict[str, Any]:
    """
    Hitung nilai bobot, total PUVA, total OM, dan status kepatuhan komposit.
    """
    results: Dict[str, Any] = {}
    total_puva = 0.0
    total_om = 0.0

    puva_codes = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]
    om_codes = ["OM1", "OM2", "OM3"]

    for code in puva_codes:
        raw_val = raw_dict.get(code, 0.0)
        res = evaluate_parameter(code, raw_val, stage)
        key = code.lower().replace("b7a", "b7a").replace("b7b", "b7b")
        results[f"{key}_raw"] = res["raw_value"]
        results[f"{key}_passed"] = res["passed"]
        results[f"{key}_score"] = res["score"]
        total_puva += res["score"]

    for code in om_codes:
        raw_val = raw_dict.get(code, 100.0)
        res = evaluate_parameter(code, raw_val, stage)
        key = code.lower()
        results[f"{key}_raw"] = res["raw_value"]
        results[f"{key}_passed"] = res["passed"]
        results[f"{key}_score"] = res["score"]
        total_om += res["score"]

    total_puva = round(total_puva, 2)
    total_om = round(total_om, 2)
    composite = round(total_puva + total_om, 2)

    if composite >= 100.0:
        compliance = "MEMENUHI"
    elif composite >= 90.0:
        compliance = "PEMBINAAN_DSMM"
    else:
        compliance = "SANKSI_TEGURAN"

    results["total_puva_score"] = total_puva
    results["total_om_score"] = total_om
    results["composite_score"] = composite
    results["compliance_status"] = compliance

    return results


def evaluate_and_sync_database(
    db: Session,
    stage: str = "EARLY",
    period_id: Optional[int] = None,
    raw_metrics: Optional[Dict[str, Dict[str, float]]] = None,
    failed_transactions: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    breakdown_stats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Evaluasi threshold dinamis dan simpan hasilnya ke tabel SQLite:
    - Update EvaluationPeriod.Active_Threshold_Stage
    - Update BankScoreMatrix untuk 21 Bank DU
    - Buat atau update FindingTicket untuk parameter yang gugur di bawah threshold
    - Catat di AuditTrail
    """
    stage_upper = stage.upper() if stage.upper() in THRESHOLDS else "EARLY"

    # 1. Cari atau buat EvaluationPeriod
    if period_id:
        period = db.query(EvaluationPeriod).filter(EvaluationPeriod.id == period_id).first()
    else:
        period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()

    if not period:
        period = EvaluationPeriod(
            Tahun=2026, Triwulan="2026-Q2",
            Active_Threshold_Stage=stage_upper,
            Is_Snapshot_Locked=False
        )
        db.add(period)
        db.flush()
    else:
        period.Active_Threshold_Stage = stage_upper

    triwulan_str = period.Triwulan.replace("-", "")

    # Ambil data bank master
    banks = db.query(MasterBank).order_by(MasterBank.Bank_ID).all()
    created_findings = 0
    updated_findings = 0
    full_compliance_count = 0
    pembinaan_count = 0
    sanksi_count = 0

    puva_codes = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]

    for b in banks:
        b_id = b.Bank_ID
        matrix_entry = db.query(BankScoreMatrix).filter(
            BankScoreMatrix.period_id == period.id,
            BankScoreMatrix.Bank_ID == b_id
        ).first()

        # Ambil raw metrics
        if raw_metrics and b_id in raw_metrics:
            bank_raw = raw_metrics[b_id]
        elif matrix_entry:
            bank_raw = {
                "B1": matrix_entry.b1_raw, "B2": matrix_entry.b2_raw, "B3": matrix_entry.b3_raw,
                "B4": matrix_entry.b4_raw, "B5": matrix_entry.b5_raw,
                "B6": matrix_entry.b6_raw, "B7a": matrix_entry.b7a_raw, "B7b": matrix_entry.b7b_raw, "B8": matrix_entry.b8_raw,
                "OM1": matrix_entry.om1_raw or 100.0, "OM2": matrix_entry.om2_raw or 100.0, "OM3": matrix_entry.om3_raw or 100.0,
            }
        else:
            bank_raw = {code: 100.0 for code in puva_codes}
            bank_raw.update({"OM1": 100.0, "OM2": 100.0, "OM3": 100.0})

        # Hitung skor berdasarkan threshold aktif
        scores = compute_matrix_scores(bank_raw, stage=stage_upper)

        if not matrix_entry:
            matrix_entry = BankScoreMatrix(period_id=period.id, Bank_ID=b_id)
            db.add(matrix_entry)

        for k, v in scores.items():
            if hasattr(matrix_entry, k):
                setattr(matrix_entry, k, v)

        if breakdown_stats and b_id in breakdown_stats:
            matrix_entry.detail_metrics_json = json.dumps(breakdown_stats[b_id])

        matrix_entry.updated_at = datetime.utcnow()

        # Hitung statistik
        if scores["compliance_status"] == "MEMENUHI":
            full_compliance_count += 1
        elif scores["compliance_status"] == "PEMBINAAN_DSMM":
            pembinaan_count += 1
        else:
            sanksi_count += 1

        # Cek apakah ada parameter PUVA yang gugur terhadap threshold aktif
        for code in puva_codes:
            code_key = code.lower()
            is_passed = scores.get(f"{code_key}_passed", True)
            raw_val = scores.get(f"{code_key}_raw", 100.0)
            threshold_val = THRESHOLDS[stage_upper].get(code, 80.0)

            # Format Finding_ID standar: FND-2026Q2-DU01-B2
            b_short = b_id.replace("-", "")
            finding_id = f"FND-{triwulan_str}-{b_short}-{code.upper()}"

            if not is_passed:
                # Cari detail transaksi gugur
                lookup_key = f"{b_id}-{code}"
                gugur_data = (failed_transactions or {}).get(lookup_key, [])
                gugur_json = json.dumps(gugur_data) if gugur_data else None

                ticket = db.query(FindingTicket).filter(FindingTicket.Finding_ID == finding_id).first()
                rekap_str = f"{raw_val:.2f}% (Batas Threshold {stage_upper}: {threshold_val:.1f}%)"

                if not ticket:
                    ticket = FindingTicket(
                        Finding_ID=finding_id,
                        period_id=period.id,
                        Bank_ID=b_id,
                        Parameter_Code=code,
                        Nilai_Rekap_BI=rekap_str,
                        Detail_Transaksi_Gugur=gugur_json,
                        Nilai_Klaim_Bank=None,
                        Alasan_Sanggahan=None,
                        File_Bukti_Name=None,
                        AI_Recommendation_Status=None,
                        AI_Analysis_Text=None,
                        BI_Decision_Status="OPEN",
                        Verified_By=None,
                        Updated_At=datetime.utcnow(),
                    )
                    db.add(ticket)
                    created_findings += 1
                else:
                    ticket.Nilai_Rekap_BI = rekap_str
                    if gugur_json and not ticket.Detail_Transaksi_Gugur:
                        ticket.Detail_Transaksi_Gugur = gugur_json
                    ticket.Updated_At = datetime.utcnow()
                    updated_findings += 1

    # Catat audit trail
    audit = AuditTrail(
        action=f"THRESHOLD_RECALCULATE_{stage_upper}",
        performed_by="Rule Engine Evaluator",
        details=f"Evaluasi threshold tahap {stage_upper} selesai. Lolos: {full_compliance_count}, Pembinaan: {pembinaan_count}, Sanksi: {sanksi_count}.",
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "stage": stage_upper,
        "period": period.Triwulan,
        "full_compliance_count": full_compliance_count,
        "pembinaan_count": pembinaan_count,
        "sanksi_count": sanksi_count,
        "created_findings": created_findings,
        "updated_findings": updated_findings,
    }
