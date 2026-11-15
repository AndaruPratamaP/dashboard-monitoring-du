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
    "bbg-repo": {"param": "B1", "pattern": "*Repo Price Quotation*.xlsx", "label": "Kuotasi Repo (Bloomberg)"},
    "bbg-srbi": {"param": "B2", "pattern": "*SRBI Price Quotation*.xlsx", "label": "Kuotasi SRBI (Bloomberg)"},
    "bbg-ois": {"param": "B3", "pattern": "*OIS Price Quotation*.xlsx", "label": "Kuotasi OIS (Bloomberg)"},
    "srbi-ratio": {"param": "B6", "pattern": "*SRBI Rasio Primer*.xlsx", "label": "Rasio Penjualan SRBI Sekunder"},
    "repo-2m": {"param": "B7a", "pattern": "*Repo 2m*.xlsx", "label": "Transaksi Repo tenor >= 2 minggu"},
    "srbi-3b": {"param": "B7b", "pattern": "*SRBI 3b*.xlsx", "label": "Transaksi SRBI sisa >= 3 bulan"},
    "mm-ois": {"param": "B8", "pattern": "*Partisipasi MM OIS*.xlsx", "label": "Partisipasi Matchmaking OIS"},
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

    raw_metrics, breakdown, failed, crosscheck, daily = {}, {}, {}, [], {}
    for bank in resolver.banks:
        valid, missing = 0, []
        flags_1b, flags_3b = [], []
        for d in session_list:
            tenors = quoted.get((bank.Bank_ID, d), set())
            ok1, ok3 = 1 in tenors, 3 in tenors
            flags_1b.append("Ya" if ok1 else "Tidak")
            flags_3b.append("Ya" if ok3 else "Tidak")
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
        daily[bank.Bank_ID] = {"sessions": [d.isoformat() for d in session_list], "1b": flags_1b, "3b": flags_3b}
        raw_metrics[bank.Bank_ID] = {"B8": rate}
        breakdown[bank.Bank_ID] = {"B8": {"valid_sessions": valid, "total_sessions": total, "rate": rate}}
        if missing:
            failed[f"{bank.Bank_ID}-B8"] = missing

    return {
        "param": "B8",
        "dates": session_list,
        "sessions": [d.isoformat() for d in session_list],
        "daily": daily,
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
            "harian": [float(r[col]) if len(r) > col and isinstance(r[col], (int, float)) else 0.0 for r in daily_rows],
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
        "daily": {
            b: {"dates": [d.isoformat() for d in working_days], "sekunder": v["harian"], "perdana": v["perdana"]}
            for b, v in per_bank.items()
        },
        "raw_metrics": raw_metrics,
        "breakdown": breakdown,
        "failed": failed,
        "crosscheck": crosscheck,
        "crosscheck_available": ratio_idx is not None,
        "unknown_banks": unknown,
    }


# ==============================================================================
# B7a / B7b - Rekap transaksi harian (Repo tenor >= 2 minggu, SRBI sisa >= 3 bulan)
# ==============================================================================
B7_MIN_DAYS_PCT = 60.0  # Transaksi minimal pada 60% hari kerja


def _ingest_daily_volume_recap(file_obj, resolver: EntityResolver, param: str, instrument: str) -> Dict[str, Any]:
    """
    Rekap BI berbentuk matriks `Jumlah Hari | Tanggal | Volume* | <bank>...` dengan volume harian
    (filter tenor/sisa jangka waktu sudah diterapkan BI). Hari bertransaksi = volume > 0.
    Baris 'Total Frekuensi' dipakai untuk cross-check.
    """
    wb = _load(file_obj)
    rows = None
    for ws in wb.worksheets:
        cand = list(ws.iter_rows(values_only=True))
        if any(r and str(r[0] or "").strip().lower() == "jumlah hari" for r in cand[:30]):
            rows = cand
            break
    wb.close()
    if rows is None:
        raise IngestError("Tidak ada sheet dengan header 'Jumlah Hari | Tanggal | <bank>'.")

    hdr_idx = next(i for i, r in enumerate(rows[:30]) if r and str(r[0] or "").strip().lower() == "jumlah hari")
    header = rows[hdr_idx]
    daily_rows = [r for r in rows[hdr_idx + 1:] if len(r) > 1 and _as_date(r[1]) is not None]
    dates = [_as_date(r[1]) for r in daily_rows]
    if not dates:
        raise IngestError("Rekap tidak memuat baris tanggal.")
    freq_row = next(
        (r for r in rows[hdr_idx + 1:] if any(isinstance(v, str) and "total frekuensi" in v.lower() for v in r[:4])),
        None,
    )

    total = len(dates)
    target = round(B7_MIN_DAYS_PCT / 100.0 * total)
    daily: Dict[str, Any] = {}
    columns: Dict[str, int] = {}
    unknown = []
    for col in range(2, len(header)):
        label = header[col]
        if not label or str(label).strip().lower().startswith("volume"):
            continue
        bank = resolver.resolve(label)
        if bank is None:
            unknown.append(str(label))
            continue
        columns[bank.Bank_ID] = col

    raw_metrics, breakdown, failed, crosscheck = {}, {}, {}, []
    for bank in resolver.banks:
        col = columns.get(bank.Bank_ID)
        if col is None:
            continue  # bank tidak ada di rekap -> parameter tetap "belum ada data"
        volumes = [float(r[col]) if len(r) > col and isinstance(r[col], (int, float)) else 0.0 for r in daily_rows]
        daily[bank.Bank_ID] = {"dates": [d.isoformat() for d in dates], "volume": volumes}
        active = [d for d, v in zip(dates, volumes) if v > 0]
        n = len(active)
        rate = round(min(100.0, n / target * 100.0), 2) if target else 100.0
        raw_metrics[bank.Bank_ID] = {param: rate}
        breakdown[bank.Bank_ID] = {param: {
            "valid_days": n, "total_days": total, "target_days": target,
            "pct_hari_kerja": round(n / total * 100.0, 2), "rate": rate,
        }}
        if rate < 100.0:
            idle = [d.isoformat() for d in dates if d not in set(active)]
            failed[f"{bank.Bank_ID}-{param}"] = [{
                "hari_bertransaksi": n,
                "target_hari": target,
                "total_hari_kerja": total,
                "tanggal_tanpa_transaksi": idle,
                "alasan": f"Transaksi {instrument} hanya pada {n} dari {total} hari kerja; minimal {target} hari (60%)",
            }]
        if freq_row is not None and len(freq_row) > col and isinstance(freq_row[col], (int, float)) and int(freq_row[col]) != n:
            crosscheck.append({
                "bank_id": bank.Bank_ID, "bank": bank.Nama_Singkat or bank.Nama_Resmi_Bank,
                "hari_hitung": n, "hari_rekap_bi": int(freq_row[col]),
            })

    return {
        "param": param,
        "dates": dates,
        "working_days": [d.isoformat() for d in dates],
        "daily": daily,
        "raw_metrics": raw_metrics,
        "breakdown": breakdown,
        "failed": failed,
        "crosscheck": crosscheck,
        "crosscheck_available": freq_row is not None,
        "unknown_banks": unknown,
    }


def ingest_repo_2m(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    return _ingest_daily_volume_recap(file_obj, resolver, "B7a", "Repo tenor >= 2 minggu")


def ingest_srbi_3b(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    return _ingest_daily_volume_recap(file_obj, resolver, "B7b", "SRBI sisa jangka waktu >= 3 bulan")


# ==============================================================================
# B1 / B2 / B3 - Kuotasi Bloomberg (worksheet "Price Quotation Gen 2")
# ==============================================================================
# Tiap bank punya sheet sendiri (nama = kode BBG). Baris 'Dates' berisi field (PX_BID/PX_ASK atau
# YLD_YTM_BID/ASK); dua baris di atasnya berisi ticker. Kolom bid diikuti kolom ask untuk ticker yang sama.
# Spread (bps) = |bid - ask| x 100. Hari valid = setiap tenor wajib punya kuotasi dua sisi dan
# spread maksimum seluruh seri yang dikuotasi hari itu <= batas (sama dengan kolom 'Spread Maks' BI). Sheet 'Rekap' (spread harian per tenor hasil BI) dipakai untuk cross-check.
QUOTE_SOURCES = {
    "bbg-repo": {
        "param": "B1", "instrument": "Repo",
        "tenors": [  # urutan = urutan kolom per bank pada sheet Rekap
            {"key": "on", "label": "O/N", "tickers": ["RB00UAP2"], "max_bps": 5.0, "ref": "ON"},
            # Batas 1 minggu = 10 bps sesuai ketentuan (dikonfirmasi pemilik produk 15 Nov 2026; sama dengan template kuotasi BI)
            {"key": "1w", "label": "1 minggu", "tickers": ["RB00UAP6"], "max_bps": 10.0, "ref": "1W"},
            {"key": "1m", "label": "1 bulan", "tickers": ["RB00UAP9"], "max_bps": 20.0, "ref": "1M"},
        ],
    },
    "bbg-srbi": {
        "param": "B2", "instrument": "SRBI",
        "tenors": [{"key": "any", "label": "seri SRBI", "tickers": None, "max_bps": 20.0, "ref": None}],
    },
    "bbg-ois": {
        "param": "B3", "instrument": "OIS",
        "tenors": [
            {"key": "3b", "label": "3 bulan", "tickers": ["IHSWOOC"], "max_bps": 20.0, "ref": None},
            {"key": "12b", "label": "12 bulan", "tickers": ["IHSWOO1"], "max_bps": 20.0, "ref": None},
        ],
    },
}


def _ticker_id(label: Any) -> str:
    s = str(label or "").strip()
    return s.split("@")[0].strip() if "@" in s else (s.split()[0] if s else "")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _spread_bps(bid: Any, ask: Any) -> Optional[float]:
    b, a = _num(bid), _num(ask)
    if b is None or a is None:
        return None
    return round(abs(b - a) * 100.0, 4)


def _best_spreads_from_bank_sheet(rows, tenors) -> Tuple[Dict[Tuple[dt.date, str], float], set]:
    """(tanggal, tenor) -> spread terbesar antar seri/ticker; plus set (tanggal, tenor) yang hanya punya kuotasi satu sisi."""
    dates_idx = next((i for i, r in enumerate(rows[:15]) if r and str(r[0] or "").strip().lower() == "dates"), None)
    if dates_idx is None or dates_idx < 2:
        return {}, set()
    tickers = rows[dates_idx - 2] if dates_idx - 2 >= 0 else ()
    fields = rows[dates_idx]
    pairs = []  # (bid_col, ask_col, tenor_key)
    for c in range(1, len(fields) - 1):
        if "BID" in str(fields[c] or "").upper() and "ASK" in str(fields[c + 1] or "").upper():
            tid = _ticker_id(tickers[c] if c < len(tickers) else None)
            for t in tenors:
                if t["tickers"] is None or tid in t["tickers"]:
                    pairs.append((c, c + 1, t["key"]))
                    break
    best: Dict[Tuple[dt.date, str], float] = {}
    one_sided: set = set()
    for r in rows[dates_idx + 1:]:
        d = _as_date(r[0]) if r else None
        if d is None:
            continue
        for bc, ac, key in pairs:
            bid = r[bc] if bc < len(r) else None
            ask = r[ac] if ac < len(r) else None
            sp = _spread_bps(bid, ask)
            if sp is None:
                if (_num(bid) is None) != (_num(ask) is None):
                    one_sided.add((d, key))
                continue
            if (d, key) not in best or sp > best[(d, key)]:
                best[(d, key)] = sp  # BI memakai spread maksimum dari seluruh seri yang dikuotasi
    return best, one_sided


def _best_spreads_from_ref_sheet(rows, tenors) -> Dict[Tuple[dt.date, str], float]:
    """Sheet pengganti `<KODE>_ref` (data dikirim manual bank): kolom '<TENOR> Bid' / '<TENOR> Ask'."""
    hdr_idx = next((i for i, r in enumerate(rows[:10]) if r and str(r[0] or "").strip().lower() == "date"), None)
    if hdr_idx is None:
        return {}
    hdr = [str(v or "").strip().upper() for v in rows[hdr_idx]]
    best = {}
    for t in tenors:
        if not t["ref"]:
            continue
        try:
            bc, ac = hdr.index(f"{t['ref']} BID"), hdr.index(f"{t['ref']} ASK")
        except ValueError:
            continue
        for r in rows[hdr_idx + 1:]:
            d = _as_date(r[0]) if r else None
            sp = _spread_bps(r[bc], r[ac]) if d and len(r) > ac else None
            if sp is not None:
                best[(d, t["key"])] = sp
    return best


def _read_quote_rekap(rows, tenors, resolver: EntityResolver):
    """Sheet Rekap BI: baris 0 = kode bank, baris 'Dates' = sub-header tenor, lalu spread harian ('-' = tidak ada)."""
    hdr_idx = next((i for i, r in enumerate(rows[:10]) if len(r) > 1 and str(r[1] or "").strip().lower() == "dates"), None)
    if hdr_idx is None:
        return [], {}
    dates, values = [], {}
    bank_cols = [(c, resolver.resolve(v)) for c, v in enumerate(rows[0]) if isinstance(v, str) and v.strip()]
    for r in rows[hdr_idx + 1:]:
        d = _as_date(r[1]) if len(r) > 1 else None
        if d is None:
            continue
        dates.append(d)
        for c, bank in bank_cols:
            if bank is None:
                continue
            for k, t in enumerate(tenors):
                v = r[c + k] if len(r) > c + k else None
                values[(bank.Bank_ID, d, t["key"])] = round(abs(v), 4) if _num(v) is not None else None
    return dates, values


def _ingest_bbg_quotes(file_obj, resolver: EntityResolver, source: str) -> Dict[str, Any]:
    cfg = QUOTE_SOURCES[source]
    param, tenors = cfg["param"], cfg["tenors"]
    wb = _load(file_obj)
    names = wb.sheetnames
    rekap_name = next((n for n in names if n.strip().lower() == "rekap"), None)
    rekap_dates, rekap_vals = _read_quote_rekap(list(wb[rekap_name].iter_rows(values_only=True)), tenors, resolver) \
        if rekap_name else ([], {})

    bank_sheets: Dict[str, str] = {}
    for n in names:
        bank = resolver.by_code.get(n.strip().upper())
        if bank is not None and bank.Bank_ID not in bank_sheets:
            bank_sheets[bank.Bank_ID] = n
    if not bank_sheets:
        raise IngestError(f"Tidak ada sheet per bank (kode BBG) pada file. Sheet yang ada: {names[:12]}...")

    spreads: Dict[str, Dict] = {}
    one_sided: Dict[str, set] = {}
    manual_ref: set = set()
    rekap_fallback: set = set()
    all_dates: set = set()
    for bank_id, sheet in bank_sheets.items():
        rows = list(wb[sheet].iter_rows(values_only=True))
        best, one = _best_spreads_from_bank_sheet(rows, tenors)
        ref_name = next((n for n in names if n.strip().upper() == f"{sheet.strip().upper()}_REF"), None)
        if not best and ref_name:
            best = _best_spreads_from_ref_sheet(list(wb[ref_name].iter_rows(values_only=True)), tenors)
            if best:
                manual_ref.add(bank_id)
        if not best and not one:
            # Ticker Bloomberg tidak valid / sheet kosong: BI mengisi Rekap dari sumber lain.
            # Pakai spread pada Rekap BI agar bank tidak dinilai 0%, dan tandai untuk verifikasi.
            from_rekap = {(d, k): v for (b, d, k), v in rekap_vals.items() if b == bank_id and v is not None}
            if from_rekap:
                best = from_rekap
                rekap_fallback.add(bank_id)
        spreads[bank_id], one_sided[bank_id] = best, one
        all_dates.update(d for d, _ in best)
    wb.close()

    # Kalender hari kerja: tanggal pada Rekap BI; bila tidak ada, tanggal kuotasi pada triwulan terbanyak
    if rekap_dates:
        dates = sorted(set(rekap_dates))
    else:
        by_q: Dict[Tuple[int, int], set] = defaultdict(set)
        for d in all_dates:
            by_q[(d.year, (d.month - 1) // 3)].add(d)
        dates = sorted(max(by_q.values(), key=len)) if by_q else []
    if not dates:
        raise IngestError("Tidak ada tanggal kuotasi yang dapat dibaca.")
    total = len(dates)

    raw_metrics, breakdown, failed, crosscheck, daily = {}, {}, {}, [], {}
    for bank in resolver.banks:
        if bank.Bank_ID not in spreads:
            continue
        best, one = spreads[bank.Bank_ID], one_sided[bank.Bank_ID]
        valid, gugur = 0, []
        per_tenor_valid = {t["key"]: 0 for t in tenors}
        for d in dates:
            problems = []
            for t in tenors:
                sp = best.get((d, t["key"]))
                if sp is None:
                    why = "kuotasi hanya satu sisi" if (d, t["key"]) in one else "tidak ada kuotasi"
                    problems.append({"tenor": t["label"], "spread_bps": None, "masalah": why})
                elif sp > t["max_bps"]:
                    problems.append({"tenor": t["label"], "spread_bps": sp, "batas_bps": t["max_bps"],
                                     "masalah": f"spread {sp:g} bps > maks. {t['max_bps']:g} bps"})
                else:
                    per_tenor_valid[t["key"]] += 1
                # cross-check per tenor terhadap rekap BI (status valid/tidak)
                if rekap_vals:
                    g = rekap_vals.get((bank.Bank_ID, d, t["key"]), "absent")
                    if g != "absent":
                        mine_ok = sp is not None and sp <= t["max_bps"]
                        bi_ok = g is not None and g <= t["max_bps"]
                        if mine_ok != bi_ok:
                            crosscheck.append({
                                "bank_id": bank.Bank_ID, "bank": bank.Nama_Singkat or bank.Nama_Resmi_Bank,
                                "tanggal": d.isoformat(), "tenor": t["label"],
                                "spread_data_mentah": sp, "spread_rekap_bi": g,
                            })
            if problems:
                gugur.append({
                    "tanggal": d.isoformat(),
                    "rincian": problems,
                    "alasan": f"{cfg['instrument']} {d.isoformat()}: " + "; ".join(
                        f"{p['tenor']} {p['masalah']}" for p in problems),
                })
            else:
                valid += 1
        rate = round(valid / total * 100.0, 2)
        daily[bank.Bank_ID] = {"dates": [d.isoformat() for d in dates],
                               **{t["key"]: [best.get((d, t["key"])) for d in dates] for t in tenors},
                               # (tanggal, tenor) yang hanya punya kuotasi satu sisi -> keterangan lampiran
                               "satu_sisi": {t["key"]: [d.isoformat() for d in dates
                                                        if best.get((d, t["key"])) is None and (d, t["key"]) in one]
                                             for t in tenors}}
        raw_metrics[bank.Bank_ID] = {param: rate}
        breakdown[bank.Bank_ID] = {param: {
            "valid_days": valid, "total_days": total, "rate": rate,
            "valid_per_tenor": {t["label"]: per_tenor_valid[t["key"]] for t in tenors},
            "sumber": ("rekap BI (ticker Bloomberg tidak valid)" if bank.Bank_ID in rekap_fallback
                       else "sheet manual bank (_ref)" if bank.Bank_ID in manual_ref else "Bloomberg"),
        }}
        if gugur:
            failed[f"{bank.Bank_ID}-{param}"] = gugur

    return {
        "param": param,
        "dates": dates,
        "working_days": [d.isoformat() for d in dates],
        "raw_metrics": raw_metrics,
        "breakdown": breakdown,
        "failed": failed,
        "crosscheck": crosscheck,
        "crosscheck_available": bool(rekap_vals),
        "unknown_banks": [],
        "daily": daily,
        "source_notes": [
            {"bank_id": b, "catatan": "Data Bloomberg kosong/ticker tidak valid; dinilai dari Rekap BI (perlu verifikasi sumber)"}
            for b in sorted(rekap_fallback)
        ] + [
            {"bank_id": b, "catatan": "Data dari sheet manual bank (_ref), bukan Bloomberg"} for b in sorted(manual_ref)
        ],
    }


def ingest_bbg_repo(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    return _ingest_bbg_quotes(file_obj, resolver, "bbg-repo")


def ingest_bbg_srbi(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    return _ingest_bbg_quotes(file_obj, resolver, "bbg-srbi")


def ingest_bbg_ois(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    return _ingest_bbg_quotes(file_obj, resolver, "bbg-ois")


INGESTERS = {
    "bbg-repo": ingest_bbg_repo,
    "bbg-srbi": ingest_bbg_srbi,
    "bbg-ois": ingest_bbg_ois,
    "srbi-ratio": ingest_srbi_ratio,
    "repo-2m": ingest_repo_2m,
    "srbi-3b": ingest_srbi_3b,
    "mm-ois": ingest_mm_ois,
}
