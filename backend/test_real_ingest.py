"""
Golden test Sprint 1: parser data ril (B6 Rasio SRBI, B8 MM OIS) dibandingkan dengan rekap BI
pada file kerja TW III 2026. Dilewati bila folder dataset ril tidak ada (tidak di-commit ke repo).

Jalankan dengan database sementara, mis.:
    DATABASE_PATH=/tmp/test.db python test_real_ingest.py
"""
import os
import sys

from fastapi.testclient import TestClient

from main import app
from services.real_ingest import default_dataset_dir

if not os.path.isdir(default_dataset_dir()):
    print(f"SKIP: folder dataset ril tidak ditemukan ({default_dataset_dir()})")
    sys.exit(0)

with TestClient(app) as client:
    # --- B6: rasio penjualan SRBI sekunder vs win perdana (kumulatif triwulan)
    r = client.post("/api/ingest/srbi-ratio")
    assert r.status_code == 200, r.text
    b6 = r.json()
    assert b6["period"]["triwulan"] == "2026-Q3"
    assert b6["period"]["working_days_count"] == 64, b6["period"]["working_days_count"]
    assert b6["unknown_banks"] == [], b6["unknown_banks"]
    assert b6["crosscheck"]["available"] and b6["crosscheck"]["differences"] == [], b6["crosscheck"]
    jatim = next(x for x in b6["per_bank"] if x["bank_id"] == "DU-18")
    assert abs(jatim["detail"]["rasio_penjualan_pct"] - 86.77) < 0.01, jatim
    print("B6 OK: 21 bank cocok dengan rekap BI; 64 hari kerja TW III")

    # --- B8: partisipasi matchmaking OIS (1b & 3b per sesi)
    r = client.post("/api/ingest/mm-ois")
    assert r.status_code == 200, r.text
    b8 = r.json()
    assert b8["period"]["mm_ois_sessions_count"] == 25
    assert b8["unknown_banks"] == [], b8["unknown_banks"]
    rates = {x["bank_id"]: x["rate"] for x in b8["per_bank"]}
    assert rates["DU-07"] == 96.0 and rates["DU-15"] == 96.0, rates  # Maybank 21 Jul, BOC HK 10 Sep (3b)
    assert all(v == 100.0 for k, v in rates.items() if k not in ("DU-07", "DU-15")), rates
    # Rekap BI (pasca konfirmasi) mencatat kedua sesi tsb sebagai "Ya": selisih harus terdeteksi tepat 2
    diffs = {(d["bank_id"], d["tanggal"]) for d in b8["crosscheck"]["differences"]}
    assert diffs == {("DU-07", "2026-07-21"), ("DU-15", "2026-09-10")}, diffs
    print("B8 OK: 25 sesi; 2 selisih vs rekap BI terdeteksi (Maybank 21 Jul, BOC HK 10 Sep)")

    # --- Matriks periode ril: parameter tanpa sumber data = None, bukan 0, dan tidak menjadi temuan
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert m["DU-07"]["period"] == "2026-Q3"
    assert m["DU-07"]["raw_metrics"]["B1"] is None and m["DU-07"]["raw_metrics"]["B8"] == 96.0
    assert m["DU-07"]["compliance_status"] == "DATA_BELUM_LENGKAP"
    assert m["DU-07"]["total_puva_score"] == 17.5  # B6 7.5 + B8 10
    assert client.get("/api/findings").json() == []
    print("Matriks OK: B6+B8 terisi, parameter lain 'belum ada data', tanpa temuan palsu")

print("\nALL REAL-DATA INGEST TESTS PASSED")
