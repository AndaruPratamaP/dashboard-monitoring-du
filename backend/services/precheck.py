"""
Pre-check PADG: pemeriksaan deterministik atas sanggahan bank (pengganti jalur AI/Gemini).

Pre-check hanya menilai hal yang bisa diverifikasi secara mekanis (angka klaim vs threshold,
aturan tenor mutlak, kelengkapan bukti). Pre-check tidak membaca isi dokumen bukti dan tidak pernah
menyetujui sendiri: sanggahan yang lolos pemeriksaan mekanis diteruskan ke petugas BI.
"""

from typing import Any, Dict, Optional

ENGINE_NAME = "Pre-check PADG (deterministik)"


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
