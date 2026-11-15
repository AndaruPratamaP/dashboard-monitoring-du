"""
Dokumen akhir evaluasi dalam format dokumen ril DPPK (TW III 2026):
- M.02  : memorandum permohonan persetujuan hasil evaluasi kepada pimpinan DPPK.
- M.01  : memorandum penyampaian hasil evaluasi kepada DSMM.
- Lampiran M.01/M.02 : matriks per tenor *sebelum* dan *setelah* penerapan threshold + tabel
  "Keterangan Hasil Evaluasi" per bank (tanggal & alasan). Lampiran M.02 ditambah daftar sanggahan
  yang memerlukan keputusan pimpinan (eskalasi).
- Surat informasi pemenuhan kewajiban (pengantar workbook konfirmasi ke 21 bank).
- Matriks dalam Excel (bahan olah lanjutan).

Seluruh angka dihitung dari data harian BI per sumber (`source_datasets`) ditambah sanggahan yang
DITERIMA, sehingga sama dengan nilai parameter di matriks dashboard. Status lolos/tidak setelah
threshold mengikuti hasil rule engine (`bank_score_matrix`).
"""

import io
import json
import os
import statistics
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from models import BankScoreMatrix, ConfirmationRound, DisputeItem, EvaluationPeriod, MasterBank, SourceDataset
from services import replies as replies_service
from services.real_ingest import B6_MIN_RATIO_PCT, B7_MIN_DAYS_PCT, QUOTE_SOURCES
from services.rule_engine import PARAMETER_NAMES, THRESHOLDS

MASTER_BANK_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "master_bank_du.json")

BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
         "Oktober", "November", "Desember"]
BULAN_PENDEK = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
STAGE_TEXT = {
    "EARLY": "early stage (tahap awal)",
    "INTERMEDIATE": "intermediate stage (tahap menengah)",
    "END_STATE": "end state (tahap akhir)",
}

# Pejabat & nomor surat: diisi lewat environment (backend/.env, tidak masuk git) agar nama pejabat tidak tersimpan di kode.
def _env(key: str, default: str) -> str:
    return (os.getenv(key) or "").strip() or default


def doc_config() -> Dict[str, Any]:
    return {
        "kepala_departemen": {
            "nama": _env("DOC_KADEP_NAMA", "[Nama Kepala Departemen]"),
            "jabatan": _env("DOC_KADEP_JABATAN", "Kepala Departemen"),
            "pangkat": _env("DOC_KADEP_PANGKAT", "Direktur"),
        },
        "kepala_grup": {
            "nama": _env("DOC_KAGRUP_NAMA", "[Nama Kepala Grup]"),
            "jabatan": _env("DOC_KAGRUP_JABATAN", "Kepala Grup Pengembangan Produk dan Pricing PUVA"),
            "pangkat": _env("DOC_KAGRUP_PANGKAT", "Direktur"),
        },
        "pemeriksa": {
            "nama": _env("DOC_PEMERIKSA_NAMA", "[Nama Analis Senior]"),
            "jabatan": _env("DOC_PEMERIKSA_JABATAN", "Analis Senior"),
            "pangkat": _env("DOC_PEMERIKSA_PANGKAT", "Asisten Direktur"),
        },
        "penyusun": {
            "nama": _env("DOC_PENYUSUN_NAMA", "[Nama Analis]"),
            "jabatan": _env("DOC_PENYUSUN_JABATAN", "Analis"),
            "pangkat": _env("DOC_PENYUSUN_PANGKAT", "Manajer"),
        },
        "email_konfirmasi": _env("DOC_EMAIL_KONFIRMASI", "[alamat email unit]"),
    }


# ==============================================================================
# Format teks
# ==============================================================================
_SATUAN = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]


def terbilang(n: int) -> str:
    n = int(n)
    if n == 0:
        return "nol"
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_SATUAN[n - 10]} belas"
    if n < 100:
        return f"{_SATUAN[n // 10]} puluh" + (f" {terbilang(n % 10)}" if n % 10 else "")
    if n < 200:
        return "seratus" + (f" {terbilang(n - 100)}" if n > 100 else "")
    if n < 1000:
        return f"{_SATUAN[n // 100]} ratus" + (f" {terbilang(n % 100)}" if n % 100 else "")
    return str(n)


def angka(n: int) -> str:
    """15 -> '15 (lima belas)'."""
    return f"{n} ({terbilang(n)})"


def gabung(items: List[str]) -> str:
    """['a','b','c'] -> 'a, b, dan c'."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} dan {items[1]}"
    return ", ".join(items[:-1]) + ", dan " + items[-1]


def tanggal_panjang(d: date) -> str:
    return f"{d.day} {BULAN[d.month]} {d.year}"


def daftar_tanggal(dates: List[str]) -> str:
    """Tanggal ISO dikelompokkan per bulan: '7, 8, dan 9 Juli 2026; dan 4 Agustus 2026'."""
    ds = sorted({date.fromisoformat(d) for d in dates})
    months: Dict[Tuple[int, int], List[int]] = {}
    for d in ds:
        months.setdefault((d.year, d.month), []).append(d.day)
    parts = [f"{gabung([str(x) for x in days])} {BULAN[m]} {y}" for (y, m), days in months.items()]
    if len(parts) <= 1:
        return "".join(parts)
    return ";\n".join(parts[:-1]) + "; dan\n" + parts[-1]


def period_info(period: EvaluationPeriod) -> Dict[str, Any]:
    year, q = (period.Triwulan or "2026-Q1").split("-Q")
    year, q = int(year), int(q)
    m1, m3 = (q - 1) * 3 + 1, q * 3
    last_day = date(year + (m3 == 12), (m3 % 12) + 1, 1) - date.resolution
    return {
        "triwulan": period.Triwulan,
        "tahun": year,
        "label": f"{BULAN[m1]} \u2013 {BULAN[m3]} {year}",          # Juli – September 2026
        "label_sd": f"{BULAN[m1]} s.d. {BULAN[m3]} {year}",         # Juli s.d. September 2026
        "label_pendek": f"{BULAN_PENDEK[m1]} - {BULAN_PENDEK[m3]} {year}",  # Jul - Sep 2026
        "akhir": last_day,
        "nomor_tahun": year - 1998,                                 # penomoran surat BI: 2026 -> 28
        "stage": period.Active_Threshold_Stage or "EARLY",
    }


# ==============================================================================
# Kolom matriks lampiran (urutan & label mengikuti lampiran memo ril)
# ==============================================================================
# kind: pct (persen hari/sesi valid), ratio (persen rasio), count (jumlah line)
COLUMNS: List[Dict[str, Any]] = [
    {"key": "repo_on", "group": "Kuotasi Repo", "label": "o/n", "param": "B1", "kind": "pct", "target": 100.0},
    {"key": "repo_1w", "group": "Kuotasi Repo", "label": "1m", "param": "B1", "kind": "pct", "target": 100.0},
    {"key": "repo_1m", "group": "Kuotasi Repo", "label": "1b", "param": "B1", "kind": "pct", "target": 100.0},
    {"key": "ois_3b", "group": "Kuotasi OIS", "label": "3b", "param": "B3", "kind": "pct", "target": 100.0},
    {"key": "ois_12b", "group": "Kuotasi OIS", "label": "12b", "param": "B3", "kind": "pct", "target": 100.0},
    {"key": "srbi", "group": "Kuotasi SRBI", "label": "", "param": "B2", "kind": "pct", "target": 100.0},
    {"key": "trx_sekunder", "group": "Transaksi", "label": "Sekunder Jual/Primer", "param": "B6", "kind": "ratio", "target": B6_MIN_RATIO_PCT},
    {"key": "trx_repo", "group": "Transaksi", "label": "Repo", "param": "B7a", "kind": "ratio", "target": B7_MIN_DAYS_PCT},
    {"key": "trx_srbi", "group": "Transaksi", "label": "SRBI", "param": "B7b", "kind": "ratio", "target": B7_MIN_DAYS_PCT},
    {"key": "ctp_repo_du", "group": "Ctp Line Repo", "label": "DU", "param": "B4", "kind": "count", "target": 10.0},
    {"key": "ctp_repo_non", "group": "Ctp Line Repo", "label": "Non DU", "param": "B4", "kind": "count", "target": 10.0},
    {"key": "ctp_ois_du", "group": "Ctp Line OIS", "label": "DU", "param": "B5", "kind": "count", "target": 10.0},
    {"key": "mm_1b", "group": "Partisipasi Matchmaking OIS", "label": "1b", "param": "B8", "kind": "pct", "target": 100.0},
    {"key": "mm_3b", "group": "Partisipasi Matchmaking OIS", "label": "3b", "param": "B8", "kind": "pct", "target": 100.0},
]
QUOTE_COL = {("bbg-repo", "on"): "repo_on", ("bbg-repo", "1w"): "repo_1w", ("bbg-repo", "1m"): "repo_1m",
             ("bbg-ois", "3b"): "ois_3b", ("bbg-ois", "12b"): "ois_12b", ("bbg-srbi", "any"): "srbi"}
GROUP_COLOR = {"Kuotasi Repo": "00B050", "Kuotasi OIS": "00B050", "Kuotasi SRBI": "00B050", "Transaksi": "0070C0",
               "Ctp Line Repo": "7030A0", "Ctp Line OIS": "7030A0", "Partisipasi Matchmaking OIS": "FFC000"}
GROUP_FONT = {"Partisipasi Matchmaking OIS": "000000"}

# Kolom tabel "Keterangan Hasil Evaluasi". Kolom bertanda always=True selalu tampil (seperti dokumen ril).
NOTE_COLUMNS = [
    {"key": "repo", "label": "Kuotasi Repo", "always": True},
    {"key": "ois", "label": "Kuotasi OIS", "always": True},
    {"key": "srbi", "label": "Kuotasi SRBI", "always": True},
    {"key": "transaksi", "label": "Transaksi", "always": False},
    {"key": "ctp_repo", "label": "Counterparty Line Repo", "always": False},
    {"key": "mm", "label": "Partisipasi Matchmaking OIS", "always": True},
    {"key": "ctp_ois", "label": "Counterparty Line OIS", "always": True},
]
INSTRUMENT = {"bbg-repo": ("repo", "repo"), "bbg-ois": ("ois", "OIS"), "bbg-srbi": ("srbi", "SRBI")}
TENOR_TEXT = {"on": "overnight", "1w": "1 minggu", "1m": "1 bulan", "3b": "3 bulan", "12b": "12 bulan", "any": ""}
TENOR_MEMO = {"on": "overnight", "1w": "1 (satu) minggu", "1m": "1 (satu) bulan", "3b": "3 (tiga) bulan",
              "12b": "12 (dua belas) bulan", "1b": "1 (satu) bulan"}


def target_after(col: Dict[str, Any], stage: str) -> float:
    return col["target"] * THRESHOLDS[stage][col["param"]] / 100.0


def label_target(col: Dict[str, Any], value: float) -> str:
    if col["kind"] == "count":
        return f"Min {value:g}"
    if col["kind"] == "ratio":
        return f"Min {value:g}%"
    return f"{value:g}%"


def fmt_value(col: Dict[str, Any], v: Optional[float]) -> str:
    if v is None:
        return "-"
    if col["kind"] == "count":
        return f"{int(v)}"
    r = round(v)
    if v < col["target"] and r >= col["target"]:  # 99,6% tetap tampil di bawah target
        r = int(col["target"]) - 1
    return f"{r}%"


def _bank_meta() -> Dict[str, Dict[str, Any]]:
    try:
        with open(MASTER_BANK_JSON, encoding="utf-8") as f:
            return {b["bank_id"]: b for b in json.load(f)["banks"]}
    except (OSError, ValueError, KeyError):
        return {}


# ==============================================================================
# Perhitungan evaluasi untuk dokumen
# ==============================================================================
def _quote_rows(source: str, payload: Dict[str, Any], accepted: set) -> Dict[str, Any]:
    """Per tenor: persen hari valid + daftar masalah (tanggal) setelah sanggahan diterima."""
    out = {}
    dates = payload["dates"]
    one_sided = payload.get("satu_sisi", {})
    for t in QUOTE_SOURCES[source]["tenors"]:
        vals = payload.get(t["key"], [None] * len(dates))
        ok, kosong, satu_sisi, spread = 0, [], [], []
        for d, v in zip(dates, vals):
            if replies_service._quote_ok(v, t["max_bps"]) or (d, t["key"]) in accepted:
                ok += 1
            elif v is None:
                (satu_sisi if d in one_sided.get(t["key"], []) else kosong).append(d)
            else:
                spread.append({"tanggal": d, "spread_bps": v, "batas_bps": t["max_bps"]})
        out[t["key"]] = {"rate": ok / len(dates) * 100.0 if dates else None, "kosong": kosong,
                         "satu_sisi": satu_sisi, "spread": spread}
    return out


def _quote_notes(source: str, per_tenor: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Kalimat keterangan lampiran + tenor yang belum terpenuhi (untuk memo)."""
    _, inst = INSTRUMENT[source]
    single = len(QUOTE_SOURCES[source]["tenors"]) == 1
    notes, failed = [], []
    # Tidak ada kuotasi: kelompokkan tanggal menurut kombinasi tenor yang kosong pada hari itu
    by_day: Dict[str, List[str]] = {}
    for key, r in per_tenor.items():
        for d in r["kosong"]:
            by_day.setdefault(d, []).append(key)
        if r["kosong"] or r["satu_sisi"] or r["spread"]:
            failed.append(key)
    combos: Dict[Tuple[str, ...], List[str]] = {}
    for d, keys in by_day.items():
        combos.setdefault(tuple(sorted(keys, key=list(per_tenor).index)), []).append(d)
    for keys, ds in sorted(combos.items(), key=lambda kv: min(kv[1])):
        tenor = "" if single else f" tenor {gabung([TENOR_TEXT[k] for k in keys])}"
        notes.append(f"Tidak terdapat kuotasi {inst}{tenor} pada tanggal:\n{daftar_tanggal(ds)}.")
    for key, r in per_tenor.items():
        tenor = "" if single else f" tenor {TENOR_TEXT[key]}"
        if r["satu_sisi"]:
            notes.append(f"Kuotasi {inst}{tenor} hanya 1 sisi pada tanggal {daftar_tanggal(r['satu_sisi'])}.")
        for s in r["spread"]:
            notes.append(
                f"Kuotasi {inst}{tenor} pada tanggal {tanggal_panjang(date.fromisoformat(s['tanggal']))} melebihi "
                f"ketentuan spread sebesar maksimum {s['batas_bps']:g} bps, spread kuotasi sebesar {s['spread_bps']:g} bps.")
    return notes, failed


def _fmt_claim(v: Any, source: str) -> str:
    if v is None or v == "":
        return "tidak ada kuotasi" if source in QUOTE_SOURCES else "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:g} bps" if source in QUOTE_SOURCES else f"{f:,.0f}".replace(",", ".")


def build_evaluation(db: Session, period: EvaluationPeriod) -> Dict[str, Any]:
    info = period_info(period)
    stage = info["stage"]
    meta = _bank_meta()
    banks = db.query(MasterBank).all()
    banks.sort(key=lambda b: (meta.get(b.Bank_ID, {}).get("urutan_lampiran", 99), b.Bank_ID))
    matrices = {m.Bank_ID: m for m in db.query(BankScoreMatrix).filter(BankScoreMatrix.period_id == period.id)}
    datasets: Dict[Tuple[str, str], Dict[str, Any]] = {
        (s.Bank_ID, s.Source): json.loads(s.Payload_JSON)
        for s in db.query(SourceDataset).filter(SourceDataset.period_id == period.id)
    }
    accepted = replies_service.accepted_overrides(db, period.id)

    rows = []
    for no, bank in enumerate(banks, 1):
        m = matrices.get(bank.Bank_ID)
        detail = json.loads(m.detail_metrics_json or "{}") if m else {}
        nama = meta.get(bank.Bank_ID, {}).get("nama_lampiran") or bank.Nama_Singkat or bank.Bank_ID
        cells: Dict[str, Optional[float]] = {c["key"]: None for c in COLUMNS}
        notes: Dict[str, List[str]] = {c["key"]: [] for c in NOTE_COLUMNS}
        memo: List[str] = []

        # Kuotasi Repo / OIS / SRBI
        for source in ("bbg-repo", "bbg-ois", "bbg-srbi"):
            payload = datasets.get((bank.Bank_ID, source))
            if not payload:
                continue
            acc = {(a.Tanggal, a.Tenor) for a in accepted.get((bank.Bank_ID, source), [])}
            per_tenor = _quote_rows(source, payload, acc)
            for key, r in per_tenor.items():
                cells[QUOTE_COL[(source, key)]] = r["rate"]
            n, failed = _quote_notes(source, per_tenor)
            note_key, inst = INSTRUMENT[source]
            notes[note_key] += n
            if failed:
                n_tenor = len(QUOTE_SOURCES[source]["tenors"])
                tenors = "" if n_tenor == 1 or (n_tenor > 2 and len(failed) == n_tenor) else                     f" tenor {gabung([TENOR_MEMO[k] for k in failed])}"
                memo.append(f"kuotasi harga {inst}{tenors}")

        # Transaksi: rasio penjualan sekunder (B6) dan hari bertransaksi Repo/SRBI (B7a/B7b)
        p = datasets.get((bank.Bank_ID, "srbi-ratio"))
        if p:
            _, d = replies_service.rate_with_overrides("srbi-ratio", p, accepted.get((bank.Bank_ID, "srbi-ratio"), []))
            cells["trx_sekunder"] = d.get("rasio_penjualan_pct")
        elif detail.get("B6"):
            cells["trx_sekunder"] = detail["B6"].get("rasio_penjualan_pct")
        for source, key, label in (("repo-2m", "trx_repo", "repo"), ("srbi-3b", "trx_srbi", "SRBI")):
            p = datasets.get((bank.Bank_ID, source))
            if p and p.get("dates"):
                acc = {a.Tanggal for a in accepted.get((bank.Bank_ID, source), [])}
                n = sum(1 for d, v in zip(p["dates"], p["volume"]) if v > 0 or d in acc)
                cells[key] = n / len(p["dates"]) * 100.0
                if cells[key] < B7_MIN_DAYS_PCT:
                    notes["transaksi"].append(
                        f"Transaksi {label} dilakukan pada {n} dari {len(p['dates'])} hari kerja ({cells[key]:.0f}%) "
                        f"dengan ketentuan minimal {B7_MIN_DAYS_PCT:g}% hari kerja.")
                    memo.append(f"transaksi {label}")
        if cells["trx_sekunder"] is not None and cells["trx_sekunder"] < B6_MIN_RATIO_PCT:
            notes["transaksi"].insert(0,
                f"Rasio penjualan SRBI di pasar sekunder terhadap pembelian di pasar perdana sebesar "
                f"{cells['trx_sekunder']:.0f}% dengan ketentuan minimal {B6_MIN_RATIO_PCT:g}%.")
            memo.append("penjualan SRBI di pasar sekunder")

        # Counterparty line (kondisi akhir periode)
        b4, b5 = detail.get("B4") or {}, detail.get("B5") or {}
        if b4:
            cells["ctp_repo_du"], cells["ctp_repo_non"] = b4.get("line_du"), b4.get("line_non_du")
            for key, label in (("ctp_repo_du", "Dealer Utama PUVA"), ("ctp_repo_non", "non-Dealer Utama PUVA")):
                if cells[key] is not None and cells[key] < 10:
                    notes["ctp_repo"].append(f"Jumlah counterparty line repo dengan {label} sebesar {cells[key]} line "
                                             f"dengan ketentuan minimal 10 line.")
                    memo.append(f"jumlah counterparty line repo dengan {label}")
        if b5:
            cells["ctp_ois_du"] = b5.get("line_du")
            if cells["ctp_ois_du"] is not None and cells["ctp_ois_du"] < 10:
                notes["ctp_ois"].append(f"Jumlah counterparty line OIS dengan Dealer Utama PUVA sebesar "
                                        f"{cells['ctp_ois_du']} line dengan ketentuan minimal 10 line.")
                memo.append("jumlah counterparty line OIS dengan Dealer Utama PUVA")

        # Partisipasi matchmaking OIS
        p = datasets.get((bank.Bank_ID, "mm-ois"))
        if p and p.get("sessions"):
            acc = {(a.Tanggal, a.Tenor) for a in accepted.get((bank.Bank_ID, "mm-ois"), [])}
            gagal_by_tenor = {}
            for t in ("1b", "3b"):
                ok = [s for s, v in zip(p["sessions"], p[t]) if v == "Ya" or (s, t) in acc]
                cells[f"mm_{t}"] = len(ok) / len(p["sessions"]) * 100.0
                gagal_by_tenor[t] = [s for s in p["sessions"] if s not in ok]
            combos: Dict[Tuple[str, ...], List[str]] = {}
            for s in p["sessions"]:
                ks = tuple(t for t in ("1b", "3b") if s in gagal_by_tenor[t])
                if ks:
                    combos.setdefault(ks, []).append(s)
            for ks, ss in combos.items():
                notes["mm"].append(f"Tidak terdapat kuotasi tenor {gabung([TENOR_TEXT['1m' if k == '1b' else k] for k in ks])} "
                                   f"pada sesi matchmaking OIS tanggal:\n{daftar_tanggal(ss)}.")
            if combos:
                memo.append("partisipasi matchmaking OIS")

        # Lolos 100% (sebelum threshold) & lolos threshold (rule engine)
        gagal_sebelum = {c["key"]: cells[c["key"]] is not None and cells[c["key"]] < c["target"] - 1e-9 for c in COLUMNS}
        params_failed = [c for c in PARAMETER_NAMES if m is not None and getattr(m, f"{c.lower()}_passed", None) is False]
        gagal_setelah = {c["key"]: c["param"] in params_failed and cells[c["key"]] is not None
                         and cells[c["key"]] < target_after(c, stage) - 1e-9 for c in COLUMNS}
        # Parameter gagal threshold tetapi tiap tenor di atas batas (agregat hari): tandai seluruh tenor < 100%
        for c in COLUMNS:
            if c["param"] in params_failed and not any(gagal_setelah[x["key"]] for x in COLUMNS if x["param"] == c["param"]):
                gagal_setelah[c["key"]] = gagal_sebelum[c["key"]]
        rows.append({
            "no": no, "bank_id": bank.Bank_ID, "nama": nama, "nama_resmi": bank.Nama_Resmi_Bank,
            "cells": cells, "gagal_sebelum": gagal_sebelum, "gagal_setelah": gagal_setelah,
            "keterangan": notes, "memo": memo,
            "penuh": not any(gagal_sebelum.values()) and not memo,
            "lolos_threshold": m is not None and not params_failed,
            "parameter_gagal": params_failed, "ada_data": m is not None,
        })

    stats = {}
    for c in COLUMNS:
        vals = [r["cells"][c["key"]] for r in rows if r["cells"][c["key"]] is not None]
        stats[c["key"]] = {"mean": statistics.mean(vals) if vals else None,
                           "median": statistics.median(vals) if vals else None}

    # Sanggahan per tanggal: rekap keputusan + eskalasi ke pimpinan
    items = db.query(DisputeItem).filter(DisputeItem.period_id == period.id).all()
    names = {r["bank_id"]: r["nama"] for r in rows}
    eskalasi = []
    for it in sorted(items, key=lambda x: (names.get(x.Bank_ID, ""), x.Parameter_Code, x.Tanggal or "")):
        if not replies_service.needs_escalation(it):
            continue
        hist = json.loads(it.History_JSON or "[]")
        last_reject = next((h for h in reversed(hist) if h.get("event") == "DITOLAK"), {})
        eskalasi.append({
            "id": it.id, "bank_id": it.Bank_ID, "bank": names.get(it.Bank_ID, it.Bank_ID),
            "parameter": it.Parameter_Code, "nama_parameter": PARAMETER_NAMES.get(it.Parameter_Code, it.Parameter_Code),
            "tanggal": it.Tanggal, "tenor": replies_service.TENOR_LABEL.get(it.Tenor or "", it.Tenor or ""),
            "nilai_bi": _fmt_claim(it.Nilai_BI, it.Source), "nilai_bank": _fmt_claim(it.Nilai_Bank, it.Source),
            "keterangan_bank": it.Keterangan_Bank or "", "ronde": f"{it.Round_No}\u2013{it.Last_Round}",
            "alasan_penolakan": last_reject.get("catatan") or it.Decision_Note or "",
        })
    rekap = {s: sum(1 for i in items if i.Status == s) for s in ("DITERIMA", "DITOLAK", "OPEN")}

    penuh = [r for r in rows if r["ada_data"] and r["penuh"]]
    belum = [r for r in rows if r["ada_data"] and not r["penuh"]]
    gagal = [r for r in rows if r["ada_data"] and not r["lolos_threshold"]]
    return {
        "period": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in info.items()},
        "stage_text": STAGE_TEXT.get(stage, stage),
        "is_locked": bool(period.Is_Snapshot_Locked),
        "locked_at": period.Locked_At.isoformat() if period.Locked_At else None,
        "columns": [{**c, "target_after": target_after(c, stage),
                     "label_before": label_target(c, c["target"]), "label_after": label_target(c, target_after(c, stage))}
                    for c in COLUMNS],
        "note_columns": [c for c in NOTE_COLUMNS if c["always"] or any(r["keterangan"][c["key"]] for r in rows)],
        "rows": rows, "stats": stats,
        "ringkasan": {
            "jumlah_bank": sum(1 for r in rows if r["ada_data"]),
            "penuh": [r["nama"] for r in penuh], "belum_penuh": [r["nama"] for r in belum],
            "lolos_threshold": [r["nama"] for r in rows if r["ada_data"] and r["lolos_threshold"]],
            "tidak_lolos_threshold": [r["nama"] for r in gagal],
            "tanpa_data": [r["nama"] for r in rows if not r["ada_data"]],
        },
        "sanggahan": {"total": len(items), **rekap, "eskalasi": len(eskalasi)},
        "eskalasi": eskalasi,
    }


def memo_points(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Kalimat inti memo (dipakai dokumen dan pratinjau UI)."""
    s = ev["ringkasan"]
    n_pen, n_bel = len(s["penuh"]), len(s["belum_penuh"])
    n_lolos, n_gagal = len(s["lolos_threshold"]), len(s["tidak_lolos_threshold"])
    hasil = f"Berdasarkan evaluasi, terdapat {angka(n_pen)} Dealer Utama PUVA yang telah memenuhi 100% kewajiban di pasar uang."
    if n_bel:
        hasil += f" Selain itu, terdapat {angka(n_bel)} Dealer Utama PUVA yang belum 100% memenuhi kewajiban, yaitu:"
    per_bank = [f"{r['nama']}: belum sepenuhnya memenuhi kewajiban {gabung(r['memo'])}."
                for r in ev["rows"] if r["ada_data"] and not r["penuh"]]
    kesimpulan = (
        f"Berdasarkan evaluasi kewajiban Dealer Utama PUVA periode {ev['period']['label']}, terdapat {angka(n_pen)} "
        f"Dealer Utama PUVA yang telah memenuhi 100% kewajiban di pasar uang"
        + (f" dan {angka(n_bel)} Dealer Utama PUVA belum 100% memenuhi kewajiban." if n_bel else ".")
        + f" Selanjutnya berdasarkan tahapan threshold saat ini yaitu {ev['stage_text']}, terdapat {angka(n_lolos)} bank "
        f"yang memenuhi kewajiban Dealer Utama PUVA di pasar uang"
        + (f" dan {angka(n_gagal)} bank yang belum memenuhi kewajiban Dealer Utama PUVA di pasar uang, yaitu "
           f"{gabung(s['tidak_lolos_threshold'])}." if n_gagal else ".")
    )
    sg = ev["sanggahan"]
    konfirmasi = None
    if sg["total"]:
        bagian = [f"{angka(sg[k])} {teks}" for k, teks in (("DITERIMA", "diterima"), ("DITOLAK", "ditolak"),
                                                            ("OPEN", "masih dalam proses verifikasi")) if sg[k]]
        konfirmasi = (
            f"Hasil evaluasi telah dikonfirmasi kepada seluruh Dealer Utama PUVA. Dari {angka(sg['total'])} sanggahan per "
            f"tanggal yang disampaikan bank, {gabung(bagian)}."
        )
        if sg["eskalasi"]:
            konfirmasi += (f" Sebanyak {angka(sg['eskalasi'])} sanggahan telah diajukan kembali pada lebih dari satu ronde "
                           f"konfirmasi dan memerlukan keputusan pimpinan sebagaimana Lampiran II.")
    return {"hasil": hasil, "per_bank": per_bank, "kesimpulan": kesimpulan, "konfirmasi": konfirmasi}


# ==============================================================================
# DOCX helpers
# ==============================================================================
def _new_document(landscape: bool = False, margins_cm: float = 2.5) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(margins_cm))
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    st.paragraph_format.space_after = Pt(4)
    return doc


def _draft_header(doc: Document, ev: Dict[str, Any]):
    if ev["is_locked"]:
        return
    p = doc.sections[0].header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run("DRAFT \u2013 snapshot evaluasi belum dikunci")
    r.font.size, r.font.bold, r.font.color.rgb = Pt(8), True, RGBColor(0xC0, 0x00, 0x00)


def _p(doc_or_cell, text: str = "", bold=False, size=None, align=None, indent_cm=None, first_line_cm=None,
       space_after=None, italic=False):
    p = doc_or_cell.add_paragraph()
    if text:
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
    if align is not None:
        p.alignment = align
    if indent_cm is not None:
        p.paragraph_format.left_indent = Cm(indent_cm)
    if first_line_cm is not None:
        p.paragraph_format.first_line_indent = Cm(first_line_cm)
    if space_after is not None:
        p.paragraph_format.space_after = Pt(space_after)
    return p


def _numbered(doc, label: str, text: str, indent_cm: float, hang_cm: float = 0.6, bold=False):
    p = _p(doc, f"{label}\t{text}", bold=bold, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_cm=indent_cm,
           first_line_cm=-hang_cm)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(indent_cm))
    return p


def _shade(cell, hex_fill: str):
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:shd")):
        tcPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _cell_text(cell, text: str, bold=False, size=7, color=None, align=WD_ALIGN_PARAGRAPH.CENTER, fill=None):
    cell.text = ""
    lines = str(text).split("\n")
    p = cell.paragraphs[0]
    for i, line in enumerate(lines):
        if i:
            p = cell.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        r = p.add_run(line)
        r.bold = bold
        r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    if fill:
        _shade(cell, fill)


def _borders(table, color="808080", sz="4"):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), sz)
        e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def _widths(table, cms: List[float]):
    table.autofit = False
    for row in table.rows:
        for cell, w in zip(row.cells, cms):
            cell.width = Cm(w)


def _keep_together(table):
    """Baris tabel tidak terpotong antarhalaman dan tetap menempel dengan baris berikutnya."""
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.keep_with_next = True


def _no_borders(table):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "nil")
        b.append(e)
    tblPr.append(b)


def _signature(cell, cfg: Dict[str, str], caption: str):
    _cell_text(cell, caption, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    for line, bold, under in ((cfg["jabatan"], False, False), ("", False, False), ("", False, False),
                              (cfg["nama"], True, True), (cfg["pangkat"], False, False)):
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.font.size, r.bold, r.underline = Pt(10), bold, under


def _stream(doc: Document) -> io.BytesIO:
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


# ==============================================================================
# Lampiran (matriks sebelum/sesudah threshold + keterangan + eskalasi)
# ==============================================================================
def _matrix_table(doc: Document, ev: Dict[str, Any], after: bool):
    cols = ev["columns"]
    n = 2 + len(cols)
    t = doc.add_table(rows=3 + len(ev["rows"]) + 2, cols=n)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t, "A6A6A6")
    # Baris 0: periode; baris 1: grup; baris 2: sub-kolom + target
    top = t.cell(0, 2).merge(t.cell(0, n - 1))
    _cell_text(top, f"Periode {ev['period']['label_pendek']}", bold=True, size=8, color="FFFFFF", fill="000000")
    nb = t.cell(0, 0).merge(t.cell(0, 1))
    _cell_text(nb, "", fill="FFFFFF")
    for j, head in ((0, "No"), (1, "Bank\nDU PUVA")):
        c = t.cell(1, j).merge(t.cell(2, j))
        _cell_text(c, head, bold=True, size=7, color="FFFFFF", fill="002060")
    j = 2
    while j < n:
        g = cols[j - 2]["group"]
        k = j
        while k + 1 < n and cols[k + 1 - 2]["group"] == g:
            k += 1
        fill, font = GROUP_COLOR[g], GROUP_FONT.get(g, "FFFFFF")
        if g == "Kuotasi SRBI":  # satu kolom: label grup + target digabung vertikal
            c = t.cell(1, j).merge(t.cell(2, j))
            lab = cols[j - 2]["label_after" if after else "label_before"]
            _cell_text(c, f"{g}\n({lab})", bold=True, size=7, color=font, fill=fill)
        else:
            c = t.cell(1, j).merge(t.cell(1, k)) if k > j else t.cell(1, j)
            _cell_text(c, g, bold=True, size=7, color=font, fill=fill)
            for x in range(j, k + 1):
                col = cols[x - 2]
                lab = col["label_after" if after else "label_before"]
                sub_fill = "FFC000" if g.startswith("Partisipasi") else "002060" if g != "Transaksi" else "0070C0"
                sub_font = "000000" if g.startswith("Partisipasi") else "FFFFFF"
                if g.startswith("Kuotasi") or g.startswith("Ctp"):
                    sub_fill = fill if g.startswith("Kuotasi") else "7030A0"
                _cell_text(t.cell(2, x), f"{col['label']}\n({lab})", bold=True, size=7, color=sub_font, fill=sub_fill)
        j = k + 1
    flag = "gagal_setelah" if after else "gagal_sebelum"
    for i, r in enumerate(ev["rows"]):
        row = t.rows[3 + i]
        bank_fail = any(r[flag].values())
        _cell_text(row.cells[0], str(r["no"]), size=7)
        _cell_text(row.cells[1], r["nama"], size=7, align=WD_ALIGN_PARAGRAPH.LEFT, fill="FFC7CE" if bank_fail else None)
        for x, col in enumerate(cols):
            bad = r[flag][col["key"]]
            _cell_text(row.cells[2 + x], fmt_value(col, r["cells"][col["key"]]), size=7,
                       color="C00000" if bad else None, align=WD_ALIGN_PARAGRAPH.RIGHT, fill="FFC7CE" if bad else None)
    for i, (lab, key) in enumerate((("Mean", "mean"), ("Median", "median"))):
        row = t.rows[3 + len(ev["rows"]) + i]
        c = row.cells[0].merge(row.cells[1])
        _cell_text(c, lab, bold=True, size=7, align=WD_ALIGN_PARAGRAPH.RIGHT, fill="F2F2F2")
        for x, col in enumerate(cols):
            v = ev["stats"][col["key"]][key]
            txt = "-" if v is None else (f"{round(v)}" if col["kind"] == "count" else f"{round(v)}%")
            _cell_text(row.cells[2 + x], txt, size=7, fill="F2F2F2", align=WD_ALIGN_PARAGRAPH.RIGHT)


def _notes_table(doc: Document, ev: Dict[str, Any]):
    ncols = ev["note_columns"]
    rows = [r for r in ev["rows"] if any(r["keterangan"][c["key"]] for c in NOTE_COLUMNS)]
    t = doc.add_table(rows=1 + max(1, len(rows)), cols=2 + len(ncols))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t)
    for j, h in enumerate(["No", "Bank"] + [c["label"] for c in ncols]):
        _cell_text(t.cell(0, j), h, bold=True, size=8, color="FFFFFF", fill="002060")
    if not rows:
        c = t.cell(1, 0).merge(t.cell(1, 1 + len(ncols)))
        _cell_text(c, "Seluruh Dealer Utama PUVA telah memenuhi 100% kewajiban.", size=8)
        return
    rest = (26.7 - 3.5) / len(ncols)
    _widths(t, [1.0, 2.5] + [rest] * len(ncols))
    for i, r in enumerate(rows, 1):
        _cell_text(t.cell(i, 0), str(i), size=8)
        _cell_text(t.cell(i, 1), r["nama"], size=8, align=WD_ALIGN_PARAGRAPH.LEFT)
        for j, c in enumerate(ncols):
            _cell_text(t.cell(i, 2 + j), "\n".join(r["keterangan"][c["key"]]), size=7, align=WD_ALIGN_PARAGRAPH.LEFT)


def _escalation_table(doc: Document, ev: Dict[str, Any]):
    heads = ["No", "Bank", "Parameter", "Tanggal", "Tenor", "Rekap BI", "Klaim bank", "Ronde", "Keterangan bank",
             "Alasan penolakan sebelumnya", "Keputusan pimpinan"]
    t = doc.add_table(rows=1 + len(ev["eskalasi"]), cols=len(heads))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t)
    for j, h in enumerate(heads):
        _cell_text(t.cell(0, j), h, bold=True, size=7, color="FFFFFF", fill="002060")
    _widths(t, [0.8, 2.0, 3.0, 2.4, 1.8, 2.0, 2.2, 1.3, 5.0, 3.6, 2.6])
    for i, e in enumerate(ev["eskalasi"], 1):
        vals = [str(i), e["bank"], f"{e['parameter']} \u2013 {e['nama_parameter']}",
                tanggal_panjang(date.fromisoformat(e["tanggal"])) if e["tanggal"] else "-", e["tenor"] or "-",
                e["nilai_bi"], e["nilai_bank"], e["ronde"], e["keterangan_bank"][:300], e["alasan_penolakan"],
                "\u2610 Diterima\n\u2610 Ditolak"]
        for j, v in enumerate(vals):
            _cell_text(t.cell(i, j), v, size=7, align=WD_ALIGN_PARAGRAPH.LEFT if j in (1, 2, 8, 9) else WD_ALIGN_PARAGRAPH.CENTER)


def generate_lampiran(ev: Dict[str, Any], memo: str = "m02") -> io.BytesIO:
    doc = _new_document(landscape=True, margins_cm=1.5)
    doc.styles["Normal"].font.size = Pt(10)
    _draft_header(doc, ev)
    roman = "I" if memo == "m02" and ev["eskalasi"] else ""
    for line in ("Hasil Evaluasi Pemenuhan Kewajiban", "Dealer Utama Pasar Uang Dan Pasar Valuta Asing",
                 f"Periode {ev['period']['label']}"):
        _p(doc, line, bold=True, size=12, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    if roman:
        _p(doc, f"Lampiran {roman}", italic=True, size=9, align=WD_ALIGN_PARAGRAPH.CENTER)
    _p(doc, "Hasil evaluasi sebelum penerapan parameter threshold", bold=True, space_after=2)
    _matrix_table(doc, ev, after=False)
    doc.add_page_break()
    _p(doc, f"Hasil evaluasi setelah penerapan parameter threshold ({ev['stage_text']})", bold=True, space_after=2)
    _matrix_table(doc, ev, after=True)
    doc.add_page_break()
    _p(doc, "Keterangan Hasil Evaluasi", bold=True, space_after=2)
    _notes_table(doc, ev)
    _p(doc, "Keterangan: hari/tanggal yang sanggahannya diterima pada proses konfirmasi telah dihitung memenuhi.",
       italic=True, size=8)
    if memo == "m02" and ev["eskalasi"]:
        doc.add_page_break()
        _p(doc, "Lampiran II", italic=True, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
        _p(doc, "Sanggahan Dealer Utama PUVA yang Memerlukan Keputusan Pimpinan", bold=True, size=12,
           align=WD_ALIGN_PARAGRAPH.CENTER)
        _p(doc, "Sanggahan berikut telah ditolak pada ronde konfirmasi sebelumnya dan diajukan kembali oleh bank. "
                "Nilai pada matriks Lampiran I belum memperhitungkan sanggahan ini.", size=9)
        _escalation_table(doc, ev)
    return _stream(doc)


# ==============================================================================
# Memorandum M.02 (ke pimpinan DPPK) dan M.01 (ke DSMM)
# ==============================================================================
def generate_m02(ev: Dict[str, Any]) -> io.BytesIO:
    cfg = doc_config()
    pts = memo_points(ev)
    per = ev["period"]
    doc = _new_document(margins_cm=2.5)
    _draft_header(doc, ev)
    lamp = 2 if ev["eskalasi"] else 1
    _p(doc, f"No. {per['nomor_tahun']}/       /DPPK-GPVA/M.02/B", space_after=0)
    _p(doc, f"Lamp.: {angka(lamp)} set")
    _p(doc, "M E M O R A N D U M", bold=True, size=14, align=WD_ALIGN_PARAGRAPH.CENTER)
    p = _p(doc, "Perihal:\tPERMOHONAN PERSETUJUAN HASIL EVALUASI KEWAJIBAN DEALER UTAMA PASAR UANG DAN PASAR VALUTA "
                f"ASING PERIODE {per['label'].upper()}", bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, indent_cm=2.2,
           first_line_cm=-2.2)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(2.2))
    t = doc.add_table(rows=2, cols=3)
    _no_borders(t)
    kd, kg = cfg["kepala_departemen"], cfg["kepala_grup"]
    for i, (a, b) in enumerate((("Kepada", f"Yth. {kd['nama']}, {kd['jabatan']} Pengembangan Pasar Keuangan"),
                                ("Melalui", f"Yth. {kg['nama']}, {kg['jabatan']}"))):
        _cell_text(t.cell(i, 0), a, size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
        _cell_text(t.cell(i, 1), ":", size=11)
        _cell_text(t.cell(i, 2), b, size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
    for row in t.rows:
        row.cells[0].width, row.cells[1].width, row.cells[2].width = Cm(2.2), Cm(0.5), Cm(13.3)
    _p(doc)

    _numbered(doc, "I.", "TUJUAN", 1.0, bold=True)
    _p(doc, "Memorandum ini bertujuan untuk meminta persetujuan atas hasil evaluasi kewajiban Dealer Utama Pasar Uang dan "
            "Pasar Valuta Asing (Dealer Utama PUVA) di pasar uang periode " + per["label"] + ".",
       align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_cm=1.0)

    _numbered(doc, "II.", "LATAR BELAKANG DAN PENJELASAN", 1.0, bold=True)
    _numbered(doc, "1.", "Dealer Utama PUVA wajib menjadi market maker dan aktif melakukan transaksi Pasar Uang, sebagai berikut:", 1.6)
    _numbered(doc, "a.", "dalam memenuhi kewajiban untuk menjadi market maker, Dealer Utama PUVA menyediakan kuotasi harga untuk "
                         "transaksi di Pasar Uang dengan metode yang ditetapkan oleh BI dan memenuhi kewajiban lain untuk menjadi "
                         "market maker yang ditetapkan oleh BI;", 2.2)
    _numbered(doc, "b.", "dalam memenuhi kewajiban untuk aktif melakukan transaksi Pasar Uang, Dealer Utama PUVA memenuhi besaran "
                         "tertentu dalam transaksi Pasar Uang dan memenuhi kewajiban lain untuk aktif melakukan transaksi Pasar "
                         "Uang yang ditetapkan oleh BI.", 2.2)
    _numbered(doc, "2.", "BI menetapkan ukuran pemenuhan kewajiban Dealer Utama PUVA dan menyampaikan hasil penetapan melalui surat, "
                         "laman BI dan/atau media lain yang ditetapkan oleh BI.", 1.6)
    _numbered(doc, "3.", "Sesuai PADG Intern mengenai tata cara persetujuan, pelaporan, pengawasan, dan evaluasi Dealer Utama PUVA, "
                         "DPPK melakukan evaluasi terhadap pemenuhan kewajiban Dealer Utama PUVA terkait Pasar Uang dan menyampaikan "
                         "memorandum kepada DSMM terkait hasil evaluasi terhadap pemenuhan kewajiban Dealer Utama PUVA.", 1.6)
    _numbered(doc, "4.", pts["hasil"], 1.6)
    for k, line in enumerate(pts["per_bank"]):
        _numbered(doc, f"{chr(97 + k)}.", line, 2.2)
    if pts["konfirmasi"]:
        _numbered(doc, "5.", pts["konfirmasi"], 1.6)

    _numbered(doc, "III.", "ANALISIS RISIKO DAN MITIGASI", 1.0, bold=True)
    _p(doc, "Risiko yang mungkin terjadi adalah tidak akuratnya data hasil evaluasi pemenuhan kewajiban Dealer Utama PUVA di "
            "Pasar Uang. Untuk memitigasi risiko tersebut, telah dilakukan konfirmasi data pemenuhan kewajiban kepada semua "
            "Dealer Utama PUVA.", align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_cm=1.0)

    _numbered(doc, "IV.", "KESIMPULAN DAN TINDAK LANJUT", 1.0, bold=True)
    _numbered(doc, "1.", pts["kesimpulan"], 1.6)
    _numbered(doc, "2.", "Selanjutnya, akan disampaikan memorandum kepada DSMM mengenai hasil evaluasi pemenuhan kewajiban Dealer "
                         "Utama PUVA di Pasar Uang, untuk dapat ditindaklanjuti sesuai kewenangan DSMM.", 1.6)
    if ev["eskalasi"]:
        _numbered(doc, "3.", f"Mohon keputusan atas {angka(len(ev['eskalasi']))} sanggahan Dealer Utama PUVA sebagaimana "
                             "Lampiran II.", 1.6)
    closing = _p(doc, "Demikian, mohon persetujuan dan arahan lebih lanjut. Apabila Bapak/Ibu menyetujui usulan pada poin IV "
                      "di atas, mohon perkenan untuk menandatangani M.01 kepada DSMM sebagaimana terlampir.",
                 align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=12)
    t = doc.add_table(rows=2, cols=2)
    _no_borders(t)
    _signature(t.cell(0, 0), cfg["penyusun"], "Dipersiapkan oleh")
    _signature(t.cell(0, 1), cfg["pemeriksa"], "Diperiksa oleh")
    _signature(t.cell(1, 0), cfg["kepala_grup"], "Didukung oleh")
    _signature(t.cell(1, 1), cfg["kepala_departemen"], "Disetujui oleh")
    for cell in t.rows[1].cells:
        cell.paragraphs[0].paragraph_format.space_before = Pt(18)
    _keep_together(t)
    closing.paragraph_format.keep_with_next = True
    return _stream(doc)


def generate_m01(ev: Dict[str, Any]) -> io.BytesIO:
    cfg = doc_config()
    per = ev["period"]
    doc = _new_document(margins_cm=3.0)
    _draft_header(doc, ev)
    _p(doc, f"No. {per['nomor_tahun']}/          /DPPK/M.01/B", space_after=0)
    _p(doc, f"Lamp.: {angka(1)} set")
    _p(doc, "M E M O R A N D U M", bold=True, size=14, align=WD_ALIGN_PARAGRAPH.CENTER)
    for a, b in (("Kepada", "Departemen Surveilans Makroprudensial Moneter & Market"),
                 ("Dari", "Departemen Pengembangan Pasar Keuangan"),
                 ("Perihal", "Evaluasi Pemenuhan Kewajiban Dealer Utama Pasar Uang dan Pasar Valuta Asing (Dealer Utama PUVA) "
                             f"Periode {per['label']}")):
        p = _p(doc, f"{a}\t:\t{b}", indent_cm=3.0, first_line_cm=-3.0, align=WD_ALIGN_PARAGRAPH.LEFT)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(2.5))
        p.paragraph_format.tab_stops.add_tab_stop(Cm(3.0))
    _p(doc)
    body = [
        "Merujuk ketentuan PADG Intern mengenai Tata Cara Persetujuan, Pelaporan, Pengawasan, dan Evaluasi Dealer Utama Pasar "
        "Uang dan Pasar Valuta Asing, DPPK memiliki kewenangan untuk melakukan evaluasi terhadap pemenuhan kewajiban Dealer "
        "Utama PUVA terkait aktivitas di Pasar Uang. Sejalan dengan ketentuan tersebut, DPPK telah melaksanakan evaluasi "
        f"pemenuhan kewajiban DU PUVA untuk periode {per['label']}, termasuk melakukan konfirmasi kepada masing-masing DU PUVA "
        "guna mendukung kelengkapan dan akurasi hasil evaluasi.",
        "Selanjutnya, ukuran pemenuhan kewajiban, threshold, dan bobot yang berlaku mengacu pada Lampiran I PADG Intern "
        f"dimaksud. Adapun penerapan threshold pada periode evaluasi dimaksud menggunakan tahapan {ev['stage_text']}.",
        memo_points(ev)["kesimpulan"],
        f"Sehubungan dengan hal tersebut, bersama ini kami sampaikan hasil evaluasi pemenuhan kewajiban Dealer Utama PUVA "
        f"periode {per['label']} sebagaimana terlampir, untuk dapat ditindaklanjuti sesuai dengan kewenangan Saudara.",
        "Demikian kami sampaikan, terima kasih atas perhatian dan kerja sama Saudara.",
    ]
    for text in body:
        _p(doc, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_cm=1.0)
    _p(doc)
    kd = cfg["kepala_departemen"]
    bulan_ttd = BULAN[datetime.now().month]
    for line, bold in ((f"Jakarta,      {bulan_ttd} {datetime.now().year}", False), (kd["jabatan"], False), ("", False),
                       ("", False), ("", False), (kd["nama"], True), (kd["pangkat"], False)):
        _p(doc, line, bold=bold, indent_cm=9.0, space_after=0)
    return _stream(doc)


# ==============================================================================
# Surat informasi pemenuhan kewajiban (pengantar workbook konfirmasi ke bank)
# ==============================================================================
def generate_surat(ev: Dict[str, Any], db: Session, period: EvaluationPeriod) -> io.BytesIO:
    cfg = doc_config()
    per = ev["period"]
    rnd = (db.query(ConfirmationRound).filter(ConfirmationRound.period_id == period.id)
           .order_by(ConfirmationRound.Round_No.desc()).first())
    hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    if rnd and rnd.Deadline:
        dl = rnd.Deadline if isinstance(rnd.Deadline, date) else date.fromisoformat(str(rnd.Deadline)[:10])
        tenggat = f"{hari[dl.weekday()]}, {tanggal_panjang(dl)}"
    else:
        tenggat = "[tanggal tenggat]"
    akhir = date.fromisoformat(per["akhir"])
    doc = _new_document(margins_cm=2.5)
    _draft_header(doc, ev)
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    _cell_text(t.cell(0, 0), f"No. {per['nomor_tahun']}/        /DPPK/Srt/B", size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
    _cell_text(t.cell(0, 1), f"Jakarta,       {BULAN[datetime.now().month]} {datetime.now().year}", size=11,
               align=WD_ALIGN_PARAGRAPH.RIGHT)
    _p(doc)
    for line in ("Kepada Yth.", "Direktur yang Membawahkan Bidang Tresuri", "*)", "di Tempat"):
        _p(doc, line, space_after=0)
    _p(doc)
    p = _p(doc, f"Perihal:\tInformasi Data Pemenuhan Kewajiban Dealer Utama PUVA Periode {per['label']}", bold=True)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(2.0))
    _p(doc)
    for text in (
        "Sehubungan dengan implementasi kewajiban Dealer Utama Pasar Uang dan Pasar Valuta Asing (Dealer Utama PUVA), Bank "
        "Indonesia melakukan evaluasi pemenuhan kewajiban Dealer Utama PUVA secara triwulanan sebagaimana diatur dalam PADG "
        "Dealer Utama PUVA. Dealer Utama PUVA berkewajiban antara lain untuk berperan sebagai market maker dan aktif melakukan "
        "transaksi di Pasar Uang. Adapun ukuran pemenuhan kewajiban dimaksud diinformasikan melalui laman Bank Indonesia. "
        "Sehubungan dengan hal tersebut, bersama ini kami sampaikan hasil monitoring pemenuhan kewajiban Bank Saudara sebagai "
        f"Dealer Utama PUVA untuk periode {per['label_sd']}.",
        "Selanjutnya, kami mengharapkan Saudara dapat melakukan verifikasi terhadap data dimaksud dengan data internal Bank "
        "Saudara serta melakukan pengkinian data counterparty line repo dan OIS pada posisi "
        f"{tanggal_panjang(akhir)} sebagai dasar pemenuhan kewajiban dimaksud. Konfirmasi pemenuhan kewajiban tersebut agar "
        f"disampaikan melalui email ke {cfg['email_konfirmasi']} dengan format subject email [Internal Assessment_"
        f"{BULAN_PENDEK[akhir.month - 2]}{BULAN_PENDEK[akhir.month]}{akhir.year}_Nama Bank Saudara], disertai bukti "
        f"pendukungnya selambat-lambatnya pada {tenggat}.",
        "Demikian kami sampaikan. Atas perhatian dan kerja sama Saudara kami ucapkan terima kasih.",
    ):
        _p(doc, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_cm=1.0)
    _p(doc)
    kd = cfg["kepala_departemen"]
    for line, bold in (("KEPALA DEPARTEMEN", True), ("PENGEMBANGAN PASAR KEUANGAN", True), ("", False), ("", False),
                       ("", False), (kd["nama"], True), (kd["pangkat"], False)):
        _p(doc, line, bold=bold, indent_cm=8.5, space_after=0, align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()
    _p(doc, f"Lampiran Surat No. {per['nomor_tahun']}/        /DPPK/Srt/B", bold=True)
    _p(doc, "*) Daftar penerima:", size=10)
    rows = [r for r in ev["rows"]]
    rows.sort(key=lambda r: r["nama_resmi"] or "")
    t = doc.add_table(rows=1 + len(rows), cols=2)
    _borders(t)
    _cell_text(t.cell(0, 0), "No.", bold=True, size=10, fill="D9D9D9")
    _cell_text(t.cell(0, 1), "Nama Bank", bold=True, size=10, fill="D9D9D9")
    for i, r in enumerate(rows, 1):
        _cell_text(t.cell(i, 0), str(i), size=10)
        _cell_text(t.cell(i, 1), r["nama_resmi"] or r["nama"], size=10, align=WD_ALIGN_PARAGRAPH.LEFT)
    return _stream(doc)


# ==============================================================================
# Matriks Excel
# ==============================================================================
def generate_matrix_xlsx(ev: Dict[str, Any]) -> io.BytesIO:
    wb = Workbook()
    thin = Side(style="thin", color="A6A6A6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    red = PatternFill("solid", fgColor="FFC7CE")

    def sheet(ws, after: bool):
        cols = ev["columns"]
        ws.cell(1, 3, f"Periode {ev['period']['label_pendek']}" + (f" \u2013 setelah threshold ({ev['stage_text']})" if after else
                                                                     " \u2013 sebelum threshold"))
        ws.merge_cells(start_row=1, start_column=3, end_row=1, end_column=2 + len(cols))
        ws.cell(1, 3).font, ws.cell(1, 3).fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="000000")
        ws.cell(1, 3).alignment = center
        for j, h in ((1, "No"), (2, "Bank DU PUVA")):
            ws.cell(2, j, h)
            ws.merge_cells(start_row=2, start_column=j, end_row=3, end_column=j)
        for j, c in enumerate(cols, 3):
            ws.cell(2, j, c["group"])
            ws.cell(3, j, f"{c['label']} ({c['label_after' if after else 'label_before']})".strip())
        j = 3
        while j < 3 + len(cols):
            k = j
            while k + 1 < 3 + len(cols) and cols[k + 1 - 3]["group"] == cols[j - 3]["group"]:
                k += 1
            if k > j:
                ws.merge_cells(start_row=2, start_column=j, end_row=2, end_column=k)
            j = k + 1
        for r in (2, 3):
            for j in range(1, 3 + len(cols)):
                cell = ws.cell(r, j)
                g = cols[j - 3]["group"] if j >= 3 else None
                cell.fill = PatternFill("solid", fgColor=GROUP_COLOR.get(g, "002060"))
                cell.font = Font(bold=True, color=GROUP_FONT.get(g, "FFFFFF"), size=9)
                cell.alignment, cell.border = center, border
        flag = "gagal_setelah" if after else "gagal_sebelum"
        for i, row in enumerate(ev["rows"], 4):
            ws.cell(i, 1, row["no"]).border = border
            nb = ws.cell(i, 2, row["nama"])
            nb.border = border
            if any(row[flag].values()):
                nb.fill = red
            for j, c in enumerate(cols, 3):
                v = row["cells"][c["key"]]
                cell = ws.cell(i, j, None if v is None else (v if c["kind"] == "count" else v / 100.0))
                cell.number_format = "0" if c["kind"] == "count" else "0%"
                cell.border = border
                if row[flag][c["key"]]:
                    cell.fill, cell.font = red, Font(color="C00000")
        end = 3 + len(ev["rows"])
        for k, (lab, key) in enumerate((("Mean", "mean"), ("Median", "median")), 1):
            ws.cell(end + k, 2, lab).font = Font(bold=True)
            for j, c in enumerate(cols, 3):
                v = ev["stats"][c["key"]][key]
                cell = ws.cell(end + k, j, None if v is None else (v if c["kind"] == "count" else v / 100.0))
                cell.number_format = "0" if c["kind"] == "count" else "0%"
                cell.fill = PatternFill("solid", fgColor="F2F2F2")
        ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 5, 14
        for j in range(3, 3 + len(cols)):
            ws.column_dimensions[get_column_letter(j)].width = 11
        ws.row_dimensions[3].height = 42
        ws.freeze_panes = "C4"

    ws = wb.active
    ws.title = "Sebelum Threshold"
    sheet(ws, False)
    sheet(wb.create_sheet("Setelah Threshold"), True)

    ws = wb.create_sheet("Keterangan")
    ncols = ev["note_columns"]
    for j, h in enumerate(["No", "Bank"] + [c["label"] for c in ncols], 1):
        c = ws.cell(1, j, h)
        c.font, c.fill, c.alignment, c.border = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="002060"), center, border
        ws.column_dimensions[get_column_letter(j)].width = 6 if j == 1 else 14 if j == 2 else 42
    i = 1
    for row in ev["rows"]:
        if not any(row["keterangan"][c["key"]] for c in NOTE_COLUMNS):
            continue
        i += 1
        ws.cell(i, 1, i - 1).border = border
        ws.cell(i, 2, row["nama"]).border = border
        for j, c in enumerate(ncols, 3):
            cell = ws.cell(i, j, "\n".join(row["keterangan"][c["key"]]))
            cell.alignment, cell.border = Alignment(wrap_text=True, vertical="top"), border

    if ev["eskalasi"]:
        ws = wb.create_sheet("Eskalasi Pimpinan")
        heads = ["No", "Bank", "Parameter", "Tanggal", "Tenor", "Rekap BI", "Klaim bank", "Ronde", "Keterangan bank",
                 "Alasan penolakan sebelumnya"]
        for j, h in enumerate(heads, 1):
            c = ws.cell(1, j, h)
            c.font, c.fill, c.border = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="002060"), border
        for i, e in enumerate(ev["eskalasi"], 2):
            for j, v in enumerate([i - 1, e["bank"], e["parameter"], e["tanggal"], e["tenor"], e["nilai_bi"], e["nilai_bank"],
                                   e["ronde"], e["keterangan_bank"], e["alasan_penolakan"]], 1):
                ws.cell(i, j, v).border = border
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ==============================================================================
# Paket dokumen
# ==============================================================================
DOC_KINDS = {
    "m02": ("M.02_Permohonan Persetujuan Hasil Evaluasi Kewajiban Dealer Utama Periode {p}.docx", "docx"),
    "m02-lampiran": ("M.02_Lampiran Memo Evaluasi DU {p}.docx", "docx"),
    "m01": ("M.01 DSMM_Evaluasi Kewajiban DU {p}.docx", "docx"),
    "m01-lampiran": ("M.01_Lampiran Memo Evaluasi DU {p}.docx", "docx"),
    "surat": ("Surat Informasi Pemenuhan Kewajiban PD Periode {p}.docx", "docx"),
    "matriks": ("Matriks Hasil Evaluasi DU {p}.xlsx", "xlsx"),
}
MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "zip": "application/zip"}


def file_name(kind: str, ev: Dict[str, Any]) -> str:
    p = ev["period"]["label_pendek"].replace(" - ", "-")
    if kind == "paket":
        return f"Paket Dokumen Evaluasi DU {p}.zip"
    return DOC_KINDS[kind][0].format(p=p)


def generate(kind: str, ev: Dict[str, Any], db: Session, period: EvaluationPeriod) -> Tuple[io.BytesIO, str, str]:
    """(stream, nama file, media type) untuk satu jenis dokumen atau paket zip semuanya."""
    if kind == "paket":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for k in DOC_KINDS:
                s, name, _ = generate(k, ev, db, period)
                z.writestr(name, s.getvalue())
        buf.seek(0)
        return buf, file_name(kind, ev), MEDIA["zip"]
    builders = {
        "m02": lambda: generate_m02(ev),
        "m02-lampiran": lambda: generate_lampiran(ev, "m02"),
        "m01": lambda: generate_m01(ev),
        "m01-lampiran": lambda: generate_lampiran(ev, "m01"),
        "surat": lambda: generate_surat(ev, db, period),
        "matriks": lambda: generate_matrix_xlsx(ev),
    }
    if kind not in builders:
        raise KeyError(kind)
    return builders[kind](), file_name(kind, ev), MEDIA[DOC_KINDS[kind][1]]
