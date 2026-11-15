"""
Rule Engine Evaluasi Dealer Utama PUVA
Berdasarkan PADG No. 23 Tahun 2024 & PBI No. 6 Tahun 2024
Departemen Pengembangan Pasar Keuangan (DPPK) Bank Indonesia
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.orm import Session

from models import MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail, get_active_period

logger = logging.getLogger("rule_engine")

# 1. AMBANG BATAS (THRESHOLDS) BERDASARKAN TAHAP
THRESHOLDS = {
    "EARLY": {
        "B1": 80.0, "B2": 80.0, "B3": 80.0,
        "B4": 50.0, "B5": 50.0,
        "B6": 80.0, "B7a": 80.0, "B7b": 80.0, "B8": 80.0,
    },
    "INTERMEDIATE": {
        "B1": 85.0, "B2": 85.0, "B3": 85.0,
        "B4": 70.0, "B5": 70.0,
        "B6": 85.0, "B7a": 85.0, "B7b": 85.0, "B8": 85.0,
    },
    "END_STATE": {
        "B1": 90.0, "B2": 90.0, "B3": 90.0,
        "B4": 80.0, "B5": 80.0,
        "B6": 90.0, "B7a": 90.0, "B7b": 90.0, "B8": 90.0,
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
}

PARAMETER_DETAILS = {
    "B1": "Setiap hari kerja; spread maks. 5 bps (O/N), 10 bps (1W), 20 bps (1M)",
    "B2": "Setiap hari kerja; kuotasi dua sisi; spread maks. 20 bps untuk seluruh seri yang dikuotasi",
    "B3": "Setiap hari kerja; tenor 3 bulan & 12 bulan; spread maks. 20 bps",
    "B4": "Minimal 10 bank DU dan 10 bank non-DU pada akhir periode",
    "B5": "Minimal 10 bank DU pada akhir periode",
    "B6": "Minimal 30% dari volume win pada lelang pasar perdana (status SETTLED)",
    "B7a": "Tenor minimal 2 minggu (>=14 hari), minimal 60% hari kerja",
    "B7b": "Sisa jangka waktu minimal 3 bulan, minimal 60% hari kerja",
    "B8": "Kuotasi tenor 1 bulan & 3 bulan pada setiap sesi matchmaking OIS",
}


PUVA_CODES = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]
MAX_PUVA_SCORE = round(sum(WEIGHTS[c] for c in PUVA_CODES), 2)  # 60.0

STATUS_MEMENUHI = "MEMENUHI"
STATUS_TIDAK_MEMENUHI = "TIDAK_MEMENUHI"
STATUS_DATA_BELUM_LENGKAP = "DATA_BELUM_LENGKAP"


def canonical_code(code: str) -> str:
    """Normalisasi kode parameter ('b7A', 'B7A ' -> 'B7a')."""
    c = (code or "").strip().upper()
    return c[:-1] + c[-1].lower() if c in ("B7A", "B7B") else c


def matrix_to_raw(entry: BankScoreMatrix) -> Dict[str, Optional[float]]:
    """Ambil nilai realisasi mentah B1-B8 dari baris matriks (None = data belum diunggah)."""
    raw: Dict[str, Optional[float]] = {}
    for code in PUVA_CODES:
        val = getattr(entry, f"{code.lower()}_raw", None)
        raw[code] = float(val) if val is not None else None
    return raw


def evaluate_parameter(param_code: str, raw_value: Optional[float], stage: str = "EARLY") -> Dict[str, Any]:
    """
    Evaluasi satu indikator terhadap threshold aktif.
    Lolos (raw >= threshold) -> skor = bobot; gagal -> 0.
    raw_value None -> sumber data belum diunggah: passed None, skor 0.
    """
    st = stage.upper() if stage.upper() in THRESHOLDS else "EARLY"
    threshold = THRESHOLDS[st].get(param_code, 80.0)
    weight = WEIGHTS.get(param_code, 0.0)

    if raw_value is None:
        passed = None
        score = 0.0
    else:
        passed = round(raw_value, 2) >= round(threshold, 2)
        score = weight if passed else 0.0

    return {
        "parameter_code": param_code,
        "name": PARAMETER_NAMES.get(param_code, param_code),
        "raw_value": round(raw_value, 2) if raw_value is not None else None,
        "threshold": threshold,
        "weight": weight,
        "passed": passed,
        "score": score,
    }


def compute_matrix_scores(raw_dict: dict, stage: str = "EARLY") -> Dict[str, Any]:
    """
    Hitung skor terbobot 9 parameter PUVA, total skor PUVA (maks 60%), dan status akhir.
    Parameter yang tidak ada di raw_dict / bernilai None dianggap belum ada data.
    """
    results: Dict[str, Any] = {}
    total_puva = 0.0
    any_failed = False
    any_missing = False

    for code in PUVA_CODES:
        res = evaluate_parameter(code, raw_dict.get(code), stage)
        key = code.lower()
        results[f"{key}_raw"] = res["raw_value"]
        results[f"{key}_passed"] = res["passed"]
        results[f"{key}_score"] = res["score"]
        total_puva += res["score"]
        if res["passed"] is None:
            any_missing = True
        elif not res["passed"]:
            any_failed = True

    if any_failed:
        status = STATUS_TIDAK_MEMENUHI
    elif any_missing:
        status = STATUS_DATA_BELUM_LENGKAP
    else:
        status = STATUS_MEMENUHI

    results["total_puva_score"] = round(total_puva, 2)
    results["compliance_status"] = status
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
        period = get_active_period(db)

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
    closed_findings = []
    status_counts = {STATUS_MEMENUHI: 0, STATUS_TIDAK_MEMENUHI: 0, STATUS_DATA_BELUM_LENGKAP: 0}

    puva_codes = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]

    for b in banks:
        b_id = b.Bank_ID
        matrix_entry = db.query(BankScoreMatrix).filter(
            BankScoreMatrix.period_id == period.id,
            BankScoreMatrix.Bank_ID == b_id
        ).first()

        # Ambil raw metrics: hasil ingest baru > nilai tersimpan > None (sumber belum diunggah).
        # Bank yang tidak muncul di file sumber yang SUDAH diunggah diberi 0 oleh parser.
        bank_raw = matrix_to_raw(matrix_entry) if matrix_entry else {code: None for code in puva_codes}
        if raw_metrics and b_id in raw_metrics:
            bank_raw.update({k: v for k, v in raw_metrics[b_id].items() if k in puva_codes})

        # Terapkan kembali nilai hasil sanggahan yang telah DISETUJUI petugas BI,
        # agar ETL ulang / ganti tahap tidak menghapus keputusan human-in-the-loop.
        approved_tickets = db.query(FindingTicket).filter(
            FindingTicket.Bank_ID == b_id,
            FindingTicket.period_id == period.id,
            FindingTicket.BI_Decision_Status == "APPROVED",
            FindingTicket.Approved_Value.isnot(None),
        ).all()
        for t in approved_tickets:
            code = canonical_code(t.Parameter_Code)
            if code in bank_raw:
                bank_raw[code] = max(bank_raw[code] or 0.0, float(t.Approved_Value))

        # Hitung skor berdasarkan threshold aktif
        scores = compute_matrix_scores(bank_raw, stage=stage_upper)

        if not matrix_entry:
            matrix_entry = BankScoreMatrix(period_id=period.id, Bank_ID=b_id)
            db.add(matrix_entry)

        for k, v in scores.items():
            if hasattr(matrix_entry, k):
                setattr(matrix_entry, k, v)

        if breakdown_stats and b_id in breakdown_stats:
            # Gabungkan dengan rincian parameter lain (ingest bisa per sumber data)
            try:
                merged = json.loads(matrix_entry.detail_metrics_json or "{}")
            except ValueError:
                merged = {}
            merged.update(breakdown_stats[b_id])
            matrix_entry.detail_metrics_json = json.dumps(merged)

        matrix_entry.updated_at = datetime.utcnow()

        status_counts[scores["compliance_status"]] += 1

        # Cek apakah ada parameter PUVA yang gugur terhadap threshold aktif
        for code in puva_codes:
            code_key = code.lower()
            is_passed = scores.get(f"{code_key}_passed")
            raw_val = scores.get(f"{code_key}_raw")
            threshold_val = THRESHOLDS[stage_upper].get(code, 80.0)

            # Format Finding_ID standar: FND-2026Q2-DU01-B2
            b_short = b_id.replace("-", "")
            finding_id = f"FND-{triwulan_str}-{b_short}-{code.upper()}"

            if is_passed is False:
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
                    if ticket.BI_Decision_Status == "CLOSED":
                        ticket.BI_Decision_Status = "OPEN"  # gagal lagi setelah sempat lolos -> temuan dibuka kembali
                    ticket.Updated_At = datetime.utcnow()
                    updated_findings += 1
            elif is_passed is True:
                # Parameter lolos (hasil sanggahan/rekalkulasi/ganti tahap) -> tiket terbuka ditutup otomatis
                ticket = db.query(FindingTicket).filter(
                    FindingTicket.Finding_ID == finding_id,
                    FindingTicket.BI_Decision_Status.in_(["OPEN", "PENDING_REVIEW"]),
                ).first()
                if ticket:
                    ticket.BI_Decision_Status = "CLOSED"
                    ticket.Nilai_Rekap_BI = f"{raw_val:.2f}% (lolos threshold {stage_upper}: {threshold_val:.1f}%)"
                    ticket.Updated_At = datetime.utcnow()
                    closed_findings.append(finding_id)

    # Catat audit trail
    audit = AuditTrail(
        action=f"THRESHOLD_RECALCULATE_{stage_upper}",
        performed_by="Rule Engine Evaluator",
        details=(
            f"Evaluasi threshold tahap {stage_upper} ({period.Triwulan}) selesai. "
            f"Memenuhi: {status_counts[STATUS_MEMENUHI]}, Tidak memenuhi: {status_counts[STATUS_TIDAK_MEMENUHI]}, "
            f"Data belum lengkap: {status_counts[STATUS_DATA_BELUM_LENGKAP]}."
            + (f" Tiket ditutup otomatis: {', '.join(closed_findings)}." if closed_findings else "")
        ),
    )
    db.add(audit)
    db.commit()

    return {
        "status": "success",
        "stage": stage_upper,
        "period": period.Triwulan,
        "memenuhi_count": status_counts[STATUS_MEMENUHI],
        "tidak_memenuhi_count": status_counts[STATUS_TIDAK_MEMENUHI],
        "data_belum_lengkap_count": status_counts[STATUS_DATA_BELUM_LENGKAP],
        "created_findings": created_findings,
        "updated_findings": updated_findings,
        "closed_findings": closed_findings,
    }
