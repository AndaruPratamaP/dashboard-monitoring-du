"""
Impor balasan bank atas workbook konfirmasi dan pembandingannya dengan rekap BI (pengganti analisis AI).

Alur:
1. File balasan dikelompokkan per bank: workbook (.xlsx), bukti (.pdf/.png/.jpg), atau file yang
   perlu tindakan manual (ber-password, arsip .7z/.zip, format lain).
2. Sheet workbook dikenali dari namanya walau sedikit berubah (fuzzy match ke nama sheet template).
   Bila bank menaruh tabel versinya di samping tabel BI (mis. kolom "BDI CHECK"), tabel paling
   kanan dianggap isian bank.
3. Isian bank dibandingkan dengan data harian BI (`source_datasets`) per tanggal per tenor.
   Setiap hari yang menurut bank memenuhi tetapi menurut BI tidak menjadi satu item sanggahan.
   Hari yang menurut bank justru lebih buruk dari rekap BI hanya dicatat sebagai selisih informasi.
4. Petugas memutuskan tiap item: DITERIMA -> hari tsb dihitung memenuhi; DITOLAK -> rekap BI tetap.
   Nilai parameter dihitung ulang dari data harian + item yang diterima (`adjusted_rates`).
"""

import datetime as dt
import difflib
import json
import os
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import openpyxl
from sqlalchemy.orm import Session

from models import BankReply, DisputeItem, MasterBank, SourceDataset
from services.counterparty import _read_sheets_fast
from services.entity_resolution import EntityResolver
from services.real_ingest import B6_MIN_RATIO_PCT, B7_MIN_DAYS_PCT, QUOTE_SOURCES

EVIDENCE_EXT = {".pdf", ".png", ".jpg", ".jpeg"}
ARCHIVE_EXT = {".7z", ".zip", ".rar"}

# Nama sheet template -> jenis data
SHEET_TEMPLATES = {
    "srbi-ratio": "rasio srbi minimal 30%",
    "repo-2m": "transaksi repo minimal 2 minggu",
    "srbi-3b": "transaksi srbi 3 bulan",
    "mm-ois": "partisipasi mm ois",
    "quotes": "kuotasi srbi, repo & ois",
}
PARAM_OF = {"srbi-ratio": "B6", "repo-2m": "B7a", "srbi-3b": "B7b", "mm-ois": "B8",
            "bbg-repo": "B1", "bbg-srbi": "B2", "bbg-ois": "B3"}
SOURCE_LABEL = {
    "bbg-repo": "Kuotasi Repo", "bbg-srbi": "Kuotasi SRBI", "bbg-ois": "Kuotasi OIS",
    "srbi-ratio": "Rasio SRBI sekunder", "repo-2m": "Transaksi Repo >= 2 minggu",
    "srbi-3b": "Transaksi SRBI >= 3 bulan", "mm-ois": "Partisipasi MM OIS",
}
# Label kolom kuotasi pada template: Repo on / 1m (= 1 minggu) / 1b (= 1 bulan), SRBI Any, OIS 3b / 12b
QUOTE_COLUMNS = {
    "repo": {"on": "on", "o/n": "on", "1m": "1w", "1w": "1w", "1 minggu": "1w", "1b": "1m", "1 bulan": "1m"},
    "srbi": {"any": "any", "srbi": "any"},
    "ois": {"3b": "3b", "3m": "3b", "3 bulan": "3b", "12b": "12b", "12m": "12b", "1y": "12b", "12 bulan": "12b"},
}
GROUP_SOURCE = {"repo": "bbg-repo", "srbi": "bbg-srbi", "ois": "bbg-ois"}
CHECK_MARKS = {"√", "v", "ok", "✓", "✔", "valid"}
LEGEND_PREFIX = ("keterangan", "0 =", "1 =", "0=", "1=", "ya =", "tidak =", "ya=", "tidak=", "sesuai/tidak")
AGREE_WORDS = {"sesuai", "ok", "setuju", "confirmed", "agree", "-"}
HEADER_WORDS = {"tanggal", "date", "dates", "months", "status", "frekuensi", "no.", "repo", "srbi", "ois",
                "on", "1m", "1b", "any", "3b", "12b", "row labels", "grand total"}
TENOR_LABEL = {"on": "O/N", "1w": "1 minggu", "1m": "1 bulan", "any": "seri SRBI", "3b": "3 bulan",
               "12b": "12 bulan", "1b": "1 bulan"}


# ------------------------------------------------------------------------------
# Pembacaan sel
# ------------------------------------------------------------------------------
def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _date(v: Any) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    n = _num(v)
    if n is not None and 40000 < n < 60000:  # serial Excel
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(n))
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d-%b-%y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(v.strip()[:10], fmt).date()
            except ValueError:
                pass
    return None


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _low(v: Any) -> str:
    return _text(v).lower()


def _lab(v: Any) -> str:
    """Label header dinormalisasi: 'Volume*' -> 'volume', 'Tanggal :' -> 'tanggal'."""
    return re.sub(r"[\s*:]+$", "", _low(v))


def _is_note(v: Any) -> bool:
    if _lab(v) in HEADER_WORDS or _lab(v).startswith(("volume", "jumlah", "total", "persentase", "sum of")):
        return False
    t = _low(v)
    return bool(t) and _num(v) is None and _date(v) is None and t not in AGREE_WORDS \
        and not t.startswith(LEGEND_PREFIX) and t not in ("ya", "tidak", "memenuhi", "tidak memenuhi")


_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7, "agu": 8, "agt": 8,
           "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}


def mentioned_dates(text: str, year: int) -> set:
    """Tanggal yang disebut pada teks: '8 Juli 2026', '21Jul2026', '13 Juli', '20260714'."""
    out = set()
    low = (text or "").lower()
    for d, mon, y in re.findall(r"(\d{1,2})\s*([a-z]{3})[a-z]*\.?\s*(\d{4})?", low):
        if mon in _MONTHS:
            try:
                out.add(dt.date(int(y or year), _MONTHS[mon], int(d)).isoformat())
            except ValueError:
                pass
    for y, m, d in re.findall(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", low):
        try:
            out.add(dt.date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    return out


def classify_sheet(title: str) -> Optional[str]:
    """Kenali jenis sheet dari nama (fuzzy). None = bukan sheet kewajiban harian."""
    low = re.sub(r"\s+", " ", title.strip().lower())
    if "counterparty" in low or low == "index":
        return None
    best, score = None, 0.0
    for kind, name in SHEET_TEMPLATES.items():
        r = difflib.SequenceMatcher(None, low, name).ratio()
        if r > score:
            best, score = kind, r
    # Sheet kuotasi tanggapan sering dipecah: "Kuotasi SRBI, Repo (response)", "Kuotasi OIS (response)"
    if low.startswith("kuotasi") and any(w in low for w in ("repo", "srbi", "ois")):
        return "quotes"
    return best if score >= 0.72 else None


def read_workbook(file_obj) -> Dict[str, List[List[Any]]]:
    """Semua sheet (kolom A:AD). Melempar ValueError bila tidak bisa dibuka (password / bukan xlsx)."""
    try:
        return _read_sheets_fast(file_obj, lambda n: True, max_col=30)
    except Exception:
        try:
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)
            wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
            out = {n: [list(r) for r in wb[n].iter_rows(max_col=30, values_only=True)] for n in wb.sheetnames}
            wb.close()
            return out
        except Exception as e:
            raise ValueError(f"tidak dapat dibuka ({e.__class__.__name__}); kemungkinan ber-password atau bukan .xlsx")


# ------------------------------------------------------------------------------
# Parser per jenis sheet (mengembalikan isian bank)
# ------------------------------------------------------------------------------
def _header_blocks(rows, must: Iterable[str], max_scan: int = 8) -> Tuple[Optional[int], List[int]]:
    """Baris header & kolom awal tiap blok tabel (kolom berlabel `must[0]` yang diikuti label lain)."""
    must = [m.lower() for m in must]
    for i, r in enumerate(rows[:max_scan]):
        labels = [_lab(c) for c in r]
        starts = [c for c, v in enumerate(labels) if v == must[0]]
        starts = [c for c in starts if all(m in labels[c:c + 8] for m in must[1:])]
        if starts:
            return i, starts
    return None, []


def _sheet_notes(rows, hdr: int, starts: List[int], left: int, right: int, date_refs: bool = False) -> List[str]:
    """Teks bebas di luar blok tabel (catatan/rujukan bukti yang ditulis bank), mulai baris header."""
    used = set()
    for s0 in starts:
        used |= set(range(max(0, s0 - left), s0 + right + 1))
    notes = []
    for r in rows[hdr:]:
        for c, v in enumerate(r):
            if c in used:
                continue
            if _is_note(v) and len(_text(v)) > 3:
                notes.append(_text(v)[:200])
            elif date_refs and _date(v) is not None and (_num(v) is None or float(_num(v)).is_integer()):
                # Daftar tanggal di samping tabel = rujukan screenshot/bukti per tanggal (mis. Deutsche)
                notes.append(f"rujukan tanggal {_date(v).isoformat()} di samping tabel")
    seen = set()
    return [n for n in notes if not (n in seen or seen.add(n))][:100]


def parse_volume(rows) -> Optional[Dict[str, Any]]:
    hdr, starts = _header_blocks(rows, ["tanggal", "volume"])
    if hdr is None:
        return None
    labels = [_lab(c) for c in rows[hdr]]
    c_tgl = starts[-1]                     # blok paling kanan = isian bank
    c_vol = labels.index("volume", c_tgl)
    c_sts = next((c for c in range(c_vol, min(c_vol + 3, len(labels))) if labels[c] == "status"), None)
    c_ket = next((c for c in range(c_vol, min(c_vol + 4, len(labels))) if labels[c].startswith("keterangan")), None)
    days = {}
    for r in rows[hdr + 1:]:
        d = _date(r[c_tgl]) if c_tgl < len(r) else None
        if d is None:
            continue
        vol = _num(r[c_vol])
        sts = _num(r[c_sts]) if c_sts is not None else None
        note = [_text(r[c]) for c in range((c_ket if c_ket is not None else c_vol + 2), min(len(r), c_tgl + 14))
                if _is_note(r[c])]
        active = (vol or 0) > 0 or sts == 1
        days[d.isoformat()] = {"aktif": active, "volume": vol, "keterangan": "; ".join(note) or None}
    return {"days": days, "notes": _sheet_notes(rows, hdr, starts, 2, 4)}


def parse_mm_ois(rows) -> Optional[Dict[str, Any]]:
    hdr, starts = _header_blocks(rows, ["tanggal", "1b", "3b"])
    if hdr is None:
        return None
    labels = [_lab(c) for c in rows[hdr]]
    c_tgl = starts[-1]
    c1, c3 = labels.index("1b", c_tgl), labels.index("3b", c_tgl)
    c_ket = next((c for c in range(c3, min(c3 + 3, len(labels))) if labels[c].startswith("keterangan")), c3 + 1)
    days = {}
    for r in rows[hdr + 1:]:
        d = _date(r[c_tgl]) if c_tgl < len(r) else None
        if d is None:
            continue
        note = [_text(r[c]) for c in range(c_ket, min(len(r), c_ket + 6)) if _is_note(r[c])]
        days[d.isoformat()] = {"1b": _low(r[c1]) == "ya", "3b": _low(r[c3]) == "ya",
                               "keterangan": "; ".join(note) or None}
    return {"days": days, "notes": _sheet_notes(rows, hdr, starts, 2, 4)}


def parse_srbi_ratio(rows) -> Optional[Dict[str, Any]]:
    hdr, starts = _header_blocks(rows, ["date", "pasar sekunder jual"])
    if hdr is None:
        return None
    labels = [_lab(c) for c in rows[hdr]]
    c_tgl = starts[-1]
    c_sek = c_tgl + 1
    c_per = next((c for c in range(c_sek, len(labels)) if labels[c].startswith("pasar perdana")), c_sek + 1)
    days, total_sek, perdana = {}, None, None
    for r in rows[hdr + 1:]:
        d = _date(r[c_tgl]) if c_tgl < len(r) else None
        if d is not None:
            days[d.isoformat()] = _num(r[c_sek]) or 0.0
        elif _low(r[c_tgl]) == "total" or (d is None and _num(r[c_per]) is not None and days):
            total_sek, perdana = _num(r[c_sek]), _num(r[c_per])
            break
    if total_sek is None:
        total_sek = sum(days.values())
    return {"days": days, "sekunder": total_sek, "perdana": perdana,
            "notes": _sheet_notes(rows, hdr, starts, 1, c_per - c_tgl + 2)}


def parse_quotes(rows) -> Optional[Dict[str, Any]]:
    hdr, starts = _header_blocks(rows, ["dates"])
    if hdr is None:
        return None
    labels = [_lab(c) for c in rows[hdr]]
    groups_row = rows[hdr - 1] if hdr > 0 else []
    c_tgl = starts[-1]
    end = next((s for s in starts if s > c_tgl), len(labels))
    columns: Dict[Tuple[str, str], int] = {}
    group = None
    for c in range(c_tgl + 1, min(end, c_tgl + 12)):
        g = _low(groups_row[c]) if c < len(groups_row) else ""
        if g in GROUP_SOURCE:
            group = g  # label grup (sel gabungan) bisa berada di kolom tengah, bukan kolom pertama grup
        if not labels[c]:
            continue
        owners = [grp for grp, m in QUOTE_COLUMNS.items() if labels[c] in m]
        grp = owners[0] if len(owners) == 1 else (group if group in owners else None)
        if grp is None:
            continue
        key = QUOTE_COLUMNS[grp][labels[c]]
        if (GROUP_SOURCE[grp], key) not in columns:
            columns[(GROUP_SOURCE[grp], key)] = c
    if not columns:
        return None
    last = max(columns.values())
    c_ket = next((c for c in range(last + 1, min(len(labels), last + 3)) if labels[c].startswith("keterangan")), None)
    days = {}
    for r in rows[hdr + 1:]:
        d = _date(r[c_tgl]) if c_tgl < len(r) else None
        if d is None:
            continue
        vals = {}
        for (src, key), c in columns.items():
            v = r[c] if c < len(r) else None
            n = _num(v)
            vals[(src, key)] = n if n is not None else ("√" if _low(v) in CHECK_MARKS else None)
        note = _text(r[c_ket]) if c_ket is not None and c_ket < len(r) and _is_note(r[c_ket]) else None
        days[d.isoformat()] = {"values": vals, "keterangan": note}
    width = last - c_tgl + (1 if c_ket is None else c_ket - last + 1)
    return {"days": days, "sources": sorted({s for s, _ in columns}),
            "notes": _sheet_notes(rows, hdr, starts, 1, width, date_refs=True)}


PARSERS = {"repo-2m": parse_volume, "srbi-3b": parse_volume, "mm-ois": parse_mm_ois,
           "srbi-ratio": parse_srbi_ratio, "quotes": parse_quotes}


def parse_reply(sheets: Dict[str, List[List[Any]]]) -> Dict[str, Any]:
    """Isian bank per sumber data + daftar pemetaan sheet (dikenali / diabaikan)."""
    found: Dict[str, Any] = {}
    mapping = []
    quotes = []
    for title, rows in sheets.items():
        kind = classify_sheet(title)
        if kind is None:
            if "counterparty" not in title.lower() and title.strip().lower() != "index":
                mapping.append({"sheet": title, "jenis": None, "catatan": "tidak dikenali, diabaikan"})
            continue
        data = PARSERS[kind](rows)
        if data is None:
            mapping.append({"sheet": title, "jenis": kind, "catatan": "struktur tabel tidak ditemukan, diabaikan"})
            continue
        if kind == "quotes":
            quotes.append((title, data))
            continue
        if kind in found:
            mapping.append({"sheet": title, "jenis": kind, "catatan": "duplikat, diabaikan"})
            continue
        found[kind] = data
        mapping.append({"sheet": title, "jenis": kind, "catatan": "dibaca"})
    # Kuotasi: sheet tanggapan ("response"/"respon"/"revisi") menimpa sheet salinan template untuk instrumennya
    quotes.sort(key=lambda t: any(w in t[0].lower() for w in ("respon", "revisi", "tanggapan")))
    for title, data in quotes:
        respon = any(w in title.lower() for w in ("respon", "revisi", "tanggapan"))
        own = [s for s in data["sources"] if not respon or s.split("-")[1] in title.lower()]
        for src in own:
            found[src] = {"days": data["days"], "notes": data["notes"], "sheet": title}
        mapping.append({"sheet": title, "jenis": "kuotasi " + "/".join(s.split("-")[1].upper() for s in own),
                        "catatan": "dibaca" + (" (tanggapan bank)" if respon else "")})
    return {"data": found, "mapping": mapping}


# ------------------------------------------------------------------------------
# Pembandingan isian bank vs data harian BI
# ------------------------------------------------------------------------------
def _quote_ok(v: Any, max_bps: float) -> bool:
    if v == "√":
        return True
    return isinstance(v, (int, float)) and v <= max_bps + 1e-9


def _fmt_spread(v: Any) -> str:
    if v is None:
        return "tidak ada kuotasi"
    if v == "√":
        return "√ (klaim ada kuotasi)"
    return f"{v:g} bps"


INSTRUMENT_SOURCES = {"repo": ("bbg-repo", "repo-2m"), "srbi": ("bbg-srbi", "srbi-3b", "srbi-ratio"),
                      "ois": ("bbg-ois", "mm-ois")}


def invalid_on(source: str, bi: Dict[str, Any], tanggal: str) -> List[Tuple[Optional[str], str]]:
    """(tenor, nilai BI) yang tidak memenuhi pada tanggal tsb menurut data harian BI."""
    out = []
    if source in QUOTE_SOURCES:
        if tanggal in bi["dates"]:
            i = bi["dates"].index(tanggal)
            for t in QUOTE_SOURCES[source]["tenors"]:
                v = bi.get(t["key"], [None] * (i + 1))[i]
                if not _quote_ok(v, t["max_bps"]):
                    out.append((t["key"], _fmt_spread(v)))
    elif source in ("repo-2m", "srbi-3b"):
        if tanggal in bi["dates"] and not bi["volume"][bi["dates"].index(tanggal)] > 0:
            out.append((None, "tidak ada transaksi"))
    elif source == "mm-ois":
        if tanggal in bi["sessions"]:
            i = bi["sessions"].index(tanggal)
            out += [(t, "Tidak") for t in ("1b", "3b") if bi[t][i] != "Ya"]
    return out


def _sources_named(text: str, candidates: Iterable[str]) -> List[str]:
    low = (text or "").lower()
    named = [s for k, srcs in INSTRUMENT_SOURCES.items() if k in low for s in srcs]
    cands = list(candidates)
    return [s for s in cands if s in named] if named else cands


def diff_reply(db: Session, period_id: int, bank_id: str, parsed: Dict[str, Any],
               evidence: Iterable[str] = (), year: Optional[int] = None) -> Dict[str, Any]:
    """
    Item sanggahan = hari yang menurut bank memenuhi tetapi menurut BI tidak, dari tiga jalur:
    (1) nilai di tabel balasan, (2) catatan bank yang menyebut tanggal, (3) nama file bukti yang menyebut tanggal.
    Hari yang menurut bank lebih buruk dari BI dihitung sebagai selisih informasi saja.
    """
    payloads = {
        r.Source: json.loads(r.Payload_JSON)
        for r in db.query(SourceDataset).filter(SourceDataset.period_id == period_id, SourceDataset.Bank_ID == bank_id)
    }
    year = year or dt.date.today().year
    items: List[Dict[str, Any]] = []
    info: Dict[str, int] = {}
    notes: Dict[str, List[str]] = {}
    for src, data in parsed["data"].items():
        bi = payloads.get(src)
        if bi is None:
            continue
        notes[src] = data.get("notes", [])
        days = data["days"]
        param = PARAM_OF[src]

        def add(tanggal, tenor, nilai_bi, nilai_bank, ket, klaim=None):
            items.append({"source": src, "param": param, "tanggal": tanggal, "tenor": tenor,
                          "nilai_bi": nilai_bi, "nilai_bank": nilai_bank, "keterangan": ket, "klaim": klaim})

        if src in QUOTE_SOURCES:
            for t in QUOTE_SOURCES[src]["tenors"]:
                for d, v_bi in zip(bi["dates"], bi.get(t["key"], [])):
                    row = days.get(d)
                    if row is None:
                        continue
                    v_bank = row["values"].get((src, t["key"]))
                    ok_bi, ok_bank = _quote_ok(v_bi, t["max_bps"]), _quote_ok(v_bank, t["max_bps"])
                    if ok_bank and not ok_bi:
                        add(d, t["key"], _fmt_spread(v_bi), _fmt_spread(v_bank), row["keterangan"],
                            {"spread_bps": v_bank if v_bank != "√" else None})
                    elif ok_bi and not ok_bank:
                        info[src] = info.get(src, 0) + 1
        elif src in ("repo-2m", "srbi-3b"):
            for d, vol in zip(bi["dates"], bi["volume"]):
                row = days.get(d)
                if row is None:
                    continue
                if row["aktif"] and not vol > 0:
                    add(d, None, "tidak ada transaksi", f"{row['volume']:,.0f}" if row["volume"] else "ada transaksi",
                        row["keterangan"], {"volume": row["volume"]})
                elif vol > 0 and not row["aktif"]:
                    info[src] = info.get(src, 0) + 1
        elif src == "mm-ois":
            for i, d in enumerate(bi["sessions"]):
                row = days.get(d)
                if row is None:
                    continue
                for tenor in ("1b", "3b"):
                    ya_bi = bi[tenor][i] == "Ya"
                    if row[tenor] and not ya_bi:
                        add(d, tenor, "Tidak", "Ya", row["keterangan"])
                    elif ya_bi and not row[tenor]:
                        info[src] = info.get(src, 0) + 1
        elif src == "srbi-ratio":
            sek_bi, per_bi = sum(bi["sekunder"]), bi["perdana"] or 0.0
            sek_b = data["sekunder"] or 0.0
            per_b = data["perdana"] if data["perdana"] is not None else per_bi
            rasio = lambda s, p: (s / p * 100.0) if p else None
            r_bi, r_b = rasio(sek_bi, per_bi), rasio(sek_b, per_b)
            ok_bi = r_bi is None or r_bi >= B6_MIN_RATIO_PCT
            ok_b = r_b is None or r_b >= B6_MIN_RATIO_PCT
            if abs(sek_b - sek_bi) > 0.5 or abs((per_b or 0) - per_bi) > 0.5:
                if ok_b and not ok_bi or (r_b or 0) > (r_bi or 0) + 0.01:
                    fmt = lambda s, p, r: f"{s:,.1f} / {p:,.1f} M = {r:.2f}%" if r is not None else f"{s:,.1f} / 0 M"
                    add(None, None, fmt(sek_bi, per_bi, r_bi), fmt(sek_b, per_b, r_b), None,
                        {"sekunder": sek_b, "perdana": per_b})
                else:
                    info[src] = info.get(src, 0) + 1
    # (2) & (3): catatan / nama file bukti yang menyebut tanggal hari gugur
    have = {(it["source"], it["tanggal"], it["tenor"]) for it in items}
    refs = [(n, _sources_named(n, [src])) for src, ns in notes.items() for n in ns]
    refs += [(f"bukti: {e}", _sources_named(e, [s for s in payloads if s in PARAM_OF])) for e in evidence]
    for text, srcs in refs:
        for d in sorted(mentioned_dates(text, year)):
            for src in srcs:
                if src not in payloads:
                    continue
                for tenor, nilai_bi in invalid_on(src, payloads[src], d):
                    key = (src, d, tenor)
                    if key in have:
                        continue
                    have.add(key)
                    items.append({"source": src, "param": PARAM_OF[src], "tanggal": d, "tenor": tenor,
                                  "nilai_bi": nilai_bi, "nilai_bank": "klaim di catatan/bukti", "keterangan": None,
                                  "klaim": None})
    # Tautkan catatan & bukti yang menyebut tanggal item ke item tsb
    for it in items:
        related = [t for t, srcs in refs if it["source"] in srcs and it["tanggal"] in mentioned_dates(t, year)]
        if related:
            joined = "; ".join(dict.fromkeys(([it["keterangan"]] if it["keterangan"] else []) + related))
            it["keterangan"] = joined[:1000]
    return {"items": items, "info": info, "notes": notes}


# ------------------------------------------------------------------------------
# Nilai parameter setelah item sanggahan DITERIMA
# ------------------------------------------------------------------------------
def accepted_overrides(db: Session, period_id: int, bank_id: Optional[str] = None) -> Dict[Tuple[str, str], List[DisputeItem]]:
    q = db.query(DisputeItem).filter(DisputeItem.period_id == period_id, DisputeItem.Status == "DITERIMA")
    if bank_id:
        q = q.filter(DisputeItem.Bank_ID == bank_id)
    out: Dict[Tuple[str, str], List[DisputeItem]] = {}
    for it in q:
        out.setdefault((it.Bank_ID, it.Source), []).append(it)
    return out


def rate_with_overrides(source: str, payload: Dict[str, Any], accepted: List[DisputeItem]) -> Tuple[float, Dict[str, Any]]:
    """Hitung ulang nilai parameter dari data harian BI dengan hari/tenor yang sanggahannya diterima."""
    acc = {(a.Tanggal, a.Tenor) for a in accepted}
    if source in QUOTE_SOURCES:
        tenors = QUOTE_SOURCES[source]["tenors"]
        valid = 0
        for i, d in enumerate(payload["dates"]):
            if all(_quote_ok(payload.get(t["key"], [None] * (i + 1))[i], t["max_bps"]) or (d, t["key"]) in acc
                   for t in tenors):
                valid += 1
        total = len(payload["dates"])
        return round(valid / total * 100.0, 2), {"valid_days": valid, "total_days": total}
    if source in ("repo-2m", "srbi-3b"):
        total = len(payload["dates"])
        target = round(B7_MIN_DAYS_PCT / 100.0 * total)
        n = sum(1 for d, v in zip(payload["dates"], payload["volume"]) if v > 0 or (d, None) in acc)
        return (round(min(100.0, n / target * 100.0), 2) if target else 100.0), {"valid_days": n, "target_days": target}
    if source == "mm-ois":
        total = len(payload["sessions"])
        ok = 0
        for i, d in enumerate(payload["sessions"]):
            if all(payload[t][i] == "Ya" or (d, t) in acc for t in ("1b", "3b")):
                ok += 1
        return round(ok / total * 100.0, 2), {"valid_sessions": ok, "total_sessions": total}
    if source == "srbi-ratio":
        sek, per = sum(payload["sekunder"]), payload["perdana"] or 0.0
        for a in accepted:
            k = json.loads(a.Klaim_Bank_JSON or "{}")
            sek, per = k.get("sekunder", sek), k.get("perdana", per)
        if per <= 0:
            return 100.0, {"rasio_penjualan_pct": None}
        ratio = sek / per * 100.0
        return round(min(100.0, ratio / B6_MIN_RATIO_PCT * 100.0), 2), {"rasio_penjualan_pct": round(ratio, 2)}
    raise ValueError(source)


def adjusted_rates(db: Session, period_id: int, bank_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """{bank_id: {param: (rate, detail)}} untuk pasangan bank-sumber yang punya item DITERIMA."""
    out: Dict[str, Dict[str, Any]] = {}
    for (b, src), acc in accepted_overrides(db, period_id, bank_id).items():
        ds = db.query(SourceDataset).filter(SourceDataset.period_id == period_id, SourceDataset.Source == src,
                                            SourceDataset.Bank_ID == b).first()
        if ds is None:
            continue
        rate, detail = rate_with_overrides(src, json.loads(ds.Payload_JSON), acc)
        out.setdefault(b, {})[PARAM_OF[src]] = (rate, {**detail, "sanggahan_diterima": len(acc)})
    return out


def base_rate(db: Session, period_id: int, bank_id: str, source: str) -> Optional[float]:
    ds = db.query(SourceDataset).filter(SourceDataset.period_id == period_id, SourceDataset.Source == source,
                                        SourceDataset.Bank_ID == bank_id).first()
    return rate_with_overrides(source, json.loads(ds.Payload_JSON), [])[0] if ds else None


# ------------------------------------------------------------------------------
# Pengelompokan file balasan per bank
# ------------------------------------------------------------------------------
def bank_for_path(path: str, resolver: EntityResolver, db: Session) -> Optional[MasterBank]:
    """Bank pemilik file: nama folder balasan ('13. Deutsche'), lalu nama file."""
    from services.counterparty import _bank_from_filename
    parent = os.path.basename(os.path.dirname(path))
    for cand in (re.sub(r"^\s*\d+\.\s*", "", parent), parent):
        b = resolver.resolve(cand) if cand else None
        if b:
            return b
    stem = os.path.splitext(os.path.basename(path))[0]
    cleaned = re.sub(r"^\s*\d+\s*[.\-]\s*", "", stem)
    for cand in (cleaned, re.split(r"[_(]", cleaned)[0].strip()):
        b = resolver.resolve(cand)
        if b:
            return b
    return _bank_from_filename(path, db)


def bank_from_sheets(sheets: Dict[str, List[List[Any]]], resolver: EntityResolver) -> Optional[MasterBank]:
    """Nama bank yang tercetak di atas tabel transaksi (mis. 'PT. BANK DBS INDONESIA')."""
    for rows in sheets.values():
        for r in rows[:4]:
            for v in r[:16]:
                if isinstance(v, str) and v.strip().upper().startswith(("PT. BANK", "PT BANK", "BANK ")):
                    b = resolver.resolve(v)
                    if b:
                        return b
    return None


def file_kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return "WORKBOOK"
    if ext in EVIDENCE_EXT:
        return "BUKTI"
    return "MANUAL"


def manual_reason(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in ARCHIVE_EXT:
        return f"arsip {ext}: ekstrak manual lalu unggah isinya"
    return f"format {ext or 'tanpa ekstensi'} tidak didukung"
