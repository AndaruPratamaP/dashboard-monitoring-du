"""
Unit test yang tidak memerlukan dataset ril: aturan skor, perhitungan ulang sanggahan, pre-check,
format kalimat dokumen, dan inisialisasi database kosong.
"""
from types import SimpleNamespace

import pytest

from services import documents
from services.precheck import precheck_item
from services.replies import needs_escalation, rate_with_overrides
from services.rule_engine import MAX_PUVA_SCORE, THRESHOLDS, compute_matrix_scores


# --- Rule engine ------------------------------------------------------------------------------
def test_skor_maksimum_60_tanpa_om():
    assert MAX_PUVA_SCORE == 60.0


def test_threshold_early_dan_status():
    full = {c: 100.0 for c in ("B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8")}
    s = compute_matrix_scores(full, stage="EARLY")
    assert s["total_puva_score"] == 60.0 and s["compliance_status"] == "MEMENUHI"
    s = compute_matrix_scores({**full, "B3": 15.62}, stage="EARLY")  # Deutsche OIS
    assert s["b3_passed"] is False and s["total_puva_score"] == 57.5 and s["compliance_status"] == "TIDAK_MEMENUHI"
    s = compute_matrix_scores({**full, "B1": None}, stage="EARLY")
    assert s["compliance_status"] == "DATA_BELUM_LENGKAP"
    assert THRESHOLDS["EARLY"]["B1"] == 80.0 and THRESHOLDS["EARLY"]["B4"] == 50.0


# --- Sanggahan per tanggal ----------------------------------------------------------------------
def _item(tanggal, tenor, status="DITERIMA", round_no=1, last_round=1):
    return SimpleNamespace(Tanggal=tanggal, Tenor=tenor, Status=status, Round_No=round_no, Last_Round=last_round,
                           Klaim_Bank_JSON=None)


def test_rate_dengan_sanggahan_kuotasi():
    payload = {"dates": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06"],
               "3b": [10, None, 50, 15], "12b": [10, None, 15, 15]}
    assert rate_with_overrides("bbg-ois", payload, [])[0] == 50.0
    # 2 Jul: kedua tenor kosong -> hari baru memenuhi bila keduanya diterima
    assert rate_with_overrides("bbg-ois", payload, [_item("2026-07-02", "3b")])[0] == 50.0
    rate, det = rate_with_overrides("bbg-ois", payload, [_item("2026-07-02", "3b"), _item("2026-07-02", "12b"),
                                                         _item("2026-07-03", "3b")])
    assert rate == 100.0 and det == {"valid_days": 4, "total_days": 4}


def test_rate_dengan_sanggahan_transaksi_dan_mm():
    p = {"dates": [f"2026-07-{d:02d}" for d in range(1, 11)], "volume": [1] * 5 + [0] * 5}
    assert rate_with_overrides("repo-2m", p, [])[0] == 83.33  # 5 dari target 6 hari (60% x 10)
    assert rate_with_overrides("repo-2m", p, [_item("2026-07-06", None)])[0] == 100.0
    mm = {"sessions": ["2026-07-02", "2026-07-09"], "1b": ["Ya", "Ya"], "3b": ["Ya", "Tidak"]}
    assert rate_with_overrides("mm-ois", mm, [])[0] == 50.0
    assert rate_with_overrides("mm-ois", mm, [_item("2026-07-09", "3b")])[0] == 100.0


def test_eskalasi_setelah_dua_ronde():
    assert not needs_escalation(_item("2026-07-01", "any", "OPEN", 1, 1))
    assert needs_escalation(_item("2026-07-01", "any", "OPEN", 1, 2))
    assert not needs_escalation(_item("2026-07-01", "any", "DITOLAK", 1, 2))


def test_precheck_item():
    impact = {"param": "B2", "rate_now": 98.44, "rate_if_accepted": 100.0, "threshold": 80.0, "same_day": 1}
    r = precheck_item({"nilai_bi": 85.0, "nilai_bank": 10.0, "keterangan": "bukti: Kuotasi SRBI 13 Juli.jpeg"}, 20.0, impact)
    assert r["label"] == "VERIFIKASI_BUKTI"
    r = precheck_item({"nilai_bi": None, "nilai_bank": "√", "keterangan": ""}, 20.0, impact)
    assert r["label"] == "MINTA_BUKTI"


# --- Kalimat dokumen ---------------------------------------------------------------------------
@pytest.mark.parametrize("n, text", [(2, "dua"), (11, "sebelas"), (15, "lima belas"), (19, "sembilan belas"),
                                     (21, "dua puluh satu"), (100, "seratus"), (123, "seratus dua puluh tiga")])
def test_terbilang(n, text):
    assert documents.terbilang(n) == text


def test_daftar_tanggal_format_lampiran():
    assert documents.daftar_tanggal(["2026-08-06", "2026-07-16"]) == "16 Juli 2026; dan\n6 Agustus 2026"
    assert documents.daftar_tanggal(["2026-07-01", "2026-07-02", "2026-07-22"]) == "1, 2, dan 22 Juli 2026"
    assert documents.gabung(["Deutsche", "HSBC"]) == "Deutsche dan HSBC"


def test_format_nilai_matriks():
    col = {"kind": "pct", "target": 100.0}
    assert documents.fmt_value(col, 15.625) == "16%" and documents.fmt_value(col, 99.7) == "99%"
    assert documents.fmt_value({"kind": "count", "target": 10.0}, 7) == "7"
    after = {c["key"]: documents.target_after(c, "EARLY") for c in documents.COLUMNS}
    assert after["srbi"] == 80.0 and after["trx_repo"] == 48.0 and after["trx_sekunder"] == 24.0 and after["ctp_ois_du"] == 5.0


def test_quote_notes_mengelompokkan_tenor():
    per_tenor = {"3b": {"rate": 96.9, "kosong": ["2026-07-16", "2026-08-06"], "satu_sisi": [], "spread": []},
                 "12b": {"rate": 96.9, "kosong": ["2026-07-16", "2026-08-06"], "satu_sisi": [], "spread": []}}
    notes, failed = documents._quote_notes("bbg-ois", per_tenor)
    assert notes == ["Tidak terdapat kuotasi OIS tenor 3 bulan dan 12 bulan pada tanggal:\n16 Juli 2026; dan\n6 Agustus 2026."]
    assert failed == ["3b", "12b"]


# --- Database kosong (tanpa data sample) -------------------------------------------------------
def test_database_baru_hanya_master_bank(client):
    banks = client.get("/api/banks").json()
    assert len(banks) == 21
    r = client.get("/api/documents/preview")
    assert r.status_code in (200, 400)  # 400 bila belum ada data ril pada sesi test ini
