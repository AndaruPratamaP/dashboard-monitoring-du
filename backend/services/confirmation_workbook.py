"""
Generator workbook konfirmasi per bank (E5-1), mengikuti template DPPK yang dikirim ke bank DU:

  1. Rasio SRBI Minimal 30%          (B6)  penjualan sekunder harian + win perdana
  2. Transaksi Repo Minimal 2 Minggu (B7a) volume harian + status 1/0
  3. Transaksi SRBI 3 Bulan          (B7b) volume harian + status 1/0
  4. Partisipasi MM OIS              (B8)  Ya/Tidak tenor 1b & 3b per sesi
  5. Kuotasi SRBI, Repo & OIS        (B1-B3) spread harian per tenor ('-' = tidak ada kuotasi)
  6. Counterparty Line Repo          (B4) daftar counterparty + pilihan status
  7. Counterparty Line OIS           (B5)
  +  Index (tersembunyi)             daftar "sandi - nama bank" untuk dropdown counterparty

Seluruh angka diambil dari data yang sudah di-ingest (SourceDataset & CounterpartyLine) pada periode tsb.
Kolom Keterangan/Status dibiarkan kosong untuk diisi bank.
"""

import datetime as dt
import io
import json
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.orm import Session

from models import BankDirectory, CounterpartyLine, EvaluationPeriod, MasterBank, SourceDataset
from services.counterparty import is_deleted
from services.real_ingest import QUOTE_SOURCES

NAVY = PatternFill("solid", fgColor="002060")
NOTE_FILL = PatternFill("solid", fgColor="FFF2CC")
WHITE_BOLD = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)
ITALIC = Font(italic=True, color="595959")
THIN = Side(style="thin", color="808080")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def confirmation_file_name(bank: MasterBank) -> str:
    no = bank.No_Urut_Konfirmasi or 0
    return f"{no:02d}. {bank.Nama_Singkat or bank.Nama_Resmi_Bank}.xlsx"


def cutoff_label(period: EvaluationPeriod) -> str:
    """Batas pembukaan line = akhir triwulan sebelumnya, mis. TW III 2026 -> '30 Jun 2026'."""
    try:
        year, q = int(period.Triwulan[:4]), int(period.Triwulan[-1])
    except (TypeError, ValueError):
        return "akhir triwulan sebelumnya"
    first_month = 3 * (q - 1) + 1
    end = dt.date(year, first_month, 1) - dt.timedelta(days=1)
    return f"{end.day} {MONTHS_ID[end.month - 1]} {end.year}"


def _payload(db: Session, period_id: int, source: str, bank_id: str) -> Optional[Dict[str, Any]]:
    row = db.query(SourceDataset).filter(
        SourceDataset.period_id == period_id, SourceDataset.Source == source, SourceDataset.Bank_ID == bank_id
    ).first()
    return json.loads(row.Payload_JSON) if row else None


def _header(ws, row: int, col: int, labels: List[str]) -> None:
    for i, label in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=label)
        c.fill, c.font, c.border, c.alignment = NAVY, WHITE_BOLD, BOX, CENTER


def _boxed(ws, row: int, col: int, value: Any, fmt: Optional[str] = None, bold: bool = False):
    c = ws.cell(row=row, column=col, value=value)
    c.border = BOX
    if fmt:
        c.number_format = fmt
    if bold:
        c.font = BOLD
    return c


def _missing(ws, cell: str, what: str) -> None:
    ws[cell] = f"Data {what} belum diunggah untuk periode ini."
    ws[cell].font = ITALIC


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _bank_label(db: Session, bank: MasterBank) -> str:
    sandi = (bank.Sandi_BI or "").zfill(3)
    entry = db.get(BankDirectory, sandi) if sandi else None
    return entry.Nama if entry else f"{sandi} - {bank.Nama_Resmi_Bank}"


# ------------------------------------------------------------------------------------------------
def _sheet_rasio_srbi(ws, data):
    ws["C1"] = "*Nominal Dalam Miliar Rupiah"
    ws["C1"].font = ITALIC
    _header(ws, 2, 1, ["No.", "Date", "Pasar Sekunder Jual", "Pasar Perdana", "% Pasar Sekunder Jual vs Pasar Perdana", "Keterangan"])
    if not data:
        return _missing(ws, "A3", "rasio SRBI sekunder-primer")
    first = 3
    for i, (d, v) in enumerate(zip(data["dates"], data["sekunder"])):
        r = first + i
        _boxed(ws, r, 1, i + 1)
        _boxed(ws, r, 2, _date(d), "dd-mmm-yy")
        _boxed(ws, r, 3, v, "#,##0.000")
    last = first + len(data["dates"]) - 1
    t = last + 1
    _boxed(ws, t, 2, "Total", bold=True)
    _boxed(ws, t, 3, f"=SUM(C{first}:C{last})", "#,##0.000", bold=True)
    _boxed(ws, t, 4, data["perdana"], "#,##0.000", bold=True)
    _boxed(ws, t, 5, f'=IF(D{t}>0,C{t}/D{t},"-")', "0.00%", bold=True)
    _boxed(ws, t, 6, f'=IF(D{t}=0,"Memenuhi",IF(E{t}>=30%,"Memenuhi","Tidak Memenuhi"))', bold=True)
    for col, w in zip("ABCDEF", (5, 11, 22, 22, 34, 18)):
        ws.column_dimensions[col].width = w


def _sheet_volume(ws, data, bank_label: str, unit_note: Optional[str], top: int, instrumen: str):
    """Sheet transaksi harian (Repo 2m / SRBI 3b): Jumlah Hari | Tanggal | Volume | Status | Keterangan."""
    if unit_note:
        ws["C1"] = unit_note
        ws["C1"].font = ITALIC
    ws.cell(row=top - 1, column=3, value=bank_label).font = BOLD
    ws.cell(row=top - 1, column=7, value="sesuai/tidak sesuai").font = ITALIC
    _header(ws, top, 3, ["Jumlah Hari", "Tanggal", "Volume", "Status", "Keterangan"])
    if not data:
        return _missing(ws, f"C{top + 1}", instrumen)
    first = top + 1
    for i, (d, v) in enumerate(zip(data["dates"], data["volume"])):
        r = first + i
        _boxed(ws, r, 3, i + 1)
        _boxed(ws, r, 4, _date(d), "dd-mmm-yy")
        _boxed(ws, r, 5, v, "#,##0")
        _boxed(ws, r, 6, f"=IF(E{r}>0,1,0)")
        _boxed(ws, r, 7, None).fill = NOTE_FILL
    last = first + len(data["dates"]) - 1
    _boxed(ws, last + 1, 5, "Total Frekuensi", bold=True)
    _boxed(ws, last + 1, 6, f"=SUM(F{first}:F{last})", bold=True)
    _boxed(ws, last + 2, 5, "Persentase pemenuhan", bold=True)
    _boxed(ws, last + 2, 6, f"=F{last + 1}/COUNT(C{first}:C{last})", "0.00%", bold=True)
    _boxed(ws, last + 2, 7, f'=IF(F{last + 2}>=60%,"Memenuhi","Tidak Memenuhi")', bold=True)
    ws.cell(row=first, column=9, value="Keterangan :").font = BOLD
    ws.cell(row=first + 1, column=9, value="0 = tidak ada transaksi")
    ws.cell(row=first + 2, column=9, value="1 = ada transaksi")
    for col, w in zip("CDEFGI", (11, 13, 20, 9, 22, 24)):
        ws.column_dimensions[col].width = w


def _sheet_mm_ois(ws, data, bank_label: str):
    ws["C2"] = bank_label
    ws["C2"].font = BOLD
    ws["G2"] = "sesuai/tidak sesuai"
    ws["G2"].font = ITALIC
    ws.merge_cells("E3:F3")
    _header(ws, 3, 5, ["Status"])
    _header(ws, 4, 3, ["Jumlah Hari", "Tanggal", "1b", "3b", "Keterangan"])
    if not data:
        return _missing(ws, "C5", "matchmaking OIS")
    first = 5
    for i, (d, f1, f3) in enumerate(zip(data["sessions"], data["1b"], data["3b"])):
        r = first + i
        _boxed(ws, r, 3, i + 1)
        _boxed(ws, r, 4, _date(d), "dd-mmm-yy")
        _boxed(ws, r, 5, f1).alignment = CENTER
        _boxed(ws, r, 6, f3).alignment = CENTER
        _boxed(ws, r, 7, None).fill = NOTE_FILL
    last = first + len(data["sessions"]) - 1
    t = last + 1
    _boxed(ws, t, 4, "Jumlah Ya", bold=True)
    _boxed(ws, t, 5, f'=COUNTIF(E{first}:E{last},"Ya")', bold=True)
    _boxed(ws, t, 6, f'=COUNTIF(F{first}:F{last},"Ya")', bold=True)
    _boxed(ws, t + 1, 4, "Persentase", bold=True)
    _boxed(ws, t + 1, 5, f"=E{t}/COUNT(C{first}:C{last})", "0.00%", bold=True)
    _boxed(ws, t + 1, 6, f"=F{t}/COUNT(C{first}:C{last})", "0.00%", bold=True)
    _boxed(ws, t + 1, 7, f'=IF(AND(E{t + 1}=100%,F{t + 1}=100%),"Memenuhi","Tidak Memenuhi")', bold=True)
    ws.cell(row=first, column=9, value="Keterangan :").font = BOLD
    ws.cell(row=first + 1, column=9, value="Tidak = tidak berpartisipasi dalam MM OIS")
    ws.cell(row=first + 2, column=9, value="Ya = berpartisipasi dalam MM OIS")
    for col, w in zip("CDEFGI", (11, 13, 9, 9, 22, 38)):
        ws.column_dimensions[col].width = w


def _sheet_kuotasi(ws, payloads: Dict[str, Optional[Dict[str, Any]]]):
    """Spread harian per tenor; kolom mengikuti template: Repo on/1m/1b, SRBI Any, OIS 3b/12b."""
    columns = []  # (source, tenor_key, label, max_bps)
    labels = {"on": "on", "1w": "1m", "1m": "1b", "any": "Any", "3b": "3b", "12b": "12b"}
    for source in ("bbg-repo", "bbg-srbi", "bbg-ois"):
        for t in QUOTE_SOURCES[source]["tenors"]:
            columns.append((source, t["key"], labels[t["key"]], t["max_bps"]))
    groups = [("Repo", 3, 5), ("SRBI", 6, 6), ("OIS", 7, 8)]
    for name, c0, c1 in groups:
        if c1 > c0:
            ws.merge_cells(start_row=1, start_column=c0, end_row=1, end_column=c1)
        _header(ws, 1, c0, [name])
    _header(ws, 2, 1, ["Months", "Dates"] + [c[2] for c in columns] + ["Keterangan"])
    dates = next((p["dates"] for p in payloads.values() if p), None)
    if not dates:
        return _missing(ws, "A3", "kuotasi Bloomberg")
    first = 3
    for i, d in enumerate(dates):
        r = first + i
        day = _date(d)
        _boxed(ws, r, 1, f"{MONTHS_ID[day.month - 1]}-{str(day.year)[2:]}")
        _boxed(ws, r, 2, day, "dd-mmm-yy")
        for j, (source, key, _, _) in enumerate(columns):
            p = payloads.get(source)
            v = p.get(key, [None] * len(dates))[i] if p else None
            _boxed(ws, r, 3 + j, round(v, 2) if v is not None else "-").alignment = CENTER
        _boxed(ws, r, 3 + len(columns), None).fill = NOTE_FILL
    last = first + len(dates) - 1
    t = last + 1
    _boxed(ws, t, 2, f"=COUNT(B{first}:B{last})", bold=True)
    for j, (_, _, _, max_bps) in enumerate(columns):
        col = get_column_letter(3 + j)
        _boxed(ws, t, 3 + j, f'=COUNTIF({col}{first}:{col}{last},"<={max_bps:g}")', bold=True)
        _boxed(ws, t + 1, 3 + j, f"={col}{t}/$B${t}", "0.00%", bold=True)
    ws.cell(row=t + 3, column=1, value="Batas spread: Repo O/N maks. 5 bps; tenor lain & SRBI/OIS maks. 20 bps (batas Repo 1 minggu masih dikonfirmasi). '-' = tidak ada kuotasi dua sisi.").font = ITALIC
    ws.freeze_panes = "C3"
    for col, w in zip("ABCDEFGHI", (9, 11, 8, 8, 8, 8, 8, 8, 28)):
        ws.column_dimensions[col].width = w


def _sheet_counterparty(ws, lines: List[CounterpartyLine], bank_label: str, cutoff: str, index_rows: int):
    _header(ws, 1, 1, ["No.", "Bank Responden", "Nama Counterpart", "Periode Pembukaan Limit"])
    ws["F1"] = "Mohon lakukan pengkinian counterparty dan periode pembukaan limit dengan memilih:"
    ws["F1"].font = BOLD
    options = [f"Sebelum {cutoff}", f"Setelah {cutoff}", "Dihapus"]
    ws["F2"] = f"1. {options[0]}"
    ws["F3"] = f"2. {options[1]} (untuk counterpart baru)"
    ws["F4"] = "3. Dihapus"
    ws["B3"], ws["C3"] = "Contoh", "011 - PT. BANK DANAMON INDONESIA, TBK"
    ws["B4"], ws["C4"], ws["D4"] = "Otomatis", "Silahkan Pilih", "Silahkan Pilih"
    for c in ("B3", "C3", "B4", "C4", "D4"):
        ws[c].font = ITALIC
    active = [l for l in lines if not is_deleted(l.Status)]
    total_rows = max(len(active) + 20, 23)
    for i in range(total_rows):
        r = 5 + i
        _boxed(ws, r, 1, i + 1)
        _boxed(ws, r, 2, bank_label if i < len(active) else None)
        _boxed(ws, r, 3, active[i].Counterparty_Nama if i < len(active) else None)
        _boxed(ws, r, 4, None).fill = NOTE_FILL
    last = 4 + total_rows
    dv_status = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
    dv_status.add(f"D5:D{last}")
    ws.add_data_validation(dv_status)
    if index_rows:
        dv_cp = DataValidation(type="list", formula1=f"=Index!$A$2:$A${index_rows + 1}", allow_blank=True)
        dv_cp.add(f"C5:C{last}")
        ws.add_data_validation(dv_cp)
    for col, w in zip("ABCDEF", (6, 36, 46, 26, 3, 60)):
        ws.column_dimensions[col].width = w


def build_confirmation_workbook(db: Session, period: EvaluationPeriod, bank: MasterBank) -> io.BytesIO:
    label = _bank_label(db, bank)
    bank_name = label.split(" - ", 1)[-1]
    get = lambda source: _payload(db, period.id, source, bank.Bank_ID)

    wb = Workbook()
    ws = wb.active
    ws.title = "Rasio SRBI Minimal 30%"
    _sheet_rasio_srbi(ws, get("srbi-ratio"))
    _sheet_volume(wb.create_sheet("Transaksi Repo Minimal 2 Minggu"), get("repo-2m"), bank_name, None, 4,
                  "transaksi Repo >= 2 minggu")
    _sheet_volume(wb.create_sheet("Transaksi SRBI 3 Bulan"), get("srbi-3b"), bank_name, "*Nominal Dalam Juta Rupiah", 3,
                  "transaksi SRBI sisa >= 3 bulan")
    _sheet_mm_ois(wb.create_sheet("Partisipasi MM OIS"), get("mm-ois"), bank_name)
    _sheet_kuotasi(wb.create_sheet("Kuotasi SRBI, Repo & OIS"), {s: get(s) for s in ("bbg-repo", "bbg-srbi", "bbg-ois")})

    directory = db.query(BankDirectory).order_by(BankDirectory.Sandi).all()
    if not directory:  # belum ada sheet Index yang diimpor: pakai master DU
        directory = [BankDirectory(Sandi=(b.Sandi_BI or "").zfill(3), Nama=f"{(b.Sandi_BI or '').zfill(3)} - {b.Nama_Resmi_Bank}")
                     for b in db.query(MasterBank).order_by(MasterBank.Sandi_BI).all() if b.Sandi_BI]
    cutoff = cutoff_label(period)
    for inst, title in (("REPO", "Counterparty Line Repo"), ("OIS", "Counterparty Line OIS")):
        lines = db.query(CounterpartyLine).filter(
            CounterpartyLine.period_id == period.id, CounterpartyLine.Bank_ID == bank.Bank_ID,
            CounterpartyLine.Instrument == inst,
        ).order_by(CounterpartyLine.id).all()
        _sheet_counterparty(wb.create_sheet(title), lines, label, cutoff, len(directory))

    idx = wb.create_sheet("Index")
    idx["A1"] = "Nama dan Sandi"
    for i, entry in enumerate(directory, start=2):
        idx.cell(row=i, column=1, value=entry.Nama)
    idx.sheet_state = "hidden"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
