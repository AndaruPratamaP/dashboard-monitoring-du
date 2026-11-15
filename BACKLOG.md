# Backlog PUVA EVAL-CORE (To-Be)

> Disusun 12 Nov 2026 berdasarkan `FINAL PROJECT REQUIREMENT UPDATED.txt` dan sampling folder
> `dataset real proses as is/` (Evaluasi TW III 2026).

## 1. Arah proyek

**Positioning:** dari loop email 21 workbook ke satu portal konfirmasi dengan *single source of truth*.
Fokusnya otomasi proses, bukan AI.

| Keputusan | Isi |
|---|---|
| **OM (DPMA)** | **Dihapus total** (keputusan mentor). Skor akhir = **skor PUVA, maks 60%**. Pemetaan ke tindak lanjut (teguran/pembinaan) dibahas lagi nanti; sementara status = Memenuhi / Tidak Memenuhi / Data Belum Lengkap. |
| **AI (Gemini)** | Dilepas. Diganti **Rule-based Dispute Pre-check (PADG 23/2024)**: deterministik, tanpa API key, bisa dijelaskan per pasal. |
| **Data masuk** | Tiga pintu: (1) upload **raw** (kuotasi BBG, MM OIS), (2) upload **worksheet rekap** (transaksi Repo/SRBI, rasio SRBI), (3) **isian bank** di portal (counterparty line). |
| **Konfirmasi** | Portal **hanya untuk internal BI** (bank tidak diberi akses). Konfirmasi tetap lewat workbook Excel via email; dashboard men-generate workbook dan mengimpor + men-diff balasan bank. |

### Sumber data per kewajiban

| Kode | Kewajiban | Data ril yang tersedia | Pintu masuk |
|---|---|---|---|
| B1 | Kuotasi Repo | Raw BBG Gen-2 (sheet per bank, bid/ask per ticker per tanggal) | Upload raw |
| B2 | Kuotasi SRBI | Raw BBG Gen-2 | Upload raw |
| B3 | Kuotasi OIS | Raw BBG Gen-2 | Upload raw |
| B4 | Counterparty line Repo | Tidak ada; diisi bank di workbook konfirmasi | Import balasan bank |
| B5 | Counterparty line OIS | Tidak ada; diisi bank di workbook konfirmasi | Import balasan bank |
| B6 | Penjualan SRBI sekunder | Rekap `SRBI Rasio Primer` (jual sekunder vs perdana per bank) | Upload rekap |
| B7a | Transaksi Repo ≥ 2 minggu | Rekap `Repo 2m` (matriks volume harian × bank) | Upload rekap |
| B7b | Transaksi SRBI sisa ≥ 3 bulan | Rekap `SRBI 3b` (matriks volume harian × bank) | Upload rekap |
| B8 | Matchmaking OIS 1b & 3b | Raw export DB BI (sheet `Kuotasi`) | Upload raw |

## 2. Konvensi

- **Prioritas:** `P0` wajib untuk sidang · `P1` sebaiknya ada · `P2` bonus.
- **Ukuran:** `S` ≤ 1 hari · `M` 2–3 hari · `L` 4–5 hari.
- **Golden test:** setiap parser dianggap selesai bila hasilnya **sama** dengan worksheet FINAL/rekap BI TW III untuk semua 21 bank (selisih harus bisa dijelaskan).
- Status ✅ = sudah dikerjakan di codebase.

## 3. Epic & user story

### E0 — Fondasi data & periode

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E0-1 | Sebagai tim, saya memakai **dataset TW III ril** sebagai data demo, menggantikan `sample_datasets_puva_2026Q2`. | Mentor mengizinkan data tanpa anonimisasi untuk demo. Folder data ril **tidak di-commit** ke GitHub (gitignore); lokasi diatur lewat env `REAL_DATASET_DIR`. | P0 | S |
| ✅ E0-2 | Sebagai admin, saya mengelola **master 21 bank** dengan semua kode: suffix BBG (`BRIJ`, `MDRI`, …), sandi bank (`002`, `008`, …), nama HARTIS, alias. | Resolver memetakan semua variasi di file ril tanpa error; bank tak dikenal muncul sebagai peringatan, bukan diabaikan. | P0 | S |
| ✅ E0-3 | Sebagai admin, saya mengatur **periode evaluasi**: kalender hari kerja dan tanggal sesi matchmaking OIS. | Jumlah hari kerja tidak lagi hardcode 60; target 60% hari kerja dihitung dari kalender. | P0 | S |
| ✅ E0-4 | Sebagai sistem, saya mencatat **riwayat upload** (file, pengunggah, waktu, hash). | Setiap angka di matriks bisa ditelusuri ke file sumbernya. **Status:** file sumber, counterparty, dan balasan bank tercatat dengan SHA-256 dan status versi (baru / berubah / sama); tampil di Data Sumber. | P1 | S |

### E1 — Ingest kuotasi BBG Gen-2 (B1–B3)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E1-1 | Sebagai petugas BI, saya upload 3 workbook raw BBG (Repo, SRBI, OIS) dan sistem membaca **sheet per bank**. | Header 6 baris di-skip, kolom bid/ask per ticker terbaca, `#N/A` = tidak ada kuotasi. | P0 | M |
| ✅ E1-2 | Sistem memetakan **ticker → tenor/seri** dari sheet `Listing WS` (mis. Repo O/N, 1 Week, 1 Month). | Repo: O/N, 1W, 1M dievaluasi; OIS: **3 bulan & 12 bulan** (`IHSWOOC`, `IHSWOO1`); SRBI: seluruh seri yang dikuotasi. | P0 | M |
| ✅ E1-3 | Sistem menghitung **spread** = \|bid − ask\| × 100 bps dan **hari valid** per aturan (Repo O/N ≤ 5, 1W/1M ≤ 20; SRBI ≤ 20 untuk **spread maksimum** antar seri; OIS 3b & 12b ≤ 20). | Golden test vs `Kuotasi BBG/*_FINAL.xlsx` lolos untuk 21 bank. | P0 | L |
| ✅ E1-4 | Rincian hari gugur (tanggal, tenor, spread) tersedia untuk drill-down dan workbook konfirmasi. | Drawer menampilkan hari gugur dari data ril. | P0 | S |

### E2 — Ingest Matchmaking OIS (B8)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E2-1 | Sebagai petugas BI, saya upload export MM OIS (sheet `Kuotasi`: tanggal, sandi bank, tenor, bid/ask, volume). | Parser membaca `Sandi Bank` (`002 - BRI`) via resolver. | P0 | S |
| ✅ E2-2 | Sistem menghitung partisipasi per sesi: **Ya** bila bank memasang kuotasi tenor 1b **dan** 3b. | Golden test vs sheet `Rekap` (Ya/Tidak per bank per tanggal) lolos. | P0 | M |

### E3 — Ingest rekap transaksi (B6, B7a, B7b)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E3-1 | Upload rekap **Repo 2m** dan **SRBI 3b** (matriks tanggal × bank, volume harian). | Hari dengan volume > 0 dihitung; % terhadap target 60% hari kerja; golden test lolos. | P0 | M |
| ✅ E3-2 | Upload rekap **SRBI Rasio Primer** (jual sekunder vs perdana per bank). | Rasio = sekunder ÷ perdana; kewajiban ≥ 30%; pemenuhan vs threshold tahap. | P0 | S |
| ✅ E3-3 | Hapus logika lama berbasis HARTIS per-transaksi (tenor per deal) yang tidak punya data ril. | Rule engine B6/B7 memakai input rekap; sanggahan B7 berbasis per tanggal. **Status:** logika HARTIS, dataset sample TW II, dan sanggahan per tiket dihapus (Sprint 5). | P0 | S |

### E4 — Counterparty line (B4, B5)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E4-1 | Sebagai petugas BI, saya mengimpor/mengoreksi **daftar counterparty line Repo & OIS** tiap bank (counterparty dari master DU/non-DU + status `Sebelum cut-off` / `Setelah cut-off` / `Dihapus`) dari workbook balasan. | Mengikuti template sheet BI; validasi duplikat; bank tidak mengakses portal. Koreksi status per line lewat tombol **Koreksi** di kartu Konfirmasi Bank (Sprint 4). | P0 | M |
| ✅ E4-2 | Sistem menghitung B4 (10 DU **dan** 10 non-DU) dan B5 (10 DU) dari isian yang berlaku per akhir periode. | Line `Dihapus` tidak dihitung; `Sebelum` dan `Setelah` cut-off sama-sama dihitung (kondisi akhir periode), line `Setelah` diberi tanda **baru**. Golden test: Panin 6 & Deutsche 7 line OIS DU, sesuai M.01. | P0 | S |
| E4-3 | Daftar counterparty periode lalu bisa disalin sebagai titik awal periode baru. | Mengurangi isian ulang. | P2 | S |

### E5 — Generator workbook konfirmasi per bank

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E5-1 | Sebagai petugas BI, saya generate workbook konfirmasi **persis template sekarang** (7 sheet + `Index` tersembunyi) untuk 1 atau 21 bank. | Isi sesuai rekap BI; kolom `Status` & `Keterangan` siap diisi bank; struktur identik dengan `Konfirmasi Bank/*.xlsx`. | P0 | M |
| ◐ E5-2 | Unduh semua workbook sekaligus (ZIP) + daftar PIC email per bank. | ZIP berisi 21 file bernama `NN. Nama Bank.xlsx`. **Status:** ZIP selesai; daftar PIC email belum (tidak ada datanya). | P1 | S |

### E6 — Import & diff balasan bank (pengganti AI)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E6-1 | Sebagai petugas BI, saya upload workbook balasan bank; sistem mengenali sheet walau **nama berubah** (mis. `Kuotasi SRBI, Repo & OIS`). | Fuzzy match nama sheet + fallback mapping manual di UI. **Status:** fuzzy match, sheet `(response)`, dan tabel versi bank di samping tabel BI (`BDI CHECK`) terbaca; pemetaan sheet tampil per file. Pemetaan manual per sheet tersedia lewat **atur sheet** (Sprint 5); pemetaan tersimpan dan tetap dipakai saat impor ulang. | P0 | M |
| ✅ E6-2 | Sistem membandingkan isian bank vs rekap BI **per tanggal per kewajiban** dan otomatis membuat tiket sanggahan untuk setiap selisih. | Tiket berisi tanggal, nilai BI, nilai bank, keterangan bank. | P0 | L |
| ✅ E6-3 | File yang tidak bisa diproses (ber-password, 7z, terlalu besar) ditandai **perlu tindakan manual** dengan alasan yang jelas. | Tidak ada crash; status terlihat di daftar balasan. | P0 | S |
| ✅ E6-4 | Lampiran bukti (PDF/PNG/JPEG) diunggah per tiket dan tampil di previewer split-screen. | Gambar & PDF tampil in-app. | P1 | M |

### E7 — Rekonsiliasi rule-based

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E7-1 | Hapus jalur Gemini; ganti label UI "AI" → **"Pre-check PADG"**. | Tidak ada dependensi API key; teks UI & dokumen konsisten. | P0 | S |
| ✅ E7-2 | Pre-check deterministik: tolak otomatis bila klaim < threshold, B7a bergantung pada transaksi gugur; selain itu → verifikasi petugas. | Sudah ada; perlu disesuaikan ke sanggahan per tanggal (E3-3). | P0 | S |
| ✅ E7-3 | **Ronde konfirmasi**: setiap kirim–balas tercatat sebagai ronde (1, 2, 3, …) dengan tenggat; tiket menyimpan riwayat argumen tiap ronde. | Audit trail menunjukkan siapa, kapan, ronde berapa. | P0 | M |
| ✅ E7-4 | Tiket otomatis **CLOSED** bila parameter lolos setelah rekalkulasi / ganti tahap. | Tidak ada tiket OPEN basi. | P0 | S |
| ✅ E7-5 | Eskalasi: tiket yang melewati N ronde ditandai **perlu keputusan pimpinan** dan masuk lampiran M.02. | Menjawab pain point "sama-sama ngeyel ga kelar". **Status:** item yang masih diperdebatkan ≥ 2 ronde masuk **Lampiran II M.02** dengan kolom keputusan pimpinan, dan disebut di poin IV.3 memo. | P1 | S |
| ✅ E7-6 | Keputusan petugas menghitung ulang skor via rule engine; nilai disetujui bertahan saat ETL ulang; snapshot lock memblokir perubahan. | Sudah dikerjakan. | — | — |

### E8 — Skor akhir tanpa OM

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E8-1 | Hapus OM1–OM3 dari rule engine, API, UI, worksheet, dan dokumen. | Skor akhir = skor PUVA (maks 60%); tidak ada angka OM di mana pun. | P0 | M |
| ✅ E8-2 | Status bank: **Memenuhi** (60/60), **Tidak Memenuhi** (ada parameter gagal), **Data Belum Lengkap** (ada sumber belum diupload). | Teguran/pembinaan tidak ditampilkan sampai aturannya diputuskan. | P0 | S |

### E9 — Dokumen akhir

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E9-1 | Sesuaikan M.02, M.01, dan lampiran dengan format dokumen ril di `Dokumen Final` & folder periode. | Struktur & kalimat baku mengikuti dokumen TW III. **Status:** golden test: setelah keputusan sanggahan, ringkasan (15/6, 19/2), kalimat per bank, nilai per tenor, dan keterangan per tanggal sama dengan M.02 ril. | P0 | M |
| ✅ E9-2 | Generate **Surat Informasi Pemenuhan Kewajiban** per bank. | 21 surat dari snapshot terkunci. **Status:** format ril adalah satu surat dengan lampiran daftar 21 penerima. Tenggat diambil dari ronde konfirmasi, posisi counterparty dari akhir triwulan. | P1 | M |
| ✅ E9-3 | Snapshot lock sebelum generate dokumen. | Sudah ada. | — | — |

### E10 — Kualitas & demo

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E10-1 | Ubah `test_stage*.py` menjadi **pytest** dengan DB sementara + golden test per parser. | `pytest` hijau tanpa menyentuh DB lokal. **Status:** `backend/tests/`: 17 unit test + 11 golden test TW III (dilewati bila dataset ril tidak ada). | P0 | M |
| ◐ E10-2 | Hapus mode "Bank DU Portal Simulation"; login sederhana untuk petugas BI saja. | Tidak ada tampilan yang mengesankan bank mengakses sistem. **Status:** mode portal bank dan endpoint-nya dihapus. Login belum ada: portal berjalan di jaringan internal BI. | P1 | M |
| ✅ E10-3 | Skenario demo 10 menit: upload raw → matriks → generate workbook → import balasan → tiket → keputusan → lock → M.02. | Skrip demo tertulis dan diuji. **Status:** `DEMO.md` + `start_app.bat demo` (database demo kosong); alur yang sama diuji `test_real_tw3.py`. | P0 | S |
| E10-4 | Upgrade Next.js 13.5 → versi terbaru yang stabil; gitignore `tsconfig.tsbuildinfo`. | Build & dev jalan. | P2 | S |

## 4. Urutan pengerjaan

Asumsi ±1 minggu per sprint, satu orang.

| Sprint | Fokus | Item | Hasil yang bisa didemokan |
|---|---|---|---|
| 1 ✅ | Fondasi + data paling "ril" | E0-1, E0-2, E0-3, E2-1, E2-2, E3-2, E8-1, E8-2 | B6 & B8 dihitung dari data TW III ril; OM hilang |
| 2 ✅ | Parser terberat | E1-1 s.d. E1-4, E3-1, E3-3 | Matriks B1–B3, B6–B8 dari data ril, lolos golden test |
| 3 ✅ | Siklus konfirmasi | E4-1, E4-2, E5-1 | Counterparty line dari balasan bank; workbook konfirmasi ter-generate |
| 4 ✅ | Rekonsiliasi | E6-1, E6-2, E6-3, E7-1, E7-3, E7-4 | Balasan bank ril diimpor → tiket otomatis → keputusan |
| 5 ✅ | Finalisasi | E9-1, E10-1, E10-3, sisa P1 | Demo end-to-end + dokumen akhir |

Bila waktu sempit, potong dari bawah: P2 → P1 → E6-1 fuzzy (ganti mapping manual saja).

## 5. Yang dihapus / dipensiunkan

- Jalur Gemini (`analyze_dispute_with_ai` → pre-check murni).
- Seluruh komponen OM (DPMA).
- Parser HARTIS per-transaksi & kolom `Tenor_Hari` / `Sisa_Jangka_Waktu_Bulan` (tidak ada data ril).
- `generate_sample_dataset.py` & `sample_datasets_puva_2026Q2/` (dihapus Sprint 5; periode sample di database lama dibersihkan otomatis saat startup).
- `seed.py`: tiket sanggahan "expected AI" dari file 05 (dihapus Sprint 5; seed hanya master bank).
- Mode Portal Bank DU, EWS reminder, worksheet per bank lama, sanggahan & keputusan per tiket (`/api/disputes/submit`, `/api/reconciliation/*`), dan generator dokumen lama `doc_generator.py` (Sprint 5).

## 6. Keputusan mentor (12 Nov 2026)

1. Data TW III boleh dipakai untuk demo, tidak perlu dianonimkan.
2. Tahap threshold yang berlaku: **Early**.
3. Rekap Repo 2 minggu **sudah difilter** tenor ≥ 14 hari.
4. Label **TW II** pada rekap `Repo 2m` & `SRBI 3b` adalah **salah nama** (isinya TW III).
5. Rasio SRBI 30% dihitung **kumulatif satu triwulan**.
6. Portal **hanya untuk internal BI**.
7. OM **dihapus dulu**; skor akhir maks 60%, tindak lanjut dibahas lagi.

## 7. Catatan Sprint 2 (13 Nov 2026)

Hasil dari data ril TW III (golden test `backend/test_real_ingest.py`):

| Param | Hasil | Selisih vs rekap BI |
|---|---|---|
| B1 Repo | BRI 96,9% (15 Jul, 15 Sep), Deutsche 98,4% (1W 21 Jul 210 bps), HSBC 96,9% (1M 8 Jul, 27 Agu) | 0 |
| B2 SRBI | HSBC 75% (16 hari), Deutsche 87,5%, BRI 96,9%, BTN 98,4% (13 Jul 85 bps) | 9 (BRI 8 Jul, Deutsche 8 hari) |
| B3 OIS | Deutsche 15,6%, BCA 96,9% (16 Jul, 6 Agu), Mega 98,4% | 1 tanggal (Mega 14 Jul) |
| B7a/B7b | 21 bank ≥ 60% hari kerja (target 38 dari 64 hari) | 0 |

Temuan akhir sistem: **Deutsche B3** dan **HSBC B2**, sama dengan lampiran M.01 BI. B4/B5 menunggu Sprint 3.

Aturan yang ditemukan dari data (bukan dari dokumen):
- SRBI dinilai dengan **spread maksimum** seluruh seri yang dikuotasi hari itu (kolom "Spread Maks" BI), bukan spread terbaik.
- Tenor OIS yang dievaluasi adalah **3 bulan & 12 bulan**, bukan 1M & 3M seperti teks lama di aplikasi.
- Ticker Bloomberg DBS (OIS, SRBI) dan Deutsche (OIS) berstatus `#N/A Invalid Security`. BI mengisi rekapnya dari sumber lain. Sistem memakai Rekap BI untuk bank tersebut dan menandainya "perlu verifikasi sumber". DBS Repo memakai sheet `DBSI_ref`.

Pertanyaan untuk mentor:
1. Dari mana data kuotasi DBS (OIS & SRBI) dan Deutsche (OIS) diperoleh bila ticker Bloomberg tidak valid?
2. Deutsche SRBI 3 Agu: seri `YX765088` spread 29 bps, tetapi rekap BI mencatat 20 bps. Apakah ada seri yang dikecualikan (mis. bukan seri tradable)?
3. Selisih BRI Repo (15 Jul, 15 Sep) hilang di rekap BBG+SPPA. Perlukah data SPPA diunggah sebagai sumber tambahan B1?

## 8. Catatan Sprint 3 (13 Nov 2026)

- **B4/B5 dari workbook konfirmasi.** Workbook kiriman BI (`Konfirmasi Bank/`) menjadi daftar awal, lalu balasan bank (`[Confirmed]*/`) menimpa daftar per bank. 33 workbook diterapkan, 12 di antaranya balasan bank.
- **Hasil.** 21 bank punya B4 & B5. Repo ≥ 10 DU dan ≥ 10 non-DU di semua bank. OIS di bawah 10 line DU hanya Panin (6) dan Deutsche (7), sama dengan M.01.
- **Matriks TW III lengkap 9 parameter.** 19 bank Memenuhi; Deutsche (B3) dan HSBC (B2) Tidak Memenuhi.
- **Workbook konfirmasi** (`GET /api/confirmation/{bank}`, ZIP `GET /api/confirmation-all`).
  - Berisi 7 sheet ditambah `Index` tersembunyi, dengan dropdown status dan dropdown counterparty.
  - Golden test: isi Repo 2m, SRBI 3b, Rasio SRBI, MM OIS, dan daftar counterparty **identik** dengan workbook yang dikirim BI ke Deutsche.
  - Bedanya hanya kuotasi OIS Deutsche, karena sistem memakai Rekap BI yang sudah diperbarui.
- **Data harian per sumber** kini disimpan (`source_datasets`). Ini juga menjadi jejak file sumber setiap angka (sebagian dari E0-4).
- **Kinerja.** Membaca 34 workbook turun dari ~95 detik (openpyxl) ke 0,1 detik (pembaca XML langsung). Sebelumnya proxy Next.js terputus.

File yang tidak bisa dibaca otomatis (dilaporkan di UI, tidak diam-diam diabaikan):
- Balasan BCA dan UOB **terenkripsi password**. Petugas perlu membuka file lalu menyimpannya tanpa password sebelum diunggah.

Pertanyaan untuk mentor:
4. Apakah counterparty berstatus **"Setelah cut-off"** (dibuka di tengah triwulan) ikut dihitung? Saat ini dihitung, karena aturannya "pada akhir periode".
5. Template kuotasi BI menghitung Repo 1 minggu dengan `COUNTIF(<=10)`, padahal M.01 menyebut batas 20 bps. Workbook yang di-generate memakai 20 bps. Mana yang benar?

## 9. Catatan Sprint 4 (13 Nov 2026)

**Impor balasan bank → item sanggahan per tanggal** (`POST /api/replies/ingest`, layar *Reconciliation Center*).
- File di folder balasan dikelompokkan per bank: workbook, bukti (PDF/PNG/JPEG), atau **perlu tindakan manual**. Contoh yang perlu tindakan manual: BCA & UOB ber-password, dan dua arsip `.7z` DBS.
- Item sanggahan = hari yang menurut bank memenuhi tetapi menurut data harian BI tidak. Sumbernya ada tiga:
  1. nilai di tabel balasan;
  2. catatan bank yang menyebut tanggal (mis. Deutsche "kuotasi Repo 21 Juli" di samping screenshot);
  3. nama file bukti yang menyebut tanggal (mis. Maybank `OIS 21Jul2026.pdf`).
- Hari yang menurut bank justru lebih buruk dari BI hanya dihitung sebagai selisih informasi, bukan tiket.
- Hasil TW III ada 23 item. Contohnya BTN SRBI 13 Jul (+JPEG), Mega OIS 14 Jul (+PNG), BOC HK MM OIS 10 Sep, Maybank MM OIS 21 Jul, Deutsche Repo 21 Jul & 8 hari SRBI, serta BRI Repo 15 Jul/15 Sep & SRBI 8 Jul/28 Sep.
  - Dua item MM OIS (Maybank, BOC HK) adalah hari yang di rekap akhir BI memang sudah diubah menjadi "Ya". Ini konsisten dengan selisih yang dicatat golden test Sprint 1.
- Deutsche OIS tidak menghasilkan item. Daftar tanggal screenshot mereka sudah tercermin di Rekap BI yang dipakai sistem.

**Keputusan per item** (Terima / Tolak / Batalkan).
- Nilai parameter dihitung ulang dari data harian BI ditambah item yang diterima.
- Keputusan tetap berlaku saat file sumber diproses ulang.
- Drawer menampilkan nilai sebelum sanggahan dan jumlah item yang diterima.
- Pre-check PADG per item memuat:
  - rekap BI vs isian bank;
  - spread klaim vs batas;
  - ada/tidaknya bukti;
  - dampak bila diterima (dihitung bersama tenor lain pada tanggal yang sama).
- Jalur Gemini dihapus (`services/ai_reconciliation.py` → `services/precheck.py`). `GEMINI_API_KEY` tidak dipakai lagi.

**Ronde & eskalasi.**
- Impor balasan masuk ke ronde berjalan. Ronde 1 dibuat otomatis, dan ronde baru dibuka dengan tenggat.
- Item yang ditolak lalu diajukan lagi oleh bank di ronde berikutnya dibuka ulang dan ditandai **perlu keputusan pimpinan**.
- Setiap item menyimpan riwayat (siapa, kapan, ronde, catatan).

**Tiket temuan** ditutup otomatis (`CLOSED`) bila parameter lolos, dan dibuka lagi bila gagal kembali.

**Sanggahan manual** untuk klaim lewat surat/email atau file yang tidak terbaca. Sanggahan ini hanya bisa dicatat untuk hari yang menurut BI memang gugur.

**Counterparty.**
- Line `Setelah` cut-off tetap dihitung dan diberi tanda **baru**. Di TW III ada di Panin (Repo non-DU), OCBC & DBS (OIS DU), dan BJB (OIS non-DU).
- Koreksi status per line tersedia di kartu Konfirmasi Bank.

**Batas Repo 1 minggu** belum final. Sistem memakai 20 bps dan melaporkan simulasi 10 bps per bank (hari terdampak & nilai alternatif) di hasil ingest B1 dan di drawer. Di TW III tidak ada bank yang berubah. Bila 10 bps dikonfirmasi, cukup ubah `max_bps` tenor `1w` di `QUOTE_SOURCES`.

Keputusan pemilik produk (13 Nov 2026):
- Pertanyaan 4 terjawab: line yang dibuka **setelah cut-off tetap dihitung**, tetapi diberi tanda pembeda.
- Pertanyaan 5 **masih menunggu konfirmasi** (Repo 1 minggu 10 vs 20 bps).

Belum dikerjakan (sisa P1, masuk Sprint 5):
- Pemetaan sheet manual di UI (E6-1).
- Item eskalasi masuk lampiran M.02 (E7-5).
- Riwayat upload ber-hash untuk file sumber (E0-4).

## 10. Catatan Sprint 5 (13 Nov 2026)

**Dokumen akhir format ril** (`services/documents.py`, layar *Snapshot & Dokumen*).
- Isinya: M.02, Lampiran M.02, M.01, Lampiran M.01, Surat ke bank DU, dan Matriks Excel. Semua bisa diunduh satu per satu atau sebagai ZIP.
- Lampiran mengikuti dokumen TW III:
  - matriks per tenor *sebelum* threshold (target 100% / min 30% / 60% / 10 line);
  - matriks per tenor *setelah* threshold (early stage: 80% / 24% / 48% / 5 line), dengan nilai Mean/Median;
  - tabel **Keterangan Hasil Evaluasi** per bank yang dirakit dari tanggal gugur. Contoh: "Tidak terdapat kuotasi OIS tenor 3 bulan dan 12 bulan pada tanggal: 16 Juli 2026; dan 6 Agustus 2026."
- Angka dihitung dari data harian BI ditambah sanggahan yang diterima. Status lolos threshold mengikuti rule engine.
- Golden test: setelah keputusan TW III (semua sanggahan diterima kecuali BRI SRBI 28 Sep, BTN SRBI 13 Jul, dan Deutsche Repo 1W 21 Jul), hasilnya **sama dengan M.02 ril**:
  - 15 bank 100%;
  - 6 bank belum: BRI, BCA, Deutsche, HSBC, BTN, Panin;
  - setelah threshold 19 lolos dan 2 tidak: Deutsche, HSBC;
  - nilai per tenor sama dengan matriks lampiran ril.
- Kuotasi yang hanya satu sisi kini disimpan per tanggal. Keterangannya dibedakan dari "tidak ada kuotasi".
- Sebelum snapshot dikunci, dokumen diberi header **DRAFT**. Nama pejabat dan email unit diambil dari `backend/.env` (`DOC_*`); bila kosong, dipakai placeholder.

**Eskalasi ke pimpinan (E7-5).** Item yang ditolak lalu diajukan lagi di ronde berikutnya masuk **Lampiran II M.02**, lengkap dengan kolom keputusan pimpinan, serta disebut di poin II.5 dan IV.3 memo.

**Riwayat upload ber-hash (E0-4).** Setiap file sumber, workbook counterparty, dan balasan bank dicatat beserta SHA-256, ukuran, asal (unggahan/folder lokal), waktu, dan status versi.

**Pemetaan sheet manual (E6-1).** Tersedia lewat tombol **atur sheet** di kartu Balasan bank. Pilihannya: jenis sheet template atau *abaikan*. Setelah disimpan:
- workbook diproses ulang;
- item OPEN yang tidak lagi terbentuk dihapus;
- pemetaan disimpan untuk impor berikutnya.

**Pembersihan (E3-3, E10-2).**
- Yang dihapus:
  - data sample TW II, parser HARTIS, dan seed sample;
  - mode Portal Bank DU, EWS reminder, dan worksheet per bank lama;
  - sanggahan & keputusan per tiket beserta pre-check per tiket.
- Database baru hanya berisi master 21 bank. Periode sample di database lama dihapus otomatis saat startup.
- Menu diberi nama Indonesia: Data Sumber, Workbook Konfirmasi, Rekonsiliasi Sanggahan, Snapshot & Dokumen.

**Kualitas & demo (E10-1, E10-3).**
- `backend/tests/` (pytest, database sementara) berisi 28 test.
- `DEMO.md` berisi skenario 10 menit. `start_app.bat demo` menjalankan aplikasi dengan database demo kosong.
- Alur penuh dari database kosong, termasuk "Proses Semua File Lokal" (±25 detik), sudah dicek di browser.

Masih terbuka:
- Pertanyaan 5: batas Repo 1 minggu 10 vs 20 bps.
- Login petugas BI (E10-2), bila portal akan dipasang di luar jaringan internal.
- Upgrade Next.js (E10-4, P2).
