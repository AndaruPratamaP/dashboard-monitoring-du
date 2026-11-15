"""
Golden test data ril TW III 2026 (parser, rekonsiliasi, dokumen akhir).

Dataset ril bersifat rahasia dan tidak ada di repo; modul ini dilewati bila foldernya tidak ditemukan.
Test berjalan berurutan pada satu database sementara (lihat conftest.py).
"""
import io
import os

import openpyxl
import pytest

from services.real_ingest import default_dataset_dir

pytestmark = pytest.mark.skipif(not os.path.isdir(default_dataset_dir()),
                                reason="folder dataset ril tidak tersedia (rahasia, tidak di-commit)")


def ingest(client, source):
    r = client.post(f"/api/ingest/{source}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["period"]["triwulan"] == "2026-Q3" and j["unknown_banks"] == [], (source, j["unknown_banks"])
    below = {x["bank_id"]: x["rate"] for x in j["per_bank"] if x["rate"] is not None and x["rate"] < 100}
    diffs = {(d["bank_id"], d.get("tanggal")) for d in j["crosscheck"]["differences"]}
    return j, below, diffs


def test_01_b6_b8_dan_matriks_awal(client):
    """B6 & B8 cocok dengan rekap BI; parameter tanpa data = None, bukan temuan."""
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
    # B6 OK: 21 bank cocok dengan rekap BI; 64 hari kerja TW III

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
    # B8 OK: 25 sesi; 2 selisih vs rekap BI terdeteksi (Maybank 21 Jul, BOC HK 10 Sep)

    # --- Matriks periode ril: parameter tanpa sumber data = None, bukan 0, dan tidak menjadi temuan
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert m["DU-07"]["period"] == "2026-Q3"
    assert m["DU-07"]["raw_metrics"]["B1"] is None and m["DU-07"]["raw_metrics"]["B8"] == 96.0
    assert m["DU-07"]["compliance_status"] == "DATA_BELUM_LENGKAP"
    assert m["DU-07"]["total_puva_score"] == 17.5  # B6 7.5 + B8 10
    assert client.get("/api/findings").json() == []
    # Matriks OK: B6+B8 terisi, parameter lain 'belum ada data', tanpa temuan palsu


def test_02_kuotasi_dan_transaksi(client):
    """B7a/B7b, B1, B2, B3 cocok dengan rekap BI; temuan = Deutsche B3 & HSBC B2 (M.01)."""
    # --- B7a / B7b: rekap transaksi harian, 60% dari 64 hari kerja = 38 hari
    for src in ("repo-2m", "srbi-3b"):
        j, below, diffs = ingest(client, src)
        assert below == {} and diffs == set(), (src, below, diffs)
        assert all(x["detail"]["target_days"] == 38 for x in j["per_bank"]), src
    # B7a/B7b OK: 21 bank >= 60% hari kerja, frekuensi sama dengan rekap BI

    # --- B1 Repo: cocok penuh dengan rekap BI; temuan M.01 (Deutsche 21 Jul 210 bps, HSBC 1 bulan 8 Jul & 27 Agu)
    j, below, diffs = ingest(client, "bbg-repo")
    assert below == {"DU-01": 96.88, "DU-14": 98.44, "DU-16": 96.88}, below
    assert diffs == set(), diffs
    dbank = next(x for x in j["per_bank"] if x["bank_id"] == "DU-12")
    assert dbank["detail"]["sumber"].startswith("sheet manual"), dbank  # DBS: sheet DBSI_ref
    # B1 OK: Repo cocok 100% dengan rekap BI

    # --- B2 SRBI: spread maksimum antar seri (BTN 13 Jul 85 bps); HSBC 16 hari tanpa kuotasi (75%)
    j, below, diffs = ingest(client, "bbg-srbi")
    assert below["DU-16"] == 75.0 and below["DU-19"] == 98.44 and below["DU-01"] == 96.88, below
    assert ("DU-19", "2026-07-13") not in diffs  # BTN 85 bps sama dengan rekap BI
    assert {b for b, _ in diffs} == {"DU-01", "DU-14"}, diffs  # BRI 8 Jul & Deutsche: dikoreksi BI pasca-konfirmasi
    # B2 OK: HSBC 75%, BTN 13 Jul 85 bps; {len(diffs)} selisih pasca-konfirmasi (BRI, Deutsche)

    # --- B3 OIS: BCA kosong 16 Jul & 6 Agu; Deutsche dinilai dari rekap BI (ticker Bloomberg invalid)
    j, below, diffs = ingest(client, "bbg-ois")
    assert below == {"DU-06": 96.88, "DU-14": 15.62, "DU-21": 98.44}, below
    assert diffs == {("DU-21", "2026-07-14")}, diffs  # Mega 14 Jul dikoreksi BI
    assert {n["bank_id"] for n in j["source_notes"]} == {"DU-12", "DU-14"}, j["source_notes"]
    # B3 OK: BCA 2 hari, Deutsche 15,62%, 1 selisih (Mega 14 Jul)

    # --- Matriks akhir: hanya B4/B5 (counterparty line) yang belum ada data.
    # Temuan = Deutsche OIS dan HSBC SRBI, sama dengan lampiran M.01 BI.
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert all(row["raw_metrics"]["B4"] is None and row["raw_metrics"]["B1"] is not None for row in m.values())
    assert m["DU-14"]["compliance_status"] == "TIDAK_MEMENUHI" and m["DU-14"]["total_puva_score"] == 47.5
    assert m["DU-16"]["compliance_status"] == "TIDAK_MEMENUHI"
    assert m["DU-01"]["compliance_status"] == "DATA_BELUM_LENGKAP" and m["DU-01"]["total_puva_score"] == 50.0
    findings = sorted(f["finding_id"] for f in client.get("/api/findings").json())
    assert len(findings) == 2 and findings[0].endswith("DU14-B3") and findings[1].endswith("DU16-B2"), findings
    # Matriks OK: temuan = Deutsche B3 & HSBC B2 (sesuai M.01); B4/B5 menunggu data


def test_03_counterparty_line(client):
    """B4/B5: Panin 6 & Deutsche 7 line OIS DU (M.01); koreksi petugas menghitung ulang."""
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
    # B4/B5 OK: Panin 6 & Deutsche 7 line OIS DU (sesuai M.01); file terenkripsi dilaporkan

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
    # Matriks akhir OK: 9 parameter dari data ril; 19 Memenuhi, Deutsche & HSBC Tidak Memenuhi


def test_04_workbook_konfirmasi(client):
    """Workbook konfirmasi: struktur template + isi sama dengan kiriman BI."""
    # --- E5-1 Workbook konfirmasi: struktur template + isi sama dengan kiriman BI
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
    # Workbook konfirmasi OK: 7 sheet + Index tersembunyi; isi sama dengan kiriman BI ke Deutsche


def test_05_cutoff_dan_batas_repo_1w(client):
    """Line setelah cut-off dihitung & ditandai; sensitivitas batas Repo 1W 10 bps."""
    # --- Sprint 4: line setelah cut-off tetap dihitung tetapi ditandai
    bd = {x["bank_id"]: x for x in client.post("/api/counterparty/ingest").json()["per_bank"]}
    assert bd["DU-08"]["B4"]["line_non_du_setelah_cutoff"] == 1 and bd["DU-11"]["B5"]["line_du_setelah_cutoff"] == 1
    assert any(l["setelah_cutoff"] for l in client.get("/api/counterparty/DU-11").json())
    # Counterparty OK: line setelah cut-off ditandai (Panin Repo non-DU, OCBC OIS DU) dan tetap dihitung

    # --- Batas Repo 1 minggu = 10 bps (ketentuan, dikonfirmasi 15 Nov 2026): hasil TW III sama, tetap cocok rekap BI
    j, below, diffs = ingest(client, "bbg-repo")
    assert below == {"DU-01": 96.88, "DU-14": 98.44, "DU-16": 96.88} and diffs == set(), (below, diffs)
    gugur = next(f for f in client.get("/api/findings").json() if f["finding_id"].endswith("DU14-B3"))  # tiket tetap ada
    assert gugur
    deutsche = next(x for x in j["per_bank"] if x["bank_id"] == "DU-14")
    assert deutsche["detail"]["valid_per_tenor"]["1 minggu"] == 63  # 21 Jul (210 bps) satu-satunya hari gugur


def test_06_balasan_bank_dan_sanggahan(client):
    """Balasan bank -> item sanggahan per tanggal; keputusan, tiket, ronde & eskalasi."""
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
    # Balasan bank OK: {n_items} item (BTN, Mega, BOC HK, Maybank, Deutsche, BRI); file ber-password/7z ditandai manual

    # Keputusan: terima BOC HK 10 Sep -> B8 100% (seperti rekap akhir BI), bertahan saat ingest ulang, bisa dibatalkan
    item = next(i for i in groups[("DU-15", "B8")]["items"] if i["tanggal"] == "2026-09-10")
    r = client.post(f"/api/disputes/{item['id']}/decide", data={"decision": "DITERIMA", "note": "sesuai log MM"})
    assert r.status_code == 200 and r.json()["parameter"]["rate"] == 100.0, r.text
    client.post("/api/ingest/mm-ois")
    m = {row["bank_id"]: row for row in client.get("/api/matrix").json()}
    assert m["DU-15"]["raw_metrics"]["B8"] == 100.0 and m["DU-15"]["detail_metrics"]["B8"]["sanggahan_diterima"] == 1
    r = client.post(f"/api/disputes/{item['id']}/decide", data={"decision": "OPEN"})
    assert r.json()["parameter"]["rate"] == 96.0
    # Keputusan OK: diterima -> B8 BOC HK 100%, bertahan saat ingest ulang, dapat dibatalkan

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
    # Tiket OK: tertutup otomatis saat B2 HSBC lolos, dibuka kembali saat keputusan dibatalkan

    # Ronde: ronde 2 + bank menyanggah lagi item yang ditolak -> dibuka ulang & eskalasi
    it = groups[("DU-21", "B3")]["items"][0]
    client.post(f"/api/disputes/{it['id']}/decide", data={"decision": "DITOLAK", "note": "bukti tidak terbaca"})
    assert client.post("/api/rounds", data={"deadline": "2026-11-20"}).json()["round_no"] == 2
    r = client.post("/api/replies/ingest")
    assert any(b["item"]["dibuka_ulang"] for b in r.json()["per_bank"] if b["bank_id"] == "DU-21")
    g = next(g for g in client.get("/api/disputes?bank_id=DU-21").json()["groups"])
    x = next(i for i in g["items"] if i["id"] == it["id"])
    assert x["status"] == "OPEN" and x["perlu_keputusan_pimpinan"] and x["history"][-1]["event"] == "DIAJUKAN_ULANG"
    # Ronde OK: item ditolak yang diajukan lagi di ronde 2 dibuka ulang dan ditandai perlu keputusan pimpinan


def test_06b_pemetaan_sheet_manual(client):
    """Petugas memetakan ulang sheet workbook balasan; item ikut dibentuk ulang (E6-1)."""
    wb = next(r for r in client.get("/api/replies").json() if r["bank_id"] == "DU-01" and r["kind"] == "WORKBOOK"
              and r["summary"] and any(m["jenis"] and m["jenis"].startswith("kuotasi") for m in r["summary"]["sheet"]))
    quote_sheets = [m["sheet"] for m in wb["summary"]["sheet"] if m["jenis"] and m["jenis"].startswith("kuotasi")]
    before = {(g["parameter_code"], i["tanggal"]) for g in client.get("/api/disputes?bank_id=DU-01").json()["groups"]
              for i in g["items"]}
    assert ("B2", "2026-09-28") in before

    import json
    r = client.post(f"/api/replies/{wb['id']}/mapping", data={"mapping": json.dumps({s: "abaikan" for s in quote_sheets})})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["dihapus"] > 0 and all(m.get("manual") for m in r.json()["summary"]["sheet"] if m["sheet"] in quote_sheets)
    after = {(g["parameter_code"], i["tanggal"]) for g in client.get("/api/disputes?bank_id=DU-01").json()["groups"]
             for i in g["items"]}
    assert not any(p in ("B1", "B2") for p, _ in after), after

    r = client.post(f"/api/replies/{wb['id']}/mapping", data={"mapping": "{}"})  # kembali ke pengenalan otomatis
    assert r.status_code == 200
    again = {(g["parameter_code"], i["tanggal"]) for g in client.get("/api/disputes?bank_id=DU-01").json()["groups"]
             for i in g["items"]}
    assert again == before
    bad = client.post(f"/api/replies/{wb['id']}/mapping", data={"mapping": json.dumps({"Tidak Ada": "quotes"})})
    assert bad.status_code == 400


# Keputusan akhir TW III sesuai M.02 ril: seluruh sanggahan diterima kecuali tiga yang tetap dicantumkan
# BI sebagai kekurangan (BRI SRBI 28 Sep, BTN SRBI 13 Jul 85 bps, Deutsche Repo 1 minggu 21 Jul 210 bps).
DITOLAK_M02 = {("DU-01", "B2", "2026-09-28"), ("DU-19", "B2", "2026-07-13"), ("DU-14", "B1", "2026-07-21")}


def test_07_dokumen_sama_dengan_m02_ril(client):
    """Setelah keputusan sanggahan, ringkasan, kalimat memo, dan matriks lampiran = M.02/M.01 ril TW III."""
    for g in client.get("/api/disputes").json()["groups"]:
        for i in g["items"]:
            if i["source_file"] == "dicatat manual":  # uji HSBC di test_06, bukan sanggahan ril
                continue
            rejected = (g["bank_id"], g["parameter_code"], i["tanggal"]) in DITOLAK_M02
            r = client.post(f"/api/disputes/{i['id']}/decide",
                            data={"decision": "DITOLAK" if rejected else "DITERIMA", "note": "keputusan TW III"})
            assert r.status_code == 200, r.text

    ev = client.get("/api/documents/preview").json()
    s = ev["ringkasan"]
    assert s["belum_penuh"] == ["BRI", "BCA", "Deutsche", "HSBC", "BTN", "Panin"], s["belum_penuh"]
    assert len(s["penuh"]) == 15 and s["tidak_lolos_threshold"] == ["Deutsche", "HSBC"]
    assert ev["memo"]["per_bank"][0] == "BRI: belum sepenuhnya memenuhi kewajiban kuotasi harga SRBI."
    assert "15 (lima belas)" in ev["memo"]["kesimpulan"] and "yaitu Deutsche dan HSBC." in ev["memo"]["kesimpulan"]

    rows = {r["nama"]: r for r in ev["rows"]}
    pct = lambda bank, key: round(rows[bank]["cells"][key])  # noqa: E731
    # Nilai matriks lampiran ril (sebelum threshold)
    assert (pct("Deutsche", "repo_1w"), pct("Deutsche", "ois_3b"), rows["Deutsche"]["cells"]["ctp_ois_du"]) == (98, 16, 7)
    assert (pct("HSBC", "repo_1m"), pct("HSBC", "srbi"), pct("BCA", "ois_12b"), pct("BTN", "srbi")) == (97, 75, 97, 98)
    assert rows["Panin"]["cells"]["ctp_ois_du"] == 6 and rows["Mega"]["penuh"] and rows["BOCHK"]["penuh"]
    # Setelah threshold (early stage): hanya Deutsche OIS dan HSBC SRBI yang gagal
    gagal = {(n, k) for n, r in rows.items() for k, v in r["gagal_setelah"].items() if v}
    assert gagal == {("Deutsche", "ois_3b"), ("Deutsche", "ois_12b"), ("HSBC", "srbi")}, gagal
    # Keterangan per tanggal sama dengan tabel "Keterangan Hasil Evaluasi" ril
    assert rows["BCA"]["keterangan"]["ois"] == [
        "Tidak terdapat kuotasi OIS tenor 3 bulan dan 12 bulan pada tanggal:\n16 Juli 2026; dan\n6 Agustus 2026."]
    assert rows["BTN"]["keterangan"]["srbi"] == [
        "Kuotasi SRBI pada tanggal 13 Juli 2026 melebihi ketentuan spread sebesar maksimum 20 bps, spread kuotasi sebesar 85 bps."]
    assert rows["HSBC"]["keterangan"]["srbi"][0].endswith("1, 2, 3, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 20, 21, dan 22 Juli 2026.")


def test_08_eskalasi_masuk_lampiran_m02(client):
    """Sanggahan yang ditolak lalu diajukan lagi di ronde berikutnya masuk Lampiran II M.02 untuk keputusan pimpinan."""
    assert client.post("/api/rounds", data={"deadline": "2026-11-27"}).json()["round_no"] == 3
    client.post("/api/replies/ingest")
    ev = client.get("/api/documents/preview").json()
    assert {(e["bank_id"], e["tanggal"]) for e in ev["eskalasi"]} == {(b, d) for b, _, d in DITOLAK_M02}
    assert "keputusan pimpinan" in ev["memo"]["konfirmasi"]

    import docx
    for kind, expect in (("m02-lampiran", True), ("m01-lampiran", False)):
        r = client.get(f"/api/documents/{kind}")
        assert r.status_code == 200
        text = "\n".join(p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs)
        assert ("Memerlukan Keputusan Pimpinan" in text) is expect, kind
    r = client.get("/api/documents/m02")
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs)
    assert "Lamp.: 2 (dua) set" in text and "BTN: belum sepenuhnya memenuhi kewajiban kuotasi harga SRBI." in text


def test_09_riwayat_upload_ber_hash(client):
    """Setiap file yang diproses tercatat dengan SHA-256; proses ulang file yang sama dikenali."""
    j = client.post("/api/ingest/srbi-ratio").json()
    assert j["upload"]["versi"] == "sama dengan sebelumnya" and len(j["upload"]["sha256"]) == 64
    kinds = {u["kind"] for u in client.get("/api/uploads").json()}
    assert kinds == {"SUMBER", "COUNTERPARTY", "BALASAN"}


def test_10_snapshot_lock_dan_dokumen_final(client):
    """Snapshot terkunci: perubahan ditolak, dokumen tanpa tanda DRAFT; buka kembali bisa."""
    import docx
    r = client.get("/api/documents/m01")
    assert "DRAFT" in docx.Document(io.BytesIO(r.content)).sections[0].header.paragraphs[0].text
    assert client.post("/api/snapshot/lock", json={"locked_by": "uji"}).status_code == 200
    item = client.get("/api/disputes").json()["groups"][0]["items"][0]
    assert client.post(f"/api/disputes/{item['id']}/decide", data={"decision": "OPEN"}).status_code == 409
    r = client.get("/api/documents/m01")
    assert "DRAFT" not in docx.Document(io.BytesIO(r.content)).sections[0].header.paragraphs[0].text
    paket = client.get("/api/documents/paket")
    assert paket.status_code == 200 and paket.headers["content-type"] == "application/zip"
    assert client.post("/api/snapshot/unlock").status_code == 200
