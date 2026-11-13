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

    def ingest(source):
        r = client.post(f"/api/ingest/{source}")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["period"]["triwulan"] == "2026-Q3" and j["unknown_banks"] == [], (source, j["unknown_banks"])
        below = {x["bank_id"]: x["rate"] for x in j["per_bank"] if x["rate"] is not None and x["rate"] < 100}
        diffs = {(d["bank_id"], d.get("tanggal")) for d in j["crosscheck"]["differences"]}
        return j, below, diffs

    # --- B7a / B7b: rekap transaksi harian, 60% dari 64 hari kerja = 38 hari
    for src in ("repo-2m", "srbi-3b"):
        j, below, diffs = ingest(src)
        assert below == {} and diffs == set(), (src, below, diffs)
        assert all(x["detail"]["target_days"] == 38 for x in j["per_bank"]), src
    print("B7a/B7b OK: 21 bank >= 60% hari kerja, frekuensi sama dengan rekap BI")

    # --- B1 Repo: cocok penuh dengan rekap BI; temuan M.01 (Deutsche 21 Jul 210 bps, HSBC 1 bulan 8 Jul & 27 Agu)
    j, below, diffs = ingest("bbg-repo")
    assert below == {"DU-01": 96.88, "DU-14": 98.44, "DU-16": 96.88}, below
    assert diffs == set(), diffs
    dbank = next(x for x in j["per_bank"] if x["bank_id"] == "DU-12")
    assert dbank["detail"]["sumber"].startswith("sheet manual"), dbank  # DBS: sheet DBSI_ref
    print("B1 OK: Repo cocok 100% dengan rekap BI")

    # --- B2 SRBI: spread maksimum antar seri (BTN 13 Jul 85 bps); HSBC 16 hari tanpa kuotasi (75%)
    j, below, diffs = ingest("bbg-srbi")
    assert below["DU-16"] == 75.0 and below["DU-19"] == 98.44 and below["DU-01"] == 96.88, below
    assert ("DU-19", "2026-07-13") not in diffs  # BTN 85 bps sama dengan rekap BI
    assert {b for b, _ in diffs} == {"DU-01", "DU-14"}, diffs  # BRI 8 Jul & Deutsche: dikoreksi BI pasca-konfirmasi
    print(f"B2 OK: HSBC 75%, BTN 13 Jul 85 bps; {len(diffs)} selisih pasca-konfirmasi (BRI, Deutsche)")

    # --- B3 OIS: BCA kosong 16 Jul & 6 Agu; Deutsche dinilai dari rekap BI (ticker Bloomberg invalid)
    j, below, diffs = ingest("bbg-ois")
    assert below == {"DU-06": 96.88, "DU-14": 15.62, "DU-21": 98.44}, below
    assert diffs == {("DU-21", "2026-07-14")}, diffs  # Mega 14 Jul dikoreksi BI
    assert {n["bank_id"] for n in j["source_notes"]} == {"DU-12", "DU-14"}, j["source_notes"]
    print("B3 OK: BCA 2 hari, Deutsche 15,62%, 1 selisih (Mega 14 Jul)")

    # --- Matriks akhir: hanya B4/B5 (counterparty line) yang belum ada data.
    # Temuan = Deutsche OIS dan HSBC SRBI, sama dengan lampiran M.01 BI.
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert all(row["raw_metrics"]["B4"] is None and row["raw_metrics"]["B1"] is not None for row in m.values())
    assert m["DU-14"]["compliance_status"] == "TIDAK_MEMENUHI" and m["DU-14"]["total_puva_score"] == 47.5
    assert m["DU-16"]["compliance_status"] == "TIDAK_MEMENUHI"
    assert m["DU-01"]["compliance_status"] == "DATA_BELUM_LENGKAP" and m["DU-01"]["total_puva_score"] == 50.0
    findings = sorted(f["finding_id"] for f in client.get("/api/findings").json())
    assert len(findings) == 2 and findings[0].endswith("DU14-B3") and findings[1].endswith("DU16-B2"), findings
    print("Matriks akhir OK: temuan = Deutsche B3 & HSBC B2 (sesuai M.01); B4/B5 menunggu data")

print("\nALL REAL-DATA INGEST TESTS PASSED")
