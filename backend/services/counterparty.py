"""
Counterparty line Repo (B4) & OIS (B5).

Sumber data: sheet `Counterparty Line Repo` / `Counterparty Line OIS` pada workbook konfirmasi BI.
- Workbook kiriman BI (folder `Konfirmasi Bank`) = daftar counterparty yang tercatat di BI (titik awal).
- Workbook balasan bank (folder `[Confirmed] ...`) = daftar yang sudah diperbarui bank; kolom
  "Periode Pembukaan Limit" berisi `Sebelum <cut-off>`, `Setelah <cut-off>` (counterparty baru), atau `Dihapus`.

Aturan hitung (PADG, kondisi pada akhir periode):
- Line dengan status `Dihapus` tidak dihitung; `Sebelum` dan `Setelah` cut-off sama-sama dihitung.
  Line `Setelah` cut-off (dibuka di tengah periode) ditandai terpisah agar terlihat bedanya.
- Counterparty dibedakan DU / non-DU berdasarkan sandi bank pada master 21 Dealer Utama (bank sendiri diabaikan).
- B4 = min(DU/10, 1) x 50% + min(non-DU/10, 1) x 50%;  B5 = min(DU/10, 1) x 100%.
"""

import glob
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import openpyxl
from sqlalchemy.orm import Session

from models import BankDirectory, CounterpartyLine, MasterBank
from services.entity_resolution import EntityResolver

MIN_LINES = 10
INSTRUMENTS = {"REPO": "counterparty line repo", "OIS": "counterparty line ois"}
_SANDI_RE = re.compile(r"^\s*(\d{1,3})\s*-\s*(.*)$")


def _sandi_of(value: Any) -> Optional[Tuple[str, str]]:
    m = _SANDI_RE.match(str(value or ""))
    if not m:
        return None
    return m.group(1).zfill(3), str(value).strip()


def is_deleted(status: Optional[str]) -> bool:
    return "hapus" in str(status or "").lower()


def is_after_cutoff(status: Optional[str]) -> bool:
    """Line baru yang dibuka setelah tanggal cut-off: tetap dihitung, tetapi diberi tanda."""
    return "setelah" in str(status or "").lower()


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _read_sheets_fast(file_obj, wanted, max_col: int = 4) -> Dict[str, List[List[Any]]]:
    """
    Baca nilai sel (kolom 1..max_col) dari sheet terpilih langsung dari XML di dalam .xlsx.
    openpyxl butuh ~2 detik per workbook konfirmasi hanya untuk membuka file (style & 8 sheet);
    di sini hanya sharedStrings + sheet yang diperlukan yang diurai.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(file_obj) as z:
        names = set(z.namelist())
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        out: Dict[str, List[List[Any]]] = {}
        for sh in wb_xml.find("m:sheets", _NS):
            title = sh.get("name")
            if not wanted(title):
                continue
            target = targets.get(sh.get(_REL_NS), "")
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rows: List[List[Any]] = []
            for row in ET.fromstring(z.read(path)).iter(f"{{{_NS['m']}}}row"):
                vals: List[Any] = [None] * max_col
                for c in row.findall("m:c", _NS):
                    idx = _col_index(c.get("r", "A"))
                    if idx >= max_col:
                        continue
                    t = c.get("t")
                    if t == "inlineStr":
                        v = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
                    else:
                        node = c.find("m:v", _NS)
                        v = node.text if node is not None else None
                        if v is not None and t == "s":
                            v = shared[int(v)]
                    vals[idx] = v
                rows.append(vals)
            out[title] = rows
    return out


def _sheet_instrument(name: str) -> Optional[str]:
    # Nama sheet bervariasi: "Counterparty Line Repo", "Counterparty Repo", ...
    low = name.strip().lower()
    return next((k for k in INSTRUMENTS if "counterparty" in low and k.lower() in low.split()), None)


def read_cp_workbook(file_obj, resolver: EntityResolver) -> Dict[str, Any]:
    """
    Baca satu workbook konfirmasi/balasan. Mengembalikan bank pemilik, daftar line per instrumen,
    dan isi sheet Index (direktori bank) bila ada. Melempar ValueError bila file tidak bisa dibuka.
    """
    wanted = lambda n: _sheet_instrument(n) is not None or n.strip().lower() == "index"
    try:
        sheets = _read_sheets_fast(file_obj, wanted)
    except Exception:
        try:  # cadangan: openpyxl (lebih lambat, lebih toleran)
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)
            wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
            sheets = {n: [list(r) for r in wb[n].iter_rows(max_col=4, values_only=True)] for n in wb.sheetnames if wanted(n)}
            wb.close()
        except Exception as e:
            raise ValueError(f"tidak dapat dibuka ({e.__class__.__name__}); kemungkinan ber-password atau bukan .xlsx")

    lines: Dict[str, List[Dict[str, Any]]] = {}
    owner: Optional[MasterBank] = None
    directory: Dict[str, str] = {}
    for name, rows in sheets.items():
        inst = _sheet_instrument(name)
        if inst is None:
            for r in rows:
                s = _sandi_of(r[0])
                if s:
                    directory.setdefault(s[0], s[1])
            continue
        found, seen = [], set()
        for r in rows:
            if len(r) < 3 or str(r[1] or "").strip().lower() in ("contoh", "otomatis"):
                continue
            cp = _sandi_of(r[2])
            if cp is None:
                continue
            if owner is None and r[1]:
                owner = resolver.resolve(r[1])
            if cp[0] in seen:
                continue  # duplikat counterparty pada sheet yang sama
            seen.add(cp[0])
            status = str(r[3]).strip() if len(r) > 3 and r[3] not in (None, "") else None
            found.append({"sandi": cp[0], "nama": cp[1], "status": status})
            directory.setdefault(cp[0], cp[1])
        if found:
            lines[inst] = found
    return {"bank": owner, "lines": lines, "directory": directory,
            "confirmed": any(l["status"] for ls in lines.values() for l in ls)}


def _bank_from_filename(path: str, db: Session) -> Optional[MasterBank]:
    """Nama file kiriman BI diawali nomor urut konfirmasi: '16. Deutsche Bank.xlsx'."""
    m = re.match(r"^\s*(\d{1,2})\s*[.\-]", os.path.basename(path))
    if not m:
        return None
    return db.query(MasterBank).filter(MasterBank.No_Urut_Konfirmasi == int(m.group(1))).first()


def apply_workbooks(
    db: Session,
    period_id: int,
    files: Iterable[Tuple[str, Any]],
    resolver: EntityResolver,
) -> Dict[str, Any]:
    """
    Terapkan workbook berurutan: tiap file mengganti daftar line bank tsb untuk instrumen yang dimuatnya.
    Urutan yang dianjurkan: workbook kiriman BI dulu, lalu balasan bank.
    """
    applied, skipped = [], []
    known = {d.Sandi for d in db.query(BankDirectory.Sandi).all()}
    for name, fobj in files:
        try:
            data = read_cp_workbook(fobj, resolver)
        except ValueError as e:
            skipped.append({"file": os.path.basename(str(name)), "alasan": str(e)})
            continue
        for sandi, nama in data["directory"].items():
            if sandi not in known:
                known.add(sandi)
                db.add(BankDirectory(Sandi=sandi, Nama=nama))
        if not data["lines"]:
            skipped.append({"file": os.path.basename(str(name)), "alasan": "tidak memuat sheet Counterparty Line"})
            continue
        bank = data["bank"] or (_bank_from_filename(name, db) if isinstance(name, str) else None)
        if bank is None:
            skipped.append({"file": os.path.basename(str(name)), "alasan": "bank responden tidak dikenali"})
            continue
        for inst, rows in data["lines"].items():
            db.query(CounterpartyLine).filter(
                CounterpartyLine.period_id == period_id,
                CounterpartyLine.Bank_ID == bank.Bank_ID,
                CounterpartyLine.Instrument == inst,
            ).delete()
            for r in rows:
                db.add(CounterpartyLine(
                    period_id=period_id, Bank_ID=bank.Bank_ID, Instrument=inst,
                    Counterparty_Sandi=r["sandi"], Counterparty_Nama=r["nama"], Status=r["status"],
                    Source_File=os.path.basename(str(name)), Confirmed_By_Bank=data["confirmed"],
                ))
        # Wajib flush per file: session tidak autoflush, dan bulk delete file berikutnya
        # hanya melihat baris yang sudah tertulis ke database.
        db.flush()
        applied.append({"file": os.path.basename(str(name)), "bank_id": bank.Bank_ID,
                        "instrumen": sorted(data["lines"]), "balasan_bank": data["confirmed"]})
    db.flush()
    return {"applied": applied, "skipped": skipped}


def compute_metrics(db: Session, period_id: int) -> Dict[str, Any]:
    """Hitung B4/B5 dari line yang tersimpan; bank tanpa data line tidak diberi nilai (tetap 'belum ada data')."""
    banks = db.query(MasterBank).all()
    du_sandi = {b.Sandi_BI.zfill(3): b for b in banks if b.Sandi_BI}
    lines = db.query(CounterpartyLine).filter(CounterpartyLine.period_id == period_id).all()
    by_bank: Dict[str, Dict[str, List[CounterpartyLine]]] = {}
    for l in lines:
        by_bank.setdefault(l.Bank_ID, {}).setdefault(l.Instrument, []).append(l)

    raw_metrics, breakdown, failed = {}, {}, {}
    for bank in banks:
        inst_lines = by_bank.get(bank.Bank_ID)
        if not inst_lines:
            continue
        own = (bank.Sandi_BI or "").zfill(3)
        raw_metrics[bank.Bank_ID], breakdown[bank.Bank_ID] = {}, {}
        for inst, code in (("REPO", "B4"), ("OIS", "B5")):
            if inst not in inst_lines:
                continue
            active = {l.Counterparty_Sandi: l for l in inst_lines[inst]
                      if not is_deleted(l.Status) and l.Counterparty_Sandi != own}
            du = sorted(s for s in active if s in du_sandi)
            non_du = sorted(s for s in active if s not in du_sandi)
            if code == "B4":
                rate = round(min(len(du) / MIN_LINES, 1) * 50.0 + min(len(non_du) / MIN_LINES, 1) * 50.0, 2)
            else:
                rate = round(min(len(du) / MIN_LINES, 1) * 100.0, 2)
            deleted = [l.Counterparty_Nama for l in inst_lines[inst] if is_deleted(l.Status)]
            after = {s for s, l in active.items() if is_after_cutoff(l.Status)}
            label = lambda s: du_sandi[s].Nama_Singkat or s if s in du_sandi else active[s].Counterparty_Nama or s
            raw_metrics[bank.Bank_ID][code] = rate
            breakdown[bank.Bank_ID][code] = {
                "line_du": len(du), "line_non_du": len(non_du), "target": MIN_LINES,
                "line_dihapus": len(deleted), "rate": rate,
                "line_du_setelah_cutoff": len([s for s in du if s in after]),
                "line_non_du_setelah_cutoff": len([s for s in non_du if s in after]),
                "counterparty_setelah_cutoff": [label(s) for s in sorted(after)],
                "dikonfirmasi_bank": any(l.Confirmed_By_Bank for l in inst_lines[inst]),
                "counterparty_du": [du_sandi[s].Nama_Singkat or s for s in du],
            }
            if rate < 100.0:
                item = {
                    "parameter": f"Counterparty Line {'Repo' if inst == 'REPO' else 'OIS'}",
                    "realisasi_line_du": len(du), "target_line_du": MIN_LINES,
                    "counterparty_du": [du_sandi[s].Nama_Singkat or s for s in du],
                    "line_setelah_cutoff": len(after),
                }
                if code == "B4":
                    item.update({"realisasi_line_non_du": len(non_du), "target_line_non_du": MIN_LINES,
                                 "alasan": f"Counterparty line Repo {len(du)} bank DU dan {len(non_du)} bank non-DU "
                                           f"(minimal {MIN_LINES} DU dan {MIN_LINES} non-DU)"})
                else:
                    item["alasan"] = f"Counterparty line OIS dengan Dealer Utama sebanyak {len(du)} line (minimal {MIN_LINES} line)"
                failed[f"{bank.Bank_ID}-{code}"] = [item]
    return {"raw_metrics": raw_metrics, "breakdown": breakdown, "failed": failed}


def local_workbook_files(dataset_dir: str) -> List[str]:
    """Workbook kiriman BI lebih dulu, lalu balasan bank (folder yang namanya memuat 'Confirmed')."""
    outgoing = sorted(glob.glob(os.path.join(dataset_dir, "Konfirmasi Bank", "*.xlsx")))
    replies = sorted(
        p for p in glob.glob(os.path.join(dataset_dir, "*Confirmed*", "**", "*.xlsx"), recursive=True)
    )
    return [p for p in outgoing + replies if not os.path.basename(p).startswith("~$")]
