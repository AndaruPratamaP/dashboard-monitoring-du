"""
AI Evidence Checker Service untuk Rekonsiliasi DU PUVA
Menggunakan Gemini API (REST) dan Fallback Deterministic Rule Analyzer
berdasarkan ketentuan mutlak PADG No. 23 Tahun 2024 & PBI No. 6 Tahun 2024.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import re
import requests

from services.rule_engine import THRESHOLDS, canonical_code, parse_claim_percent

logger = logging.getLogger("ai_reconciliation")

SYSTEM_PROMPT = """
Anda adalah AI Regulatory Evidence Verification Assistant untuk Departemen Pengembangan Pasar Keuangan (DPPK) Bank Indonesia.
Tugas Anda adalah memvalidasi sanggahan dan bukti dokumen yang diajukan oleh bank Dealer Utama (DU) PUVA terhadap temuan evaluasi kuartalan berdasarkan ketentuan mutlak PADG No. 23 Tahun 2024 dan PBI No. 6 Tahun 2024.

ATURAN BISNIS & KRITERIA VALIDASI MUTLAK:
1. B1 (Kuotasi Repo): Setiap hari kerja; spread maksimal 5 bps (tenor O/N) dan maksimal 20 bps (tenor 1W dan 1M).
2. B2 (Kuotasi SRBI): Setiap hari kerja; seri SRBI tradable; spread kuotasi maksimal 20 bps.
3. B3 (Kuotasi OIS): Setiap hari kerja; kuotasi lengkap tenor 1M dan 3M; spread maksimal 20 bps. Kuotasi wajib tayang aktif di platform resmi pasar.
4. B4 (Counterparty Line Repo): Fasilitas aktif minimal 10 bank DU dan 10 bank Non-DU pada akhir periode cut-off. Rasio pemenuhan = (min(DU/10, 1)*50% + min(NonDU/10, 1)*50%).
5. B5 (Counterparty Line OIS): Fasilitas aktif minimal 10 bank DU pada akhir periode cut-off.
6. B6 (Penjualan SRBI Sekunder): Minimal 30% dari volume win lelang pasar perdana dengan status SETTLED sebelum cut-off akhir periode.
7. B7a (Transaksi Repo Sekunder): Transaksi repo wajib memiliki tenor minimal 2 minggu (>= 14 hari). Transaksi dengan tenor di bawah 14 hari (misal 7 hari) GUGUR dan tidak dapat dihitung. Minimal dilakukan pada 60% hari kerja (36 hari kerja).
8. B7b (Transaksi SRBI Sekunder): Transaksi SRBI wajib memiliki sisa jangka waktu minimal 3 bulan pada minimal 60% hari kerja (36 hari kerja).
9. B8 (Matchmaking OIS): Kehadiran dan kuotasi aktif pada tenor 1M dan 3M pada setiap sesi matchmaking resmi (6 periode).

Pedoman Analisis:
- Periksa kesesuaian klaim bank dan bukti dokumen terhadap batas-batas kuantitatif regulasi di atas.
- Berikan status rekomendasi: RECOMMEND_APPROVE, RECOMMEND_REJECT, atau PARTIAL_REVIEW.
- Format output JSON:
  {
    "recommendation_status": "RECOMMEND_APPROVE" | "RECOMMEND_REJECT" | "PARTIAL_REVIEW",
    "confidence_score": 0.95,
    "regulatory_reference": "PADG No. 23/2024 Pasal ...",
    "analysis_text": "Penjelasan institusional mendalam tentang alasan persetujuan atau penolakan, mengacu pada angka dan bukti",
    "suggested_action": "Tindakan yang disarankan kepada petugas BI"
  }
"""


VALID_STATUSES = {"RECOMMEND_APPROVE", "RECOMMEND_REJECT", "PARTIAL_REVIEW"}


def run_deterministic_analyzer(
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
    Fallback Deterministic Rule Analyzer.

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
        f"Analyzer deterministik tidak membaca isi berkas '{file_bukti_name or '-'}', sehingga kebenaran klaim "
        f"harus dicocokkan manual dengan data sumber.",
        "Petugas BI memverifikasi isi berkas bukti terhadap data sumber sebelum memutuskan.",
    )


def analyze_dispute_with_ai(
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
    Eksekusi analisis AI untuk verifikasi bukti sanggahan:
    Mencoba memanggil Google Gemini API via REST dengan fallback model chain dan timeout ketat.
    Jika API gagal atau tidak tersedia, otomatis menggunakan Fallback Deterministic Rule Analyzer.
    """
    api_key = os.environ.get("GEMINI_API_KEY")

    if api_key:
        # Prioritas model: gunakan GEMINI_MODEL jika didefinisikan, atau default ke gemini-3.5-flash
        custom_model = os.environ.get("GEMINI_MODEL")
        candidate_models = [custom_model] if custom_model else ["gemini-3.5-flash", "gemini-3.8-flash"]

        user_prompt = f"""
Parameter Evaluasi: {parameter_code}
Bank Dealer Utama: {bank_alias} (Nama resmi telah disamarkan demi privasi perbankan)
Tahap Threshold Aktif: {stage}
Data Rekap Awal BI: {rekap_bi}
Klaim Sanggahan Bank: {klaim_bank or '[Tidak ada klaim angka spesifik]'}
Alasan Resmi Sanggahan Bank: {alasan_sanggahan or '[Tidak ada uraian alasan]'}
Nama Berkas Bukti: {file_bukti_name or '[Tidak melampirkan berkas bukti]'} (CATATAN: isi berkas TIDAK disertakan; jangan berasumsi isi berkas membuktikan klaim)
Rincian Catatan Transaksi Tidak Memenuhi Syarat:
{json.dumps(failed_details or [], indent=2)}

Lakukan analisis kepatuhan regulasi terhadap PADG No. 23/2024 dan berikan rekomendasi output dalam format JSON sesuai spesifikasi system prompt.
"""

        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                # Timeout ringkas 4.0 detik agar UI responsif dan tidak hang jika server Google overload (503)
                resp = requests.post(url, json=payload, headers=headers, timeout=4.0)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            raw_text = parts[0]["text"]
                            parsed = json.loads(raw_text)
                            rec = str(parsed.get("recommendation_status", "")).upper()
                            if rec not in VALID_STATUSES:
                                rec = "PARTIAL_REVIEW"
                            return {
                                "recommendation_status": rec,
                                "confidence_score": float(parsed.get("confidence_score", 0.90)),
                                "regulatory_reference": parsed.get("regulatory_reference", "PADG No. 23/2024"),
                                "analysis_text": parsed.get("analysis_text", raw_text),
                                "suggested_action": parsed.get("suggested_action", "Verifikasi petugas"),
                                "engine_used": f"Gemini AI ({model})",
                            }
                else:
                    logger.warning(f"Gemini API model {model} returned HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                logger.warning(f"Gemini API call to {model} failed: {e}")

    # Fallback ke Deterministic Rule Engine bila API key tidak ada, offline, atau Google API 503/timeout
    result = run_deterministic_analyzer(
        finding_id=finding_id,
        bank_alias=bank_alias,
        parameter_code=parameter_code,
        rekap_bi=rekap_bi,
        klaim_bank=klaim_bank,
        alasan_sanggahan=alasan_sanggahan,
        file_bukti_name=file_bukti_name,
        failed_details=failed_details,
        stage=stage,
    )
    result["engine_used"] = "PADG Deterministic Rule Engine (Automated Fallback)"
    return result
