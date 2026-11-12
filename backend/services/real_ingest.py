"""
Ingest data ril (format file kerja DPPK) per sumber data.

Sprint 1:
- MM OIS (B8)      : file "Rekap Kewajiban Partisipasi MM OIS_*.xlsx"
                     sheet `Kuotasi` = export mentah DS Antasena (dasar perhitungan),
                     sheet `Rekap`   = rekap BI pasca-konfirmasi (dipakai untuk cross-check).
- Rasio SRBI (B6)  : file "Rekap Transaksi SRBI Rasio Primer_*.xlsx"
                     sheet `2. Rekap Sekunder Primer TW` = penjualan sekunder harian per bank
                     + total menang lelang perdana; baris `% Pasar Sekunder Jual` untuk cross-check.

Setiap parser mengembalikan hasil per Bank_ID beserta rincian untuk drill-down,
detail kegagalan untuk tiket temuan, dan daftar selisih terhadap rekap BI.
"""

import datetime as dt
import glob
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from services.entity_resolution import EntityResolver

B6_MIN_RATIO_PCT = 30.0  # Penjualan sekunder minimal 30% dari volume win lelang perdana (kumulatif triwulan)

SOURCES = {
    "mm-ois": {"param": "B8", "pattern": "*Partisipasi MM OIS*.xlsx", "label": "Partisipasi Matchmaking OIS"},
    "srbi-ratio": {"param": "B6", "pattern": "*SRBI Rasio Primer*.xlsx", "label": "Rasio Penjualan SRBI Sekunder"},
}


class IngestError(ValueError):
    """Format file tidak sesuai template yang diharapkan."""


def default_dataset_dir() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.environ.get(
        "REAL_DATASET_DIR",
        os.path.join(base, "..", "dataset real proses as is", "Evaluasi Triwulanan Periode Jul - Sep 2026"),
    )


def find_default_file(source: str) -> str:
    pattern = SOURCES[source]["pattern"]
    root = default_dataset_dir()
    matches = sorted(glob.glob(os.path.join(root, "**", pattern), recursive=True))
    matches = [m for m in matches if not os.path.basename(m).startswith("~$")]
    if not matches:
        raise IngestError(f"File '{pattern}' tidak ditemukan di folder dataset ril ({root}). Unggah file secara manual.")
    return matches[0]


def period_from_dates(dates: List[dt.date]) -> Tuple[int, str]:
    """Tentukan (tahun, 'YYYY-Qn') dari tanggal data; seluruh tanggal harus dalam satu triwulan."""
    if not dates:
        raise IngestError("File tidak memuat tanggal data.")
    quarters = {(d.year, (d.month - 1) // 3 + 1) for d in dates}
    if len(quarters) > 1:
        raise IngestError(f"Tanggal data mencakup lebih dari satu triwulan: {sorted(quarters)}.")
    year, q = quarters.pop()
    return year, f"{year}-Q{q}"


def _as_date(v: Any) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def _load(file_obj) -> openpyxl.Workbook:
    try:
        return openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
    except Exception as e:  # file rusak / ber-password / bukan xlsx
        raise IngestError(f"File tidak dapat dibuka sebagai .xlsx: {e}")


# ==============================================================================
# B8 - Partisipasi Matchmaking OIS
# ==============================================================================
def ingest_mm_ois(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    wb = _load(file_obj)
    if "Kuotasi" not in wb.sheetnames:
        raise IngestError(f"Sheet 'Kuotasi' tidak ditemukan. Sheet yang ada: {wb.sheetnames}")

    # 1. Kuotasi mentah: (bank, tanggal) -> set tenor
    quoted: Dict[Tuple[str, dt.date], set] = defaultdict(set)
    sessions: set = set()
    unknown: set = set()
    header_seen = False
    for row in wb["Kuotasi"].iter_rows(values_only=True):
        if not header_seen:
            header_seen = row and str(row[0]).strip().lower() == "no"
            continue
        tanggal, sandi, tenor = _as_date(row[2]), row[3], row[4]
        if tanggal is None or sandi is None:
            continue
        sessions.add(tanggal)
        bank = resolver.resolve(sandi)
        if bank is None:
            unknown.add(str(sandi))
            continue
        try:
            quoted[(bank.Bank_ID, tanggal)].add(int(tenor))
        except (TypeError, ValueError):
            continue

    # 2. Rekap BI (opsional) untuk cross-check; tanggal sesi juga diambil dari sini
    golden: Dict[Tuple[str, dt.date], Tuple[str, str]] = {}
    if "Rekap" in wb.sheetnames:
        rows = list(wb["Rekap"].iter_rows(values_only=True))
        if rows:
            for col, label in enumerate(rows[0]):
                if not label:
                    continue
                bank = resolver.resolve(label)
                if bank is None:
                    unknown.add(str(label))
                    continue
                for r in rows[3:]:
                    d = _as_date(r[1]) if len(r) > 1 else None
                    if d is None or len(r) <= col + 5:
                        continue
                    sessions.add(d)
                    golden[(bank.Bank_ID, d)] = (str(r[col + 4] or "").strip(), str(r[col + 5] or "").strip())
    wb.close()

    session_list = sorted(sessions)
    total = len(session_list)
    if total == 0:
        raise IngestError("Tidak ada tanggal sesi matchmaking OIS pada file.")

    raw_metrics, breakdown, failed, crosscheck = {}, {}, {}, []
    for bank in resolver.banks:
        valid, missing = 0, []
        for d in session_list:
            tenors = quoted.get((bank.Bank_ID, d), set())
            ok1, ok3 = 1 in tenors, 3 in tenors
            if ok1 and ok3:
                valid += 1
            else:
                lacking = [t for t, ok in (("1 bulan", ok1), ("3 bulan", ok3)) if not ok]
                missing.append({
                    "tanggal": d.isoformat(),
                    "tenor_tidak_dikuotasi": lacking,
                    "alasan": f"Tidak ada kuotasi tenor {' & '.join(lacking)} pada sesi matchmaking OIS {d.isoformat()}",
                })
            g = golden.get((bank.Bank_ID, d))
            if g is not None:
                mine = ("Ya" if ok1 else "Tidak", "Ya" if ok3 else "Tidak")
                if mine != g:
                    crosscheck.append({
                        "bank_id": bank.Bank_ID, "bank": bank.Nama_Singkat or bank.Nama_Resmi_Bank,
                        "tanggal": d.isoformat(),
                        "hasil_data_mentah": {"1b": mine[0], "3b": mine[1]},
                        "rekap_bi": {"1b": g[0], "3b": g[1]},
                    })
        rate = round(valid / total * 100.0, 2)
        raw_metrics[bank.Bank_ID] = {"B8": rate}
        breakdown[bank.Bank_ID] = {"B8": {"valid_sessions": valid, "total_sessions": total, "rate": rate}}
        if missing:
            failed[f"{bank.Bank_ID}-B8"] = missing

    return {
        "param": "B8",
        "dates": session_list,
        "sessions": [d.isoformat() for d in session_list],
        "raw_metrics": raw_metrics,
        "breakdown": breakdown,
        "failed": failed,
        "crosscheck": crosscheck,
        "crosscheck_available": bool(golden),
        "unknown_banks": sorted(unknown),
    }


# ==============================================================================
# B6 - Rasio penjualan SRBI di pasar sekunder terhadap win lelang perdana
# ==============================================================================
def _find_row(rows, label: str) -> Optional[int]:
    for i, r in enumerate(rows[:20]):
        for v in r[:3]:
            if v is not None and str(v).strip().lower().startswith(label):
                return i
    return None


def ingest_srbi_ratio(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    wb = _load(file_obj)
    sheet = next((n for n in wb.sheetnames if "sekunder" in n.lower() and "primer" in n.lower()), None)
    if sheet is None:
        raise IngestError(f"Sheet rekap sekunder-primer tidak ditemukan. Sheet yang ada: {wb.sheetnames}")
    rows = list(wb[sheet].iter_rows(values_only=True))
    wb.close()

    hdr_idx = next((i for i, r in enumerate(rows[:30]) if r and str(r[0] or "").strip().lower() == "jumlah hari"), None)
    perdana_idx = _find_row(rows, "pasar perdana")
    ratio_idx = _find_row(rows, "% pasar sekunder")
    if hdr_idx is None or perdana_idx is None:
        raise IngestError("Baris header 'Jumlah Hari | Tanggal | <bank>' atau baris 'Pasar Perdana' tidak ditemukan.")

    header = rows[hdr_idx]
    daily_rows = [r for r in rows[hdr_idx + 1:] if len(r) > 1 and _as_date(r[1]) is not None]
    working_days = [_as_date(r[1]) for r in daily_rows]

    per_bank: Dict[str, Dict[str, float]] = {}
    unknown = []
    for col in range(2, len(header)):
        label = header[col]
        if not label:
            continue
        bank = resolver.resolve(label)
        if bank is None:
            unknown.append(str(label))
            continue
        sekunder = sum(float(r[col] or 0) for r in daily_rows if len(r) > col and isinstance(r[col], (int, float)))
        perdana_v = rows[perdana_idx][col] if len(rows[perdana_idx]) > col else None
        perdana = float(perdana_v) if isinstance(perdana_v, (int, float)) else 0.0
        ratio_rekap = rows[ratio_idx][col] if ratio_idx is not None and len(rows[ratio_idx]) > col else None
        per_bank[bank.Bank_ID] = {
            "sekunder": sekunder,
            "perdana": perdana,
            "ratio_rekap_pct": float(ratio_rekap) * 100.0 if isinstance(ratio_rekap, (int, float)) else None,
        }

    raw_metrics, breakdown, failed, crosscheck = {}, {}, {}, []
    for bank in resolver.banks:
        v = per_bank.get(bank.Bank_ID)
        if v is None:
            raw_metrics[bank.Bank_ID] = {"B6": 0.0}
            breakdown[bank.Bank_ID] = {"B6": {"win_perdana": None, "actual_sales": None, "rate": 0.0}}
            failed[f"{bank.Bank_ID}-B6"] = [{"alasan": "Bank tidak ditemukan pada rekap rasio SRBI sekunder-primer"}]
            continue
        sek, per = v["sekunder"], v["perdana"]
        if per > 0:
            ratio_pct = sek / per * 100.0
            rate = round(min(100.0, ratio_pct / B6_MIN_RATIO_PCT * 100.0), 2)
        else:
            ratio_pct = None
            rate = 100.0  # Tidak memiliki win lelang perdana -> tidak ada kewajiban penjualan
        raw_metrics[bank.Bank_ID] = {"B6": rate}
        breakdown[bank.Bank_ID] = {"B6": {
            "win_perdana": round(per, 3), "target_sales": round(per * B6_MIN_RATIO_PCT / 100.0, 3),
            "actual_sales": round(sek, 3),
            "rasio_penjualan_pct": round(ratio_pct, 2) if ratio_pct is not None else None,
            "rate": rate,
        }}
        if rate < 100.0:
            failed[f"{bank.Bank_ID}-B6"] = [{
                "volume_win_perdana_miliar": round(per, 3),
                "target_kewajiban_30pct_miliar": round(per * 0.30, 3),
                "realisasi_penjualan_sekunder_miliar": round(sek, 3),
                "rasio_penjualan": f"{ratio_pct:.2f}%",
                "alasan": f"Penjualan SRBI sekunder {ratio_pct:.2f}% dari win perdana, di bawah kewajiban minimal 30%",
            }]
        if v["ratio_rekap_pct"] is not None and ratio_pct is not None and abs(v["ratio_rekap_pct"] - ratio_pct) > 0.01:
            crosscheck.append({
                "bank_id": bank.Bank_ID, "bank": bank.Nama_Singkat or bank.Nama_Resmi_Bank,
                "rasio_hitung_pct": round(ratio_pct, 2), "rasio_rekap_bi_pct": round(v["ratio_rekap_pct"], 2),
            })

    return {
        "param": "B6",
        "dates": working_days,
        "working_days": [d.isoformat() for d in working_days],
        "raw_metrics": raw_metrics,
        "breakdown": breakdown,
        "failed": failed,
        "crosscheck": crosscheck,
        "crosscheck_available": ratio_idx is not None,
        "unknown_banks": unknown,
    }


INGESTERS = {"mm-ois": ingest_mm_ois, "srbi-ratio": ingest_srbi_ratio}
