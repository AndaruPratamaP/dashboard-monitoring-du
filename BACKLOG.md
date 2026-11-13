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
| E0-4 | Sebagai sistem, saya mencatat **riwayat upload** (file, pengunggah, waktu, hash). | Setiap angka di matriks bisa ditelusuri ke file sumbernya. | P1 | S |

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
| ◐ E3-3 | Hapus logika lama berbasis HARTIS per-transaksi (tenor per deal) yang tidak punya data ril. | Rule engine B6/B7 memakai input rekap; sanggahan B7 berbasis per tanggal. **Status:** data ril B6/B7 sudah lewat rekap; logika HARTIS tinggal dipakai dataset sample TW II dan dihapus bersama sample (E0-1 lanjutan, Sprint 5). | P0 | S |

### E4 — Counterparty line (B4, B5)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E4-1 | Sebagai petugas BI, saya mengimpor/mengoreksi **daftar counterparty line Repo & OIS** tiap bank (counterparty dari master DU/non-DU + status `Sebelum cut-off` / `Setelah cut-off` / `Dihapus`) dari workbook balasan. | Mengikuti template sheet BI; validasi duplikat; bank tidak mengakses portal. | P0 | M |
| E4-2 | Sistem menghitung B4 (10 DU **dan** 10 non-DU) dan B5 (10 DU) dari isian yang berlaku per akhir periode. | Hanya line `Sebelum cut-off` yang dihitung; daftar periode lalu bisa disalin sebagai titik awal. | P0 | S |
| E4-3 | Daftar counterparty periode lalu bisa disalin sebagai titik awal periode baru. | Mengurangi isian ulang. | P2 | S |

### E5 — Generator workbook konfirmasi per bank

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E5-1 | Sebagai petugas BI, saya generate workbook konfirmasi **persis template sekarang** (7 sheet + `Index` tersembunyi) untuk 1 atau 21 bank. | Isi sesuai rekap BI; kolom `Status` & `Keterangan` siap diisi bank; struktur identik dengan `Konfirmasi Bank/*.xlsx`. | P0 | M |
| E5-2 | Unduh semua workbook sekaligus (ZIP) + daftar PIC email per bank. | ZIP berisi 21 file bernama `NN. Nama Bank.xlsx`. | P1 | S |

### E6 — Import & diff balasan bank (pengganti AI)

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E6-1 | Sebagai petugas BI, saya upload workbook balasan bank; sistem mengenali sheet walau **nama berubah** (mis. `Kuotasi SRBI, Repo & OIS`). | Fuzzy match nama sheet + fallback mapping manual di UI. | P0 | M |
| E6-2 | Sistem membandingkan isian bank vs rekap BI **per tanggal per kewajiban** dan otomatis membuat tiket sanggahan untuk setiap selisih. | Tiket berisi tanggal, nilai BI, nilai bank, keterangan bank. | P0 | L |
| E6-3 | File yang tidak bisa diproses (ber-password, 7z, terlalu besar) ditandai **perlu tindakan manual** dengan alasan yang jelas. | Tidak ada crash; status terlihat di daftar balasan. | P0 | S |
| E6-4 | Lampiran bukti (PDF/PNG/JPEG) diunggah per tiket dan tampil di previewer split-screen. | Gambar & PDF tampil in-app. | P1 | M |

### E7 — Rekonsiliasi rule-based

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E7-1 | Hapus jalur Gemini; ganti label UI "AI" → **"Pre-check PADG"**. | Tidak ada dependensi API key; teks UI & dokumen konsisten. | P0 | S |
| ✅ E7-2 | Pre-check deterministik: tolak otomatis bila klaim < threshold, B7a bergantung pada transaksi gugur; selain itu → verifikasi petugas. | Sudah ada; perlu disesuaikan ke sanggahan per tanggal (E3-3). | P0 | S |
| E7-3 | **Ronde konfirmasi**: setiap kirim–balas tercatat sebagai ronde (1, 2, 3, …) dengan tenggat; tiket menyimpan riwayat argumen tiap ronde. | Audit trail menunjukkan siapa, kapan, ronde berapa. | P0 | M |
| E7-4 | Tiket otomatis **CLOSED** bila parameter lolos setelah rekalkulasi / ganti tahap. | Tidak ada tiket OPEN basi. | P0 | S |
| E7-5 | Eskalasi: tiket yang melewati N ronde ditandai **perlu keputusan pimpinan** dan masuk lampiran M.02. | Menjawab pain point "sama-sama ngeyel ga kelar". | P1 | S |
| ✅ E7-6 | Keputusan petugas menghitung ulang skor via rule engine; nilai disetujui bertahan saat ETL ulang; snapshot lock memblokir perubahan. | Sudah dikerjakan. | — | — |

### E8 — Skor akhir tanpa OM

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| ✅ E8-1 | Hapus OM1–OM3 dari rule engine, API, UI, worksheet, dan dokumen. | Skor akhir = skor PUVA (maks 60%); tidak ada angka OM di mana pun. | P0 | M |
| ✅ E8-2 | Status bank: **Memenuhi** (60/60), **Tidak Memenuhi** (ada parameter gagal), **Data Belum Lengkap** (ada sumber belum diupload). | Teguran/pembinaan tidak ditampilkan sampai aturannya diputuskan. | P0 | S |

### E9 — Dokumen akhir

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E9-1 | Sesuaikan M.02, M.01, dan lampiran dengan format dokumen ril di `Dokumen Final` & folder periode. | Struktur & kalimat baku mengikuti dokumen TW III. | P0 | M |
| E9-2 | Generate **Surat Informasi Pemenuhan Kewajiban** per bank. | 21 surat dari snapshot terkunci. | P1 | M |
| ✅ E9-3 | Snapshot lock sebelum generate dokumen. | Sudah ada. | — | — |

### E10 — Kualitas & demo

| ID | Story | Kriteria terima | P | Size |
|---|---|---|---|---|
| E10-1 | Ubah `test_stage*.py` menjadi **pytest** dengan DB sementara + golden test per parser. | `pytest` hijau tanpa menyentuh DB lokal. | P0 | M |
| E10-2 | Hapus mode "Bank DU Portal Simulation"; login sederhana untuk petugas BI saja. | Tidak ada tampilan yang mengesankan bank mengakses sistem. | P1 | M |
| E10-3 | Skenario demo 10 menit: upload raw → matriks → generate workbook → import balasan → tiket → keputusan → lock → M.02. | Skrip demo tertulis dan diuji. | P0 | S |
| E10-4 | Upgrade Next.js 13.5 → versi terbaru yang stabil; gitignore `tsconfig.tsbuildinfo`. | Build & dev jalan. | P2 | S |

## 4. Urutan pengerjaan

Asumsi ±1 minggu per sprint, satu orang.

| Sprint | Fokus | Item | Hasil yang bisa didemokan |
|---|---|---|---|
| 1 ✅ | Fondasi + data paling "ril" | E0-1, E0-2, E0-3, E2-1, E2-2, E3-2, E8-1, E8-2 | B6 & B8 dihitung dari data TW III ril; OM hilang |
| 2 ✅ | Parser terberat | E1-1 s.d. E1-4, E3-1, E3-3 | Matriks B1–B3, B6–B8 dari data ril, lolos golden test |
| 3 | Siklus konfirmasi | E4-1, E4-2, E5-1 | Counterparty line dari balasan bank; workbook konfirmasi ter-generate |
| 4 | Rekonsiliasi | E6-1, E6-2, E6-3, E7-1, E7-3, E7-4 | Balasan bank ril diimpor → tiket otomatis → keputusan |
| 5 | Finalisasi | E9-1, E10-1, E10-3, sisa P1 | Demo end-to-end + dokumen akhir |

Bila waktu sempit, potong dari bawah: P2 → P1 → E6-1 fuzzy (ganti mapping manual saja).

## 5. Yang dihapus / dipensiunkan

- Jalur Gemini (`analyze_dispute_with_ai` → pre-check murni).
- Seluruh komponen OM (DPMA).
- Parser HARTIS per-transaksi & kolom `Tenor_Hari` / `Sisa_Jangka_Waktu_Bulan` (tidak ada data ril).
- `generate_sample_dataset.py` & `sample_datasets_puva_2026Q2/` setelah E0-1 selesai.
- `seed.py`: tiket sanggahan "expected AI" dari file 05.

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
