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
    print("Matriks OK: temuan = Deutsche B3 & HSBC B2 (sesuai M.01); B4/B5 menunggu data")

    # --- B4/B5 Counterparty line: workbook kiriman BI + balasan bank
    r = client.post("/api/counterparty/ingest")
    assert r.status_code == 200, r.text
    cp = r.json()
    rows = {x["bank_id"]: x for x in cp["per_bank"]}
    assert all(x["B4"] and x["B5"] for x in rows.values()), [k for k, x in rows.items() if not (x["B4"] and x["B5"])]
    assert rows["DU-14"]["B5"]["line_du"] == 7 and rows["DU-08"]["B5"]["line_du"] == 6  # M.01: Deutsche 7, Panin 6
    assert {k for k, x in rows.items() if x["B5"]["rate"] < 100} == {"DU-08", "DU-14"}
    assert all(x["B4"]["rate"] == 100.0 for x in rows.values())
    assert any("password" in s["alasan"] for s in cp["skipped"])  # balasan BCA/UOB terenkripsi dilaporkan, tidak diam-diam diabaikan
    print("B4/B5 OK: Panin 6 & Deutsche 7 line OIS DU (sesuai M.01); file terenkripsi dilaporkan")

    # Koreksi petugas: tandai satu line OIS Panin 'Dihapus' -> B5 turun, lalu kembalikan
    all_lines = client.get("/api/counterparty/DU-08").json()
    assert len({(l["instrument"], l["sandi"]) for l in all_lines}) == len(all_lines), "line ganda"
    lines = [l for l in all_lines if l["instrument"] == "OIS" and l["is_du"]]
    r = client.patch(f"/api/counterparty/lines/{lines[0]['id']}", data={"status": "Dihapus"})
    assert r.status_code == 200 and r.json()["breakdown"]["B5"]["line_du"] == 5, r.text
    client.patch(f"/api/counterparty/lines/{lines[0]['id']}", data={"status": lines[0]["status"] or ""})

    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    statuses = {k: v["compliance_status"] for k, v in m.items()}
    assert {k for k, v in statuses.items() if v != "MEMENUHI"} == {"DU-14", "DU-16"}, statuses
    assert m["DU-14"]["total_puva_score"] == 57.5 and m["DU-01"]["total_puva_score"] == 60.0
    print("Matriks akhir OK: 9 parameter dari data ril; 19 Memenuhi, Deutsche & HSBC Tidak Memenuhi")

    # --- E5-1 Workbook konfirmasi: struktur template + isi sama dengan kiriman BI
    import io
    import openpyxl
    r = client.get("/api/confirmation/DU-14")
    assert r.status_code == 200 and "16. Deutsche Bank.xlsx" in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == [
        "Rasio SRBI Minimal 30%", "Transaksi Repo Minimal 2 Minggu", "Transaksi SRBI 3 Bulan", "Partisipasi MM OIS",
        "Kuotasi SRBI, Repo & OIS", "Counterparty Line Repo", "Counterparty Line OIS", "Index",
    ] and wb["Index"].sheet_state == "hidden"
    orig = openpyxl.load_workbook(os.path.join(default_dataset_dir(), "Konfirmasi Bank", "16. Deutsche Bank.xlsx"), data_only=True)

    def col_values(ws, date_col, val_col):
        out = {}
        for row in ws.iter_rows(values_only=True):
            if len(row) > val_col and hasattr(row[date_col], "year"):
                out[row[date_col].date() if hasattr(row[date_col], "date") else row[date_col]] = row[val_col]
        return out

    for sheet, dc, vc in (("Transaksi Repo Minimal 2 Minggu", 3, 4), ("Transaksi SRBI 3 Bulan", 3, 4),
                          ("Rasio SRBI Minimal 30%", 1, 2), ("Partisipasi MM OIS", 3, 5)):
        assert col_values(wb[sheet], dc, vc) == col_values(orig[sheet], dc, vc), sheet
    gen_ois = [row[2][:3] for row in wb["Counterparty Line OIS"].iter_rows(min_row=5, max_col=3, values_only=True) if row[2]]
    org_ois = [row[2][:3] for row in orig["Counterparty Line OIS"].iter_rows(min_row=5, max_col=3, values_only=True) if row[2]]
    assert gen_ois == org_ois, (gen_ois, org_ois)
    r = client.get("/api/confirmation-all")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    print("Workbook konfirmasi OK: 7 sheet + Index tersembunyi; isi sama dengan kiriman BI ke Deutsche")

    # --- Sprint 4: line setelah cut-off tetap dihitung tetapi ditandai
    bd = {x["bank_id"]: x for x in client.post("/api/counterparty/ingest").json()["per_bank"]}
    assert bd["DU-08"]["B4"]["line_non_du_setelah_cutoff"] == 1 and bd["DU-11"]["B5"]["line_du_setelah_cutoff"] == 1
    assert any(l["setelah_cutoff"] for l in client.get("/api/counterparty/DU-11").json())
    print("Counterparty OK: line setelah cut-off ditandai (Panin Repo non-DU, OCBC OIS DU) dan tetap dihitung")

    # --- Sprint 4: batas Repo 1 minggu menunggu konfirmasi (20 vs 10 bps) -> dilaporkan, TW III tidak terdampak
    j = client.post("/api/ingest/bbg-repo").json()
    assert j["threshold_notes"][0]["batas_alternatif_bps"] == 10.0 and j["threshold_notes"][0]["bank_terdampak"] == []
    print("Batas Repo 1W OK: sensitivitas 10 bps dilaporkan; tidak ada bank TW III yang berubah")

    # --- Sprint 4: impor balasan bank -> item sanggahan per tanggal (kasus nyata TW III)
    r = client.post("/api/replies/ingest")
    assert r.status_code == 200, r.text
    rep = {b["bank_id"]: b for b in r.json()["per_bank"]}
    assert rep["DU-06"]["manual"] and any(m["file"].endswith(".7z") for m in rep["DU-12"]["manual"])
    groups = {(g["bank_id"], g["parameter_code"]): g for g in client.get("/api/disputes").json()["groups"]}

    def dates(bank, param):
        return {(i["tanggal"], i["tenor"]) for i in groups[(bank, param)]["items"]}

    assert ("2026-07-13", "any") in dates("DU-19", "B2")                          # BTN SRBI 85 bps + bukti JPEG
    assert dates("DU-21", "B3") == {("2026-07-14", "3b"), ("2026-07-14", "12b")}  # Mega OIS + bukti PNG
    assert ("2026-09-10", "3b") in dates("DU-15", "B8")                           # BOC HK MM OIS
    assert {d for d, _ in dates("DU-07", "B8")} == {"2026-07-21"}                 # Maybank: dari nama file bukti PDF
    assert ("2026-07-21", "1w") in dates("DU-14", "B1")                           # Deutsche: catatan screenshot
    assert "bukti:" in groups[("DU-19", "B2")]["items"][0]["keterangan_bank"]
    n_items = sum(len(g["items"]) for g in groups.values())
    r = client.post("/api/replies/ingest")  # impor ulang: tidak menggandakan item
    assert sum(b["item"]["baru"] for b in r.json()["per_bank"]) == 0
    print(f"Balasan bank OK: {n_items} item (BTN, Mega, BOC HK, Maybank, Deutsche, BRI); file ber-password/7z ditandai manual")

    # Keputusan: terima BOC HK 10 Sep -> B8 100% (seperti rekap akhir BI), bertahan saat ingest ulang, bisa dibatalkan
    item = next(i for i in groups[("DU-15", "B8")]["items"] if i["tanggal"] == "2026-09-10")
    r = client.post(f"/api/disputes/{item['id']}/decide", data={"decision": "DITERIMA", "note": "sesuai log MM"})
    assert r.status_code == 200 and r.json()["parameter"]["rate"] == 100.0, r.text
    client.post("/api/ingest/mm-ois")
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert m["DU-15"]["raw_metrics"]["B8"] == 100.0 and m["DU-15"]["detail_metrics"]["B8"]["sanggahan_diterima"] == 1
    r = client.post(f"/api/disputes/{item['id']}/decide", data={"decision": "OPEN"})
    assert r.json()["parameter"]["rate"] == 96.0
    print("Keputusan OK: diterima -> B8 BOC HK 100%, bertahan saat ingest ulang, dapat dibatalkan")

    # Tiket temuan tertutup otomatis bila parameter lolos: HSBC B2 lewat sanggahan manual seluruh hari gugur
    t = next(x for x in client.get("/api/findings").json() if x["finding_id"].endswith("DU16-B2"))
    assert t["bi_decision_status"] == "OPEN"
    for d in [f["tanggal"] for f in t["detail_transaksi_gugur"]]:
        r = client.post("/api/disputes/manual", data={"bank_id": "DU-16", "source": "bbg-srbi", "tanggal": d, "keterangan": "uji"})
        assert r.status_code == 200, r.text
    ids = [i["id"] for g in client.get("/api/disputes?bank_id=DU-16").json()["groups"] for i in g["items"]]
    for i in ids:
        client.post(f"/api/disputes/{i}/decide", data={"decision": "DITERIMA"})
    t = next(x for x in client.get("/api/findings").json() if x["finding_id"].endswith("DU16-B2"))
    assert t["bi_decision_status"] == "CLOSED", t["bi_decision_status"]
    for i in ids:
        client.post(f"/api/disputes/{i}/decide", data={"decision": "OPEN"})
    t = next(x for x in client.get("/api/findings").json() if x["finding_id"].endswith("DU16-B2"))
    assert t["bi_decision_status"] == "OPEN"
    print("Tiket OK: tertutup otomatis saat B2 HSBC lolos, dibuka kembali saat keputusan dibatalkan")

    # Ronde: ronde 2 + bank menyanggah lagi item yang ditolak -> dibuka ulang & eskalasi
    it = groups[("DU-21", "B3")]["items"][0]
    client.post(f"/api/disputes/{it['id']}/decide", data={"decision": "DITOLAK", "note": "bukti tidak terbaca"})
    assert client.post("/api/rounds", data={"deadline": "2026-11-20"}).json()["round_no"] == 2
    r = client.post("/api/replies/ingest")
    assert any(b["item"]["dibuka_ulang"] for b in r.json()["per_bank"] if b["bank_id"] == "DU-21")
    g = next(g for g in client.get("/api/disputes?bank_id=DU-21").json()["groups"])
    x = next(i for i in g["items"] if i["id"] == it["id"])
    assert x["status"] == "OPEN" and x["perlu_keputusan_pimpinan"] and x["history"][-1]["event"] == "DIAJUKAN_ULANG"
    print("Ronde OK: item ditolak yang diajukan lagi di ronde 2 dibuka ulang dan ditandai perlu keputusan pimpinan")

    # Pre-check PADG menggantikan Gemini
    r = client.post(f"/api/reconciliation/{t['finding_id']}/analyze")
    assert r.status_code == 200 and "Pre-check" in r.json()["ai_result"]["engine_used"], r.text
    print("Pre-check OK: tanpa layanan AI eksternal")

print("\nALL REAL-DATA INGEST TESTS PASSED")
