"""
Pre-check PADG: pemeriksaan deterministik atas sanggahan bank (pengganti jalur AI/Gemini).

Pre-check hanya menilai hal yang bisa diverifikasi secara mekanis (angka klaim vs threshold,
aturan tenor mutlak, kelengkapan bukti). Pre-check tidak membaca isi dokumen bukti dan tidak pernah
menyetujui sendiri: sanggahan yang lolos pemeriksaan mekanis diteruskan ke petugas BI.
"""

import re
from typing import Any, Dict, Optional

from services.rule_engine import THRESHOLDS, canonical_code, parse_claim_percent

ENGINE_NAME = "Pre-check PADG (deterministik)"

VALID_STATUSES = {"RECOMMEND_APPROVE", "RECOMMEND_REJECT", "PARTIAL_REVIEW"}


def precheck_dispute(
    finding_id: str,
    bank_alias: str,
    parameter_code: str,
    rekap_bi: str,
    klaim_bank: Optional[str],
    alasan_sanggahan: Optional[str],
    file_bukti_name: Optional[str],
    failed_details: Optional[list] = None,
    stage: str = "EARLY",
) -> Dict[str, Any]:
    """
    Pre-check tiket temuan per parameter (alur lama berbasis klaim persentase).

    Hanya menilai hal yang dapat diverifikasi secara mekanis dari data yang tersedia
    (angka klaim vs threshold, aturan tenor mutlak, kelengkapan berkas). Analyzer ini
    TIDAK membaca isi dokumen bukti, sehingga tidak pernah merekomendasikan APPROVE:
    sanggahan yang lolos pemeriksaan mekanis diteruskan sebagai PARTIAL_REVIEW untuk
    diverifikasi petugas BI.
    """
    p_code = canonical_code(parameter_code)
    st = stage.upper() if stage.upper() in THRESHOLDS else "EARLY"
    threshold = THRESHOLDS[st].get(p_code, 80.0)
    reason = alasan_sanggahan or ""
    claimed = parse_claim_percent(klaim_bank)
    details = failed_details or []

    def result(status: str, confidence: float, ref: str, text: str, action: str) -> Dict[str, Any]:
        return {
            "recommendation_status": status,
            "confidence_score": confidence,
            "regulatory_reference": ref,
            "analysis_text": f"{status}: {text}",
            "suggested_action": action,
        }

    # 1. Tidak ada uraian sanggahan maupun berkas bukti
    if not reason.strip() and not file_bukti_name:
        return result(
            "RECOMMEND_REJECT", 0.90, "PADG No. 23/2024 Ketentuan Umum",
            f"{bank_alias} belum menyampaikan alasan sanggahan maupun berkas bukti untuk parameter {p_code}.",
            "Tolak sanggahan atau minta bank melengkapi alasan dan bukti.",
        )

    # 2. Aturan tenor mutlak B7a: transaksi repo < 14 hari tidak dapat diakui.
    #    Jika selisih hari klaim bank vs rekap BI tidak melebihi jumlah tanggal transaksi
    #    bertenor < 14 hari yang dikeluarkan BI, sanggahan bergantung pada transaksi tsb.
    if p_code == "B7a":
        short_deals = [t for t in details if isinstance(t, dict) and (t.get("tenor_hari") or 99) < 14]
        short_dates = {t.get("tanggal") for t in short_deals}
        claim_days = re.search(r"(\d+)\s*/\s*(\d+)", klaim_bank or "")
        bi_days_m = re.search(r"(\d+)\s*/\s*\d+", rekap_bi or "")
        bi_pct = re.search(r"(\d+(?:\.\d+)?)\s*%", rekap_bi or "")
        bi_days = None
        if bi_days_m:
            bi_days = int(bi_days_m.group(1))
        elif bi_pct and claim_days:
            # Rekap hanya memuat persentase -> konversi ke hari memakai target hari pada klaim (mis. 72.22% x 36 = 26)
            bi_days = round(float(bi_pct.group(1)) * int(claim_days.group(2)) / 100.0)
        if short_dates and bi_days is not None and claim_days:
            gap = int(claim_days.group(1)) - bi_days
            if 0 < gap <= len(short_dates):
                return result(
                    "RECOMMEND_REJECT", 0.95, "PADG No. 23/2024 (tenor repo sekunder minimal 2 minggu)",
                    f"{bank_alias} mengklaim {claim_days.group(1)} hari valid, sedangkan rekap BI {bi_days} hari. "
                    f"Selisih {gap} hari tidak melebihi {len(short_dates)} tanggal transaksi repo bertenor < 14 hari "
                    f"({len(short_deals)} transaksi, tenor terpendek {min(t.get('tenor_hari') for t in short_deals)} hari) "
                    f"yang dikeluarkan dari perhitungan BI. Transaksi tersebut tidak dapat diakui.",
                    "Tolak sanggahan dan pertahankan nilai rekap BI.",
                )

    # 3. Angka klaim bank sendiri masih di bawah threshold aktif
    if claimed is not None and claimed < threshold:
        return result(
            "RECOMMEND_REJECT", 0.90, f"PADG No. 23/2024 (threshold {st})",
            f"Nilai klaim {bank_alias} ({claimed:.2f}%) masih di bawah ambang batas {p_code} tahap {st} "
            f"({threshold:.1f}%). Walaupun klaim diterima seluruhnya, parameter tetap tidak terpenuhi.",
            "Tolak sanggahan; status temuan tidak berubah meskipun klaim diterima.",
        )

    # 4. Lolos pemeriksaan mekanis -> wajib verifikasi berkas oleh petugas
    notes = []
    if claimed is None:
        notes.append("klaim bank tidak memuat angka persentase yang dapat diverifikasi")
    else:
        notes.append(f"klaim {claimed:.2f}% akan melampaui threshold {st} ({threshold:.1f}%) bila terbukti")
    if not file_bukti_name:
        notes.append("bank tidak melampirkan berkas bukti")
    if details:
        notes.append(f"data BI mencatat {len(details)} catatan transaksi/kuotasi tidak memenuhi syarat")
    return result(
        "PARTIAL_REVIEW", 0.50, "PADG No. 23/2024",
        f"Sanggahan {bank_alias} pada parameter {p_code} (rekap BI: {rekap_bi}): " + "; ".join(notes) + ". "
        f"Pre-check tidak membaca isi berkas '{file_bukti_name or '-'}', sehingga kebenaran klaim "
        f"harus dicocokkan manual dengan data sumber.",
        "Petugas BI memverifikasi isi berkas bukti terhadap data sumber sebelum memutuskan.",
    )


def precheck_item(item: Dict[str, Any], max_bps: Optional[float], impact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pre-check satu item sanggahan per tanggal. Mengembalikan label dan poin pemeriksaan:
    - MINTA_BUKTI     : bank tidak memberi keterangan maupun bukti
    - VERIFIKASI_BUKTI: ada keterangan/bukti -> petugas mencocokkan dengan data sumber
    Ditambah dampak bila diterima (nilai parameter sebelum/sesudah dan perubahan status).
    """
    points = [f"Rekap BI: {item['nilai_bi']}; isian bank: {item['nilai_bank']}."]
    spread = None
    try:
        spread = float(str(item.get("nilai_bank") or "").split()[0])
    except ValueError:
        pass
    if max_bps is not None and spread is not None:
        points.append(f"Spread klaim {spread:g} bps {'<=' if spread <= max_bps else '>'} batas {max_bps:g} bps.")
    ket = (item.get("keterangan") or "").strip()
    has_evidence = "bukti:" in ket.lower()
    if not ket:
        label = "MINTA_BUKTI"
        points.append("Bank tidak menyertakan keterangan atau bukti; minta bukti (screenshot Bloomberg/VCON/konfirmasi transaksi).")
    else:
        label = "VERIFIKASI_BUKTI"
        points.append("Bukti terlampir; cocokkan isi bukti dengan tanggal & tenor." if has_evidence
                      else "Bank memberi keterangan tanpa file bukti terpisah; cek lampiran di workbook balasan.")
    if impact.get("rate_now") is not None and impact.get("rate_if_accepted") is not None:
        now, after, thr = impact["rate_now"], impact["rate_if_accepted"], impact["threshold"]
        flip = now < thr <= after
        extra = impact.get("same_day", 1) - 1
        points.append(
            f"Jika diterima{f' (bersama {extra} tenor lain pada tanggal ini)' if extra > 0 else ''}: "
            f"{impact['param']} {now:.2f}% -> {after:.2f}% "
            + ("(menjadi MEMENUHI threshold)." if flip else
               "(status tetap memenuhi)." if now >= thr else f"(masih di bawah threshold {thr:.0f}%).")
        )
    return {"label": label, "engine": ENGINE_NAME, "points": points}
