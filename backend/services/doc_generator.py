"""
Evaluation Snapshot & Automated Document Generator (M.02 & M.01 Engine)
Menghasilkan dokumen resmi Bank Indonesia:
1. Memorandum M.02 (.docx): Laporan Evaluasi Triwulanan ke Pimpinan DPPK.
2. Memorandum M.01 (.docx): Pengantar Hasil Evaluasi & Rekomendasi Tindak Lanjut ke DSMM.
3. Paket 3 Lampiran Resmi (.xlsx): Multi-sheet Excel (Sebelum Threshold, Setelah Threshold, dan Tindak Lanjut).
"""

import io
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from models import get_active_period, MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, AuditTrail
from services.rule_engine import THRESHOLDS, WEIGHTS, PARAMETER_NAMES


# ==============================================================================
# DOCX HELPER FUNCTIONS & STYLING
# ==============================================================================
def _set_cell_background(cell, fill_hex: str):
    """Set background color of a docx table cell."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tc_pr.append(shd)


def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Set inner padding for a docx table cell in twips."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tc_pr.append(tc_mar)


def _set_table_borders(table, color="CBD5E1", sz="4", val="single"):
    """Apply thin borders to entire table."""
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:right w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'</w:tblBorders>'
    )
    tbl_pr.append(borders)


# ==============================================================================
# 1. GENERATOR MEMORANDUM WORD (M.02 & M.01)
# ==============================================================================
PUVA_CODES_DOC = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"]
TINDAK_LANJUT_PENDING = (
    "Pemetaan skor PUVA ke tindak lanjut (pembinaan / teguran tertulis) menunggu penetapan "
    "aturan skor tanpa komponen Operasi Moneter."
)


def _failed_params(m) -> list:
    return [c for c in PUVA_CODES_DOC if getattr(m, f"{c.lower()}_passed", None) is False]


def _missing_params(m) -> list:
    return [c for c in PUVA_CODES_DOC if getattr(m, f"{c.lower()}_raw", None) is None]


def _score(m) -> float:
    return m.total_puva_score or 0.0


def generate_memo_docx(
    db: Session,
    memo_type: str = "m02",
    custom_narration: Optional[str] = None,
    masked: bool = False,
) -> io.BytesIO:
    """
    Generate Memorandum resmi Bank Indonesia dalam format .docx:
    - memo_type 'm02': Memorandum internal kepada Pimpinan DPPK
    - memo_type 'm01': Memorandum pengantar kepada DSMM
    """
    memo_type = memo_type.lower()
    if memo_type not in ["m02", "m01"]:
        memo_type = "m02"

    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"
    stage_str = period.Active_Threshold_Stage if period else "EARLY"

    # Query 21 Bank Score Matrices
    matrices = (
        db.query(BankScoreMatrix)
        .join(MasterBank)
        .filter(BankScoreMatrix.period_id == period.id)
        .order_by(MasterBank.Bank_ID.asc())
        .all()
    )

    # Query 5 Finding Tickets
    tickets = (
        db.query(FindingTicket)
        .join(MasterBank)
        .filter(FindingTicket.period_id == period.id)
        .order_by(FindingTicket.Finding_ID.asc())
        .all()
    )

    # Statistics
    total_banks = len(matrices)
    full_pass_banks = [m for m in matrices if m.compliance_status == "MEMENUHI"]
    tidak_memenuhi_banks = [m for m in matrices if m.compliance_status == "TIDAK_MEMENUHI"]
    belum_lengkap_banks = [m for m in matrices if m.compliance_status == "DATA_BELUM_LENGKAP"]

    doc = Document()

    # Set Margins (1 inch all around)
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Header Bank Indonesia
    p_bi = doc.add_paragraph()
    p_bi.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_bi = p_bi.add_run("BANK INDONESIA")
    run_bi.bold = True
    run_bi.font.name = "Calibri"
    run_bi.font.size = Pt(14)
    run_bi.font.color.rgb = RGBColor(15, 23, 42)

    p_dept = doc.add_paragraph()
    p_dept.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_dept = p_dept.add_run("DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN")
    run_dept.bold = True
    run_dept.font.name = "Calibri"
    run_dept.font.size = Pt(11)
    run_dept.font.color.rgb = RGBColor(71, 85, 105)

    p_memo_title = doc.add_paragraph()
    p_memo_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_memo_title = p_memo_title.add_run("MEMORANDUM")
    run_memo_title.bold = True
    run_memo_title.font.name = "Calibri"
    run_memo_title.font.size = Pt(13)
    run_memo_title.font.underline = True
    run_memo_title.font.color.rgb = RGBColor(15, 23, 42)

    # Metadata Memorandum
    table_meta = doc.add_table(rows=6, cols=3)
    table_meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_meta.autofit = False

    memo_meta = {
        "m02": {
            "nomor": f"MEMO-{datetime.utcnow().year}/DPPK/PUVA/M.02/084",
            "kepada": "Yth. Kepala Departemen Pengembangan Pasar Keuangan (DPPK)",
            "dari": "Tim Evaluasi & Pengawasan Pasar Uang dan Pasar Valas (DPPK)",
            "perihal": f"Laporan Hasil Evaluasi Triwulanan Kewajiban Dealer Utama PUVA Periode {triwulan_str} dan Permohonan Persetujuan Hasil Rekonsiliasi",
        },
        "m01": {
            "nomor": f"MEMO-{datetime.utcnow().year}/DPPK/PUVA/M.01/085",
            "kepada": "Yth. Kepala Departemen Surveilans & Manajemen Risiko (DSMM)",
            "dari": "Kepala Departemen Pengembangan Pasar Keuangan (DPPK)",
            "perihal": f"Penyampaian Hasil Akhir Evaluasi Pemenuhan Kewajiban Dealer Utama PUVA Periode {triwulan_str} untuk Pembinaan & Pengawasan",
        },
    }

    meta_rows = [
        ("Nomor", ":", memo_meta[memo_type]["nomor"]),
        ("Kepada", ":", memo_meta[memo_type]["kepada"]),
        ("Dari", ":", memo_meta[memo_type]["dari"]),
        ("Tanggal", ":", datetime.utcnow().strftime("%d %B %Y")),
        ("Sifat", ":", "RAHASIA / SEGERA"),
        ("Perihal", ":", memo_meta[memo_type]["perihal"]),
    ]

    for idx, (lbl, sep, val) in enumerate(meta_rows):
        row = table_meta.rows[idx]
        row.cells[0].width = Inches(1.2)
        row.cells[1].width = Inches(0.2)
        row.cells[2].width = Inches(5.1)

        p0 = row.cells[0].paragraphs[0]
        r0 = p0.add_run(lbl)
        r0.font.name = "Calibri"
        r0.font.size = Pt(10)
        r0.bold = True

        p1 = row.cells[1].paragraphs[0]
        r1 = p1.add_run(sep)
        r1.font.name = "Calibri"
        r1.font.size = Pt(10)

        p2 = row.cells[2].paragraphs[0]
        r2 = p2.add_run(val)
        r2.font.name = "Calibri"
        r2.font.size = Pt(10)
        if lbl in ["Kepada", "Nomor", "Perihal"]:
            r2.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # Divider line
    p_line = doc.add_paragraph()
    p_line_run = p_line.add_run("―" * 58)
    p_line_run.font.color.rgb = RGBColor(148, 163, 184)
    p_line.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ==========================================================================
    # KONTEN MEMORANDUM M.02 (KEPADA PIMPINAN DPPK)
    # ==========================================================================
    if memo_type == "m02":
        # 1. Latar Belakang
        h1 = doc.add_heading("1. Latar Belakang dan Landasan Hukum", level=2)
        h1.runs[0].font.name = "Calibri"
        h1.runs[0].font.size = Pt(11)
        h1.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(
            "1.1. Merujuk Peraturan Bank Indonesia (PBI) No. 6 Tahun 2024 tentang Pasar Uang dan Pasar Valuta Asing "
            "serta Peraturan Anggota Dewan Gubernur (PADG) No. 23 Tahun 2024 tentang Tata Cara Penetapan, Evaluasi, dan "
            "Kewajiban Dealer Utama Pasar Uang dan Pasar Valuta Asing (DU PUVA).\n"
            f"1.2. Telah dilaksanakan kegiatan evaluasi triwulanan atas kepatuhan 21 (dua puluh satu) Bank Dealer Utama "
            f"untuk periode {triwulan_str} (berdasarkan 60 hari kerja aktif pasar) pada tahap penetapan ambang batas: "
        )
        r.font.name = "Calibri"
        r.font.size = Pt(10)
        r_stage = p.add_run(f"{stage_str} STATE.")
        r_stage.bold = True
        r_stage.font.name = "Calibri"
        r_stage.font.size = Pt(10)

        # 2. Ringkasan Eksekutif
        h2 = doc.add_heading("2. Ringkasan Eksekutif Hasil Evaluasi & Rekonsiliasi", level=2)
        h2.runs[0].font.name = "Calibri"
        h2.runs[0].font.size = Pt(11)
        h2.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        # Narasi Eksekutif (Kustom dari Pengguna atau Auto-Generated)
        p_narasi = doc.add_paragraph()
        p_narasi.paragraph_format.line_spacing = 1.15
        p_narasi.paragraph_format.space_after = Pt(8)
        if custom_narration and custom_narration.strip():
            r_nar = p_narasi.add_run(custom_narration.strip())
        else:
            r_nar = p_narasi.add_run(
                f"Berdasarkan hasil perhitungan rule engine PADG No. 23 Tahun 2024 atas data kewajiban Pasar Uang dan "
                f"Pasar Valas, tercatat {len(full_pass_banks)} bank memenuhi seluruh kewajiban PUVA (skor 60%), "
                f"{len(tidak_memenuhi_banks)} bank tidak memenuhi minimal satu kewajiban, dan {len(belum_lengkap_banks)} bank "
                f"dengan data evaluasi yang belum lengkap. {TINDAK_LANJUT_PENDING}"
            )
        r_nar.font.name = "Calibri"
        r_nar.font.size = Pt(10)

        # Tabel Ringkasan Sebelum vs Sesudah Rekonsiliasi
        t_sum = doc.add_table(rows=5, cols=4)
        t_sum.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(t_sum)

        headers = ["Status Evaluasi", "Sebelum Rekonsiliasi", "Pasca Rekonsiliasi", "Keterangan"]
        for c_idx, h_text in enumerate(headers):
            cell = t_sum.cell(0, c_idx)
            _set_cell_background(cell, "0F172A")
            _set_cell_margins(cell, 120, 120, 150, 150)
            p_h = cell.paragraphs[0]
            p_h.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r_h = p_h.add_run(h_text)
            r_h.bold = True
            r_h.font.color.rgb = RGBColor(255, 255, 255)
            r_h.font.name = "Calibri"
            r_h.font.size = Pt(9.5)

        open_tickets = [t for t in tickets if t.BI_Decision_Status in ("OPEN", "PENDING_REVIEW")]
        decided_tickets = [t for t in tickets if t.BI_Decision_Status in ("APPROVED", "REJECTED")]
        sum_data = [
            ("Memenuhi Seluruh Kewajiban PUVA (60%)", "-", f"{len(full_pass_banks)} Bank", "Seluruh 9 parameter lolos threshold"),
            ("Tiket Temuan / Sanggahan", f"{len(tickets)} Tiket", f"{len(open_tickets)} Terbuka", f"{len(decided_tickets)} telah diputuskan petugas BI"),
            ("Tidak Memenuhi Minimal Satu Kewajiban", "-", f"{len(tidak_memenuhi_banks)} Bank", "Tindak lanjut menunggu penetapan"),
            ("Data Evaluasi Belum Lengkap", "-", f"{len(belum_lengkap_banks)} Bank", "Sumber data belum seluruhnya diunggah"),
        ]

        for r_idx, row_vals in enumerate(sum_data, start=1):
            for c_idx, val in enumerate(row_vals):
                cell = t_sum.cell(r_idx, c_idx)
                _set_cell_margins(cell, 80, 80, 120, 120)
                if r_idx % 2 == 1:
                    _set_cell_background(cell, "F8FAFC")
                p_c = cell.paragraphs[0]
                if c_idx in [1, 2]:
                    p_c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r_c = p_c.add_run(val)
                r_c.font.name = "Calibri"
                r_c.font.size = Pt(9)
                if c_idx == 0:
                    r_c.bold = True

        doc.add_paragraph().paragraph_format.space_after = Pt(6)

        # 3. Rincian Tiket Sanggahan (Finding Tickets)
        h3 = doc.add_heading("3. Rincian Hasil Verifikasi Sanggahan Bank (Finding Tickets)", level=2)
        h3.runs[0].font.name = "Calibri"
        h3.runs[0].font.size = Pt(11)
        h3.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        t_fnd = doc.add_table(rows=len(tickets) + 1, cols=6)
        t_fnd.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(t_fnd)

        fnd_headers = ["Finding ID", "Bank DU", "Param", "Klaim Bank", "Rekomendasi AI", "Keputusan Final"]
        for c_idx, h_text in enumerate(fnd_headers):
            cell = t_fnd.cell(0, c_idx)
            _set_cell_background(cell, "0F172A")
            _set_cell_margins(cell, 120, 120, 120, 120)
            p_h = cell.paragraphs[0]
            p_h.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r_h = p_h.add_run(h_text)
            r_h.bold = True
            r_h.font.color.rgb = RGBColor(255, 255, 255)
            r_h.font.name = "Calibri"
            r_h.font.size = Pt(9)

        for idx, t in enumerate(tickets, start=1):
            bank_name = t.bank.Masked_Alias if masked else t.bank.Nama_Resmi_Bank
            vals = [
                t.Finding_ID,
                f"{t.bank.Masked_Alias}\n({bank_name})",
                t.Parameter_Code,
                t.Nilai_Klaim_Bank or "Tidak Mengajukan",
                t.AI_Recommendation_Status or "Pending",
                t.BI_Decision_Status,
            ]
            for c_idx, val in enumerate(vals):
                cell = t_fnd.cell(idx, c_idx)
                _set_cell_margins(cell, 80, 80, 100, 100)
                if idx % 2 == 1:
                    _set_cell_background(cell, "F8FAFC")
                p_c = cell.paragraphs[0]
                if c_idx in [0, 2, 4, 5]:
                    p_c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r_c = p_c.add_run(str(val))
                r_c.font.name = "Calibri"
                r_c.font.size = Pt(8.5)
                if c_idx == 5:
                    r_c.bold = True
                    if t.BI_Decision_Status == "APPROVED":
                        r_c.font.color.rgb = RGBColor(5, 150, 105)
                    elif t.BI_Decision_Status == "REJECTED":
                        r_c.font.color.rgb = RGBColor(225, 29, 72)

        doc.add_paragraph().paragraph_format.space_after = Pt(6)

        # 4. Rekomendasi & Permohonan Persetujuan
        h4 = doc.add_heading("4. Kesimpulan dan Permohonan Persetujuan", level=2)
        h4.runs[0].font.name = "Calibri"
        h4.runs[0].font.size = Pt(11)
        h4.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        p_rek = doc.add_paragraph()
        p_rek.paragraph_format.line_spacing = 1.15
        p_rek.paragraph_format.space_after = Pt(12)
        r_rek = p_rek.add_run(
            "Sehubungan dengan selesainya proses rekonsiliasi dan verifikasi teknis atas seluruh transaksi 21 Dealer Utama PUVA, "
            "bersama ini kami memohon perkenan Bapak/Ibu Kepala Departemen Pengembangan Pasar Keuangan untuk:\n"
            f"a. Menyetujui hasil evaluasi pemenuhan kewajiban 21 Bank DU PUVA Periode {triwulan_str} sebagaimana tercantum "
            "dalam Lampiran 1, 2, dan 3;\n"
            "b. Menyetujui penyampaian Memorandum M.01 kepada Departemen Surveilans & Manajemen Risiko (DSMM) sebagai dasar "
            "pelaksanaan tindak lanjut pengawasan perbankan, pembinaan, dan penerbitan sanksi administratif sesuai PADG No. 23/2024."
        )
        r_rek.font.name = "Calibri"
        r_rek.font.size = Pt(10)

        # Lembar Tanda Tangan
        t_sign = doc.add_table(rows=3, cols=2)
        t_sign.alignment = WD_TABLE_ALIGNMENT.CENTER
        for r in t_sign.rows:
            r.cells[0].width = Inches(3.2)
            r.cells[1].width = Inches(3.3)

        p_s0 = t_sign.cell(0, 0).paragraphs[0]
        r_s0 = p_s0.add_run("Disiapkan Oleh:\nTim Evaluasi & Rekonsiliasi PUVA\nDepartemen Pengembangan Pasar Keuangan")
        r_s0.font.name = "Calibri"
        r_s0.font.size = Pt(9.5)

        p_s1 = t_sign.cell(0, 1).paragraphs[0]
        r_s1 = p_s1.add_run("Menyetujui:\nKepala Departemen Pengembangan\nPasar Keuangan (DPPK)")
        r_s1.font.name = "Calibri"
        r_s1.font.size = Pt(9.5)
        r_s1.bold = True

        # Ruang Tanda Tangan
        t_sign.cell(1, 0).paragraphs[0].paragraph_format.space_after = Pt(40)
        t_sign.cell(1, 1).paragraphs[0].paragraph_format.space_after = Pt(40)

        p_n0 = t_sign.cell(2, 0).paragraphs[0]
        r_n0 = p_n0.add_run("Analis Senior / Manajer Tim PUVA\nNIP. 198804122012011002")
        r_n0.font.name = "Calibri"
        r_n0.font.size = Pt(9.5)
        r_n0.bold = True

        p_n1 = t_sign.cell(2, 1).paragraphs[0]
        r_n1 = p_n1.add_run("Donny Hutabarat / Pimpinan Terkait\nDirektur Eksekutif DPPK")
        r_n1.font.name = "Calibri"
        r_n1.font.size = Pt(9.5)
        r_n1.bold = True

    # ==========================================================================
    # KONTEN MEMORANDUM M.01 (PENGANTAR KE DSMM)
    # ==========================================================================
    else:
        # 1. Dasar Hukum & Maksud
        h1 = doc.add_heading("1. Dasar Hukum dan Maksud Penyampaian", level=2)
        h1.runs[0].font.name = "Calibri"
        h1.runs[0].font.size = Pt(11)
        h1.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(
            f"1.1. Menindaklanjuti ketentuan Pasal 28 Peraturan Anggota Dewan Gubernur No. 23 Tahun 2024 tentang "
            f"Kewajiban dan Evaluasi Dealer Utama Pasar Uang dan Pasar Valuta Asing (DU PUVA), Departemen Pengembangan "
            f"Pasar Keuangan (DPPK) menyampaikan hasil akhir evaluasi kepatuhan 21 (dua puluh satu) Bank Dealer Utama "
            f"untuk Periode {triwulan_str}.\n"
            f"1.2. Memorandum ini disampaikan kepada Departemen Surveilans & Manajemen Risiko (DSMM) sebagai rujukan resmi "
            f"dalam melaksanakan pembinaan pengawasan bank dan penegakan sanksi administratif sesuai kewenangan yang diatur dalam PADG."
        )
        r.font.name = "Calibri"
        r.font.size = Pt(10)

        # 2. Klasifikasi Hasil Evaluasi & Tindak Lanjut
        h2 = doc.add_heading("2. Klasifikasi Hasil Evaluasi & Rekomendasi Tindak Lanjut", level=2)
        h2.runs[0].font.name = "Calibri"
        h2.runs[0].font.size = Pt(11)
        h2.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        p_rule = doc.add_paragraph()
        p_rule.paragraph_format.line_spacing = 1.15
        p_rule.paragraph_format.space_after = Pt(8)
        r_rule = p_rule.add_run(
            "Berdasarkan perhitungan Skor PUVA (maksimal 60%, komponen Operasi Moneter tidak termasuk dalam "
            "evaluasi ini), hasil evaluasi 21 Bank DU PUVA diklasifikasikan sebagai berikut. " + TINDAK_LANJUT_PENDING
        )
        r_rule.font.name = "Calibri"
        r_rule.font.size = Pt(10)

        categories = [
            ("A. Memenuhi Seluruh Kewajiban PUVA (Skor 60%)", RGBColor(5, 150, 105), full_pass_banks, False),
            ("B. Tidak Memenuhi Minimal Satu Kewajiban PUVA", RGBColor(225, 29, 72), tidak_memenuhi_banks, True),
            ("C. Data Evaluasi Belum Lengkap", RGBColor(100, 116, 139), belum_lengkap_banks, False),
        ]
        for title, color, banks_in_cat, show_params in categories:
            p_cat = doc.add_paragraph()
            p_cat.paragraph_format.left_indent = Inches(0.2)
            r_t = p_cat.add_run(title + "\n")
            r_t.bold = True
            r_t.font.color.rgb = color
            names = []
            for m in banks_in_cat:
                nm = m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank
                if show_params:
                    nm += f" ({_score(m):.1f}%; {', '.join(_failed_params(m))})"
                names.append(nm)
            r_d = p_cat.add_run(f"Sebanyak {len(banks_in_cat)} bank: {', '.join(names) if names else 'Nihil'}.")
            r_d.font.size = Pt(9.5)

        doc.add_paragraph().paragraph_format.space_after = Pt(6)

        # 3. Tabel Detail Bank dalam Kategori Pengawasan Khusus
        h3 = doc.add_heading("3. Ringkasan Bank Memerlukan Tindak Lanjut Khusus", level=2)
        h3.runs[0].font.name = "Calibri"
        h3.runs[0].font.size = Pt(11)
        h3.runs[0].font.color.rgb = RGBColor(15, 23, 42)

        attention_banks = tidak_memenuhi_banks
        t_att = doc.add_table(rows=len(attention_banks) + 1, cols=5)
        t_att.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(t_att)

        att_headers = ["Bank ID", "Nama Dealer Utama", "Skor PUVA (maks 60%)", "Parameter Tidak Terpenuhi", "Tindak Lanjut"]
        for c_idx, h_text in enumerate(att_headers):
            cell = t_att.cell(0, c_idx)
            _set_cell_background(cell, "0F172A")
            _set_cell_margins(cell, 120, 120, 120, 120)
            p_h = cell.paragraphs[0]
            p_h.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r_h = p_h.add_run(h_text)
            r_h.bold = True
            r_h.font.color.rgb = RGBColor(255, 255, 255)
            r_h.font.name = "Calibri"
            r_h.font.size = Pt(9)

        for idx, m in enumerate(attention_banks, start=1):
            bank_name = m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank
            failed_p = _failed_params(m)
            rec_text = "Menunggu penetapan"

            vals = [
                m.bank.Bank_ID,
                f"{m.bank.Masked_Alias}\n({bank_name})",
                f"{_score(m):.2f}%",
                ", ".join(failed_p) if failed_p else "-",
                rec_text,
            ]

            for c_idx, val in enumerate(vals):
                cell = t_att.cell(idx, c_idx)
                _set_cell_margins(cell, 80, 80, 100, 100)
                if idx % 2 == 1:
                    _set_cell_background(cell, "F8FAFC")
                p_c = cell.paragraphs[0]
                if c_idx in [0, 2, 3]:
                    p_c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r_c = p_c.add_run(str(val))
                r_c.font.name = "Calibri"
                r_c.font.size = Pt(8.5)
                if c_idx == 4:
                    r_c.bold = True
                    if "Teguran" in rec_text:
                        r_c.font.color.rgb = RGBColor(225, 29, 72)
                    else:
                        r_c.font.color.rgb = RGBColor(217, 119, 6)

        doc.add_paragraph().paragraph_format.space_after = Pt(6)

        # 4. Lampiran Terkait & Penutup
        p_close = doc.add_paragraph()
        p_close.paragraph_format.line_spacing = 1.15
        p_close.paragraph_format.space_after = Pt(12)
        r_cl = p_close.add_run(
            "Sebagai kelengkapan berkas tindak lanjut, bersama ini kami lampirkan:\n"
            "1. Lampiran 1: Matriks Capaian Mentah Dealer Utama (Sebelum Threshold)\n"
            "2. Lampiran 2: Matriks Skor Terbobot dan Nilai Komposit (Setelah Threshold)\n"
            "3. Lampiran 3: Keterangan Detail Hasil Evaluasi dan Rincian Temuan Per Bank\n\n"
            "Demikian kami sampaikan. Atas koordinasi dan kerja sama yang baik, kami ucapkan terima kasih."
        )
        r_cl.font.name = "Calibri"
        r_cl.font.size = Pt(10)

        # Signature Block
        t_sign = doc.add_table(rows=2, cols=1)
        t_sign.alignment = WD_TABLE_ALIGNMENT.RIGHT
        c_sign = t_sign.cell(0, 0)
        c_sign.width = Inches(3.5)
        p_s = c_sign.paragraphs[0]
        r_s = p_s.add_run("Departemen Pengembangan Pasar Keuangan\nKepala Departemen,")
        r_s.bold = True
        r_s.font.name = "Calibri"
        r_s.font.size = Pt(10)
        p_s.paragraph_format.space_after = Pt(45)

        c_name = t_sign.cell(1, 0)
        p_n = c_name.paragraphs[0]
        r_n = p_n.add_run("Donny Hutabarat\nDirektur Eksekutif")
        r_n.bold = True
        r_n.font.name = "Calibri"
        r_n.font.size = Pt(10)

    # Save to BytesIO
    docx_io = io.BytesIO()
    doc.save(docx_io)
    docx_io.seek(0)
    return docx_io


# ==============================================================================
# 2. GENERATOR PAKET 3 LAMPIRAN EXCEL (LAMPIRAN 1, 2, DAN 3)
# ==============================================================================
def generate_attachments_xlsx(db: Session, masked: bool = False) -> io.BytesIO:
    """
    Menghasilkan file Excel (.xlsx) multi-sheet yang memuat 3 lampiran resmi:
    - Sheet 1: Lampiran 1 - Sebelum Threshold (Capaian Mentah B1-B8)
    - Sheet 2: Lampiran 2 - Setelah Threshold (Skor Terbobot & Komposit)
    - Sheet 3: Lampiran 3 - Tindak Lanjut (Status Kepatuhan & Rekomendasi Sanksi/Pembinaan)
    """
    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"
    stage_str = period.Active_Threshold_Stage if period else "EARLY"

    matrices = (
        db.query(BankScoreMatrix)
        .join(MasterBank)
        .filter(BankScoreMatrix.period_id == period.id)
        .order_by(MasterBank.Bank_ID.asc())
        .all()
    )

    tickets = (
        db.query(FindingTicket)
        .join(MasterBank)
        .filter(FindingTicket.period_id == period.id)
        .order_by(FindingTicket.Finding_ID.asc())
        .all()
    )
    tickets_by_bank: Dict[str, List[FindingTicket]] = {}
    for t in tickets:
        tickets_by_bank.setdefault(t.Bank_ID, []).append(t)

    wb = Workbook()
    wb.remove(wb.active)  # Hapus default empty sheet

    # Color Fills & Styles
    navy_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    dark_slate_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    emerald_fill = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
    light_emerald_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid")
    light_rose_fill = PatternFill(start_color="FFF1F2", end_color="FFF1F2", fill_type="solid")
    light_amber_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    font_title = Font(name="Calibri", size=13, bold=True, color="0F172A")
    font_subtitle = Font(name="Calibri", size=9.5, italic=True, color="475569")
    font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=9.5, bold=True, color="0F172A")
    font_regular = Font(name="Calibri", size=9.5, color="1E293B")
    font_pass = Font(name="Calibri", size=9.5, bold=True, color="047857")
    font_fail = Font(name="Calibri", size=9.5, bold=True, color="BE123C")
    font_amber = Font(name="Calibri", size=9.5, bold=True, color="B45309")

    thin_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    # --------------------------------------------------------------------------
    # SHEET 1: LAMPIRAN 1 (SEBELUM THRESHOLD - CAPAIAN MENTAH)
    # --------------------------------------------------------------------------
    ws1 = wb.create_sheet(title="Lampiran 1 - Sebelum Thresh")
    ws1.views.sheetView[0].showGridLines = True

    ws1.merge_cells("A1:N1")
    ws1["A1"] = "BANK INDONESIA - DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN"
    ws1["A1"].font = font_subtitle

    ws1.merge_cells("A2:N2")
    ws1["A2"] = f"LAMPIRAN 1: HASIL EVALUASI REALISASI MENTAH DEALER UTAMA PUVA (SEBELUM THRESHOLD) - {triwulan_str}"
    ws1["A2"].font = font_title

    ws1.merge_cells("A3:N3")
    ws1["A3"] = f"Dasar Hukum: PBI No. 6 Tahun 2024 & PADG No. 23 Tahun 2024 | Efektif Pasar: 60 Hari Kerja | Nilai ditampilkan dalam rasio % realisasi mentah."
    ws1["A3"].font = font_subtitle

    headers_l1 = [
        "No", "Bank ID", "Nama Dealer Utama", "KBMI",
        "B1: Repo (%)", "B2: SRBI (%)", "B3: OIS (%)", "B4: Line Repo (%)",
        "B5: Line OIS (%)", "B6: Jual SRBI (%)", "B7a: Repo 14h (%)",
        "B7b: SRBI 3Bln (%)", "B8: Match OIS (%)", "Rata-rata PUVA",
    ]

    for col_idx, h_text in enumerate(headers_l1, start=1):
        cell = ws1.cell(row=5, column=col_idx, value=h_text)
        cell.font = font_header
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border
    ws1.row_dimensions[5].height = 28

    for row_idx, m in enumerate(matrices, start=6):
        bank_name = m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank
        raw_vals = [getattr(m, f"{c.lower()}_raw") for c in PUVA_CODES_DOC]
        known = [v for v in raw_vals if v is not None]
        avg_puva = sum(known) / len(known) if known else None

        vals = [
            row_idx - 5,
            m.bank.Bank_ID,
            f"{m.bank.Masked_Alias} - {bank_name}" if not masked else m.bank.Masked_Alias,
            m.bank.Kelompok_KBMI,
            *[(v / 100.0 if v is not None else "Belum ada data") for v in raw_vals],
            avg_puva / 100.0 if avg_puva is not None else "-",
        ]

        for col_idx, val in enumerate(vals, start=1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            if row_idx % 2 == 1:
                cell.fill = zebra_fill

            if col_idx in [1, 2, 4]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 3:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "0.0%"

    # Auto-fit columns
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 3, 11)
    ws1.column_dimensions["C"].width = 30

    # --------------------------------------------------------------------------
    # SHEET 2: LAMPIRAN 2 (SETELAH THRESHOLD - SKOR TERBOBOT & KOMPOSIT)
    # --------------------------------------------------------------------------
    ws2 = wb.create_sheet(title="Lampiran 2 - Setelah Thresh")
    ws2.views.sheetView[0].showGridLines = True

    ws2.merge_cells("A1:Q1")
    ws2["A1"] = "BANK INDONESIA - DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN"
    ws2["A1"].font = font_subtitle

    ws2.merge_cells("A2:Q2")
    ws2["A2"] = f"LAMPIRAN 2: HASIL EVALUASI SKOR TERBOBOT DEALER UTAMA PUVA (SETELAH THRESHOLD) - {triwulan_str}"
    ws2["A2"].font = font_title

    ws2.merge_cells("A3:Q3")
    ws2["A3"] = f"Tahap Threshold: {stage_str} STATE | Bobot Maksimal: PUVA 60.0% (komponen Operasi Moneter tidak dievaluasi)"
    ws2["A3"].font = font_subtitle

    headers_l2 = [
        "No", "Bank ID", "Nama Dealer Utama",
        "B1 (2.5%)", "B2 (2.5%)", "B3 (2.5%)", "B4 (7.5%)", "B5 (2.5%)",
        "B6 (7.5%)", "B7a (20%)", "B7b (5%)", "B8 (10%)", "Skor PUVA (60%)",
    ]

    for col_idx, h_text in enumerate(headers_l2, start=1):
        cell = ws2.cell(row=5, column=col_idx, value=h_text)
        cell.font = font_header
        cell.fill = dark_slate_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border
    ws2.row_dimensions[5].height = 28

    for row_idx, m in enumerate(matrices, start=6):
        bank_name = m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank
        vals = [
            row_idx - 5,
            m.bank.Bank_ID,
            f"{m.bank.Masked_Alias} - {bank_name}" if not masked else m.bank.Masked_Alias,
            *[(getattr(m, f"{c.lower()}_score") or 0.0) / 100.0 for c in PUVA_CODES_DOC],
            _score(m) / 100.0,
        ]

        for col_idx, val in enumerate(vals, start=1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            if row_idx % 2 == 1:
                cell.fill = zebra_fill

            if col_idx in [1, 2]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 3:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif col_idx in [13, 17]:
                # Kolom Subtotal PUVA dan Komposit Total
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.font = font_bold
                cell.number_format = "0.0%"
                if col_idx == 17:
                    if val >= 1.0:
                        cell.fill = light_emerald_fill
                        cell.font = font_pass
                    elif val >= 0.90:
                        cell.fill = light_amber_fill
                        cell.font = font_amber
                    else:
                        cell.fill = light_rose_fill
                        cell.font = font_fail
            else:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "0.0%"

    # Auto-fit columns
    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 3, 11)
    ws2.column_dimensions["C"].width = 28

    # --------------------------------------------------------------------------
    # SHEET 3: LAMPIRAN 3 (TINDAK LANJUT & STATUS KEPATUHAN PER BANK)
    # --------------------------------------------------------------------------
    ws3 = wb.create_sheet(title="Lampiran 3 - Tindak Lanjut")
    ws3.views.sheetView[0].showGridLines = True

    ws3.merge_cells("A1:I1")
    ws3["A1"] = "BANK INDONESIA - DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN"
    ws3["A1"].font = font_subtitle

    ws3.merge_cells("A2:I2")
    ws3["A2"] = f"LAMPIRAN 3: KETERANGAN HASIL EVALUASI & REKOMENDASI TINDAK LANJUT PER BANK - {triwulan_str}"
    ws3["A2"].font = font_title

    ws3.merge_cells("A3:I3")
    ws3["A3"] = "Rujukan: Skor PUVA maks 60%. " + TINDAK_LANJUT_PENDING
    ws3["A3"].font = font_subtitle

    headers_l3 = [
        "No", "Bank ID", "Nama Dealer Utama", "KBMI",
        "Skor PUVA (maks 60%)", "Status Kepatuhan", "Parameter Tidak Terpenuhi",
        "Tiket Finding Sanggahan", "Rekomendasi Tindak Lanjut",
    ]

    for col_idx, h_text in enumerate(headers_l3, start=1):
        cell = ws3.cell(row=5, column=col_idx, value=h_text)
        cell.font = font_header
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border
    ws3.row_dimensions[5].height = 28

    for row_idx, m in enumerate(matrices, start=6):
        bank_name = m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank

        # Parameter yang gugur
        failed_params = _failed_params(m)

        bank_tickets = tickets_by_bank.get(m.Bank_ID, [])
        ticket_str = ", ".join([f"{t.Finding_ID} ({t.BI_Decision_Status})" for t in bank_tickets]) if bank_tickets else "-"

        if m.compliance_status == "MEMENUHI":
            tindak_lanjut = "Memenuhi seluruh kewajiban DU PUVA"
        elif m.compliance_status == "TIDAK_MEMENUHI":
            tindak_lanjut = "Menunggu penetapan tindak lanjut"
        else:
            tindak_lanjut = "Data belum lengkap: " + ", ".join(_missing_params(m))

        vals = [
            row_idx - 5,
            m.bank.Bank_ID,
            f"{m.bank.Masked_Alias} - {bank_name}" if not masked else m.bank.Masked_Alias,
            m.bank.Kelompok_KBMI,
            _score(m) / 100.0,
            m.compliance_status,
            ", ".join(failed_params) if failed_params else "Nihil (Lolos Semua)",
            ticket_str,
            tindak_lanjut,
        ]

        for col_idx, val in enumerate(vals, start=1):
            cell = ws3.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            if row_idx % 2 == 1:
                cell.fill = zebra_fill

            if col_idx in [1, 2, 4]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in [3, 7, 8]:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif col_idx == 5:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.number_format = "0.0%"
                cell.font = font_bold
            elif col_idx == 6:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = font_bold
                if val == "MEMENUHI":
                    cell.font = font_pass
                    cell.fill = light_emerald_fill
                elif val == "DATA_BELUM_LENGKAP":
                    cell.font = font_amber
                    cell.fill = light_amber_fill
                else:
                    cell.font = font_fail
                    cell.fill = light_rose_fill
            elif col_idx == 9:
                cell.alignment = Alignment(horizontal="left", vertical="center")
                cell.font = font_bold
                if "Teguran" in val:
                    cell.font = font_fail
                elif "Pembinaan" in val:
                    cell.font = font_amber
                else:
                    cell.font = font_pass

    # Auto-fit columns
    for col in ws3.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = max(max_len + 3, 11)
    ws3.column_dimensions["C"].width = 28
    ws3.column_dimensions["I"].width = 42

    excel_io = io.BytesIO()
    wb.save(excel_io)
    excel_io.seek(0)
    return excel_io


# ==============================================================================
# 3. GENERATOR STRUCTURED PREVIEW JSON (UNTUK LIVE PREVIEW FRONTEND)
# ==============================================================================
def get_memo_preview_data(db: Session, memo_type: str = "m02", masked: bool = False) -> Dict[str, Any]:
    """
    Menghasilkan data struktural memorandum untuk ditampilkan secara real-time
    pada Live Preview di UI sebelum diunduh dalam format .docx atau .xlsx.
    """
    memo_type = memo_type.lower()
    period = get_active_period(db)
    triwulan_str = period.Triwulan if period else "2026-Q2"
    stage_str = period.Active_Threshold_Stage if period else "EARLY"

    matrices = (
        db.query(BankScoreMatrix)
        .join(MasterBank)
        .filter(BankScoreMatrix.period_id == period.id)
        .order_by(MasterBank.Bank_ID.asc())
        .all()
    )

    tickets = (
        db.query(FindingTicket)
        .join(MasterBank)
        .filter(FindingTicket.period_id == period.id)
        .order_by(FindingTicket.Finding_ID.asc())
        .all()
    )

    full_pass_banks = [m for m in matrices if m.compliance_status == "MEMENUHI"]
    tidak_memenuhi_banks = [m for m in matrices if m.compliance_status == "TIDAK_MEMENUHI"]
    belum_lengkap_banks = [m for m in matrices if m.compliance_status == "DATA_BELUM_LENGKAP"]

    if memo_type == "m02":
        return {
            "type": "M.02",
            "title": "MEMORANDUM LAPORAN EVALUASI TRIWULANAN (M.02)",
            "nomor": f"MEMO-{datetime.utcnow().year}/DPPK/PUVA/M.02/084",
            "kepada": "Yth. Kepala Departemen Pengembangan Pasar Keuangan (DPPK)",
            "dari": "Tim Evaluasi & Pengawasan Pasar Uang dan Pasar Valas (DPPK)",
            "tanggal": datetime.utcnow().strftime("%d %B %Y"),
            "sifat": "RAHASIA / SEGERA",
            "lampiran": "3 (tiga) berkas matriks evaluasi",
            "perihal": f"Laporan Hasil Evaluasi Triwulanan Kewajiban Dealer Utama PUVA Periode {triwulan_str} dan Permohonan Persetujuan Hasil Rekonsiliasi",
            "period": triwulan_str,
            "stage": stage_str,
            "default_narration": (
                f"Berdasarkan hasil perhitungan rule engine PADG No. 23 Tahun 2024 untuk periode {triwulan_str}, "
                f"tercatat {len(full_pass_banks)} bank memenuhi seluruh kewajiban PUVA (skor 60%), "
                f"{len(tidak_memenuhi_banks)} bank tidak memenuhi minimal satu kewajiban, dan {len(belum_lengkap_banks)} bank "
                f"dengan data evaluasi yang belum lengkap. {TINDAK_LANJUT_PENDING}"
            ),
            "summary_stats": {
                "total_banks": len(matrices),
                "full_pass": len(full_pass_banks),
                "tidak_memenuhi": len(tidak_memenuhi_banks),
                "data_belum_lengkap": len(belum_lengkap_banks),
            },
            "findings": [
                {
                    "finding_id": t.Finding_ID,
                    "bank_id": t.Bank_ID,
                    "bank_name": t.bank.Masked_Alias if masked else t.bank.Nama_Resmi_Bank,
                    "parameter": t.Parameter_Code,
                    "nilai_bi": t.Nilai_Rekap_BI,
                    "klaim_bank": t.Nilai_Klaim_Bank or "Belum diajukan",
                    "ai_recom": t.AI_Recommendation_Status or "PENDING",
                    "decision": t.BI_Decision_Status,
                }
                for t in tickets
            ],
        }
    else:
        return {
            "type": "M.01",
            "title": "MEMORANDUM PENGANTAR HASIL EVALUASI KE DSMM (M.01)",
            "nomor": f"MEMO-{datetime.utcnow().year}/DPPK/PUVA/M.01/085",
            "kepada": "Yth. Kepala Departemen Surveilans & Manajemen Risiko (DSMM)",
            "dari": "Kepala Departemen Pengembangan Pasar Keuangan (DPPK)",
            "tanggal": datetime.utcnow().strftime("%d %B %Y"),
            "sifat": "RAHASIA / SEGERA",
            "lampiran": "3 (tiga) berkas matriks evaluasi",
            "perihal": f"Penyampaian Hasil Akhir Evaluasi Pemenuhan Kewajiban Dealer Utama PUVA Periode {triwulan_str} untuk Pembinaan & Pengawasan Perbankan",
            "period": triwulan_str,
            "stage": stage_str,
            "default_narration": (
                f"Menindaklanjuti ketentuan Pasal 28 PADG No. 23 Tahun 2024, Departemen Pengembangan Pasar Keuangan (DPPK) "
                f"menyampaikan hasil akhir evaluasi 21 Dealer Utama PUVA periode {triwulan_str} pasca-rekonsiliasi. "
                f"Hasil evaluasi memuat daftar bank yang memenuhi seluruh kewajiban PUVA dan bank yang tidak memenuhi "
                f"minimal satu kewajiban. {TINDAK_LANJUT_PENDING}"
            ),
            "categories": {
                "lulus": [m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank for m in full_pass_banks],
                "tidak_memenuhi": [
                    {
                        "bank_name": m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank,
                        "score": _score(m),
                        "notes": "Tidak memenuhi: " + ", ".join(_failed_params(m)),
                    }
                    for m in tidak_memenuhi_banks
                ],
                "data_belum_lengkap": [
                    {
                        "bank_name": m.bank.Masked_Alias if masked else m.bank.Nama_Resmi_Bank,
                        "score": _score(m),
                        "notes": "Belum ada data: " + ", ".join(_missing_params(m)),
                    }
                    for m in belum_lengkap_banks
                ],
            },
        }
