# PROJECT SPECIFICATION: PUVA EVAL-CORE (Sistem Evaluasi Triwulanan Dealer Utama PUVA)

## 1. Gambaran Umum & Tujuan Proyek
Aplikasi web full-stack untuk mengotomasi proses monitoring, rekonsiliasi/konfirmasi, dan evaluasi triwulanan kewajiban Dealer Utama Pasar Uang dan Pasar Valuta Asing (DU PUVA) di Bank Indonesia berdasarkan PBI No. 6 Tahun 2024 dan PADG No. 23 Tahun 2024.
Aplikasi ini menggantikan proses manual pengolahan data dari 5 sumber (Bloomberg, SPPA, Survey, HARTIS, DS Antasena), pemisahan worksheet per bank, verifikasi bukti sanggahan yang berlarut-larut, hingga pembuatan dokumen laporan akhir (Memorandum M.02 untuk Pimpinan dan M.01 untuk DSMM).

## 2. Tech Stack & Arsitektur
- **Frontend:** Next.js (App Router, TypeScript), Tailwind CSS, Shadcn/UI, Lucide Icons, TanStack Table (untuk tabel matriks & filter kompleks), Recharts (visualisasi tren & gap pemenuhan).
- **Backend / API Engine:** Python FastAPI (terintegrasi sebagai backend service) menggunakan `pandas` & `openpyxl` (pemrosesan multi-file Excel & ekspor lampiran), `python-docx` (pembuatan otomatis dokumen Word M.02 & M.01), serta `google-genai` (Gemini API untuk analisis bukti sanggahan & generasi narasi evaluasi).
- **Database & File Storage:** Supabase (PostgreSQL + Storage Buckets) atau SQLite/PostgreSQL lokal dengan dukungan seeding data otomatis untuk keperluan Live Demo penguji.

## 3. Identitas Desain UI/UX Baru (Berbeda Total dari Prototype Lama)
Buat antarmuka yang sama sekali baru dengan konsep **"Modern Central Bank Command Center"**:
1. **Layout Navigasi (Collapsible Left Sidebar + Sticky Context Bar):**
   - Jangan gunakan tab horizontal di bagian atas seperti prototipe lama. Gunakan *Left Sidebar* vertikal yang dapat dilipat dengan grup menu terstruktur: (1) *Executive Overview*, (2) *Smart ETL & Data Hub*, (3) *Workbooks & Bank Splitter*, (4) *Reconciliation Resolution Center*, (5) *Snapshot & Doc Generator*, (6) *Rule & Calendar Settings*.
   - **Sticky Top Context Bar:** Menampilkan *Global Control* yang selalu terlihat di semua halaman: Selector Periode (Tahun & Triwulan), Selector Tahap Threshold (*Early State / Intermediate / End-State*), **Interactive Role Switcher** (`Internal BI View` vs `Bank DU Portal Simulation` + dropdown pilih simulasi Bank), dan **Privacy Masking Switch** (`Real Bank Names` vs `Masked Alias: Bank A - Bank U`).
2. **Desain Visual:**
   - Tema warna: *Slate & Emerald Institutional* (Background `#F8FAFC`, Sidebar `#0F172A`, Accent `#059669` untuk kepatuhan/lolos dan `#E11D48` untuk temuan di bawah threshold).
   - **Split-Screen Reconciliation View:** Pada menu klarifikasi temuan, gunakan layar terbelah dua (Kiri: Data Transaksi BI & Kalkulasi Aturan PADG; Kanan: Tiket Sanggahan Bank, *In-App Document/Image Previewer* untuk bukti bank, dan Panel Rekomendasi AI).
   - **Interactive Drill-Down Drawer:** Mengklik nilai persentase pada sel matriks bank akan membuka *Slide-over Drawer* dari kanan yang menampilkan rincian transaksi harian pembentuk angka tersebut tanpa berpindah halaman.

## 4. Aturan Bisnis & Logika Perhitungan (Rule Engine PADG No. 23 Tahun 2024)
Sistem mengevaluasi 21 Bank Dealer Utama berdasarkan parameter berikut:

### A. Komponen Pasar Uang & Pasar Valas (PUVA - DPPK) — Total Bobot Maksimal: 60%
Jika pemenuhan bank >= Threshold tahap yang dipilih, bank mendapat **Skor Penuh** (sesuai bobot). Jika < Threshold, bank mendapat **Skor 0** dan sistem otomatis menerbitkan **Finding ID** (Nomor Temuan).

| Kode | Kewajiban PUVA | Ukuran Pemenuhan & Kriteria Validasi | Early State | Intermediate | End-State | Bobot |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **B1** | Kuotasi Harga Repo | Setiap hari kerja; spread maks. 5 bps (tenor O/N) & maks. 20 bps (tenor 1 minggu & 1 bulan) | >= 80% | >= 85% | >= 90% | 2,5% |
| **B2** | Kuotasi Harga SRBI | Setiap hari kerja; seri yang dapat ditransaksikan; spread maks. 20 bps | >= 80% | >= 85% | >= 90% | 2,5% |
| **B3** | Kuotasi Harga OIS | Setiap hari kerja; spread maks. 20 bps (tenor 1 bulan & 3 bulan) | >= 80% | >= 85% | >= 90% | 2,5% |
| **B4** | Counterparty Line Repo | Minimal 10 bank DU PUVA dan 10 bank non-DU PUVA pada akhir periode evaluasi | >= 50% | >= 70% | >= 80% | 7,5% |
| **B5** | Counterparty Line OIS | Minimal 10 bank DU PUVA pada akhir periode evaluasi | >= 50% | >= 70% | >= 80% | 2,5% |
| **B6** | Penjualan SRBI Pasar Sekunder | Minimal 30% dari volume win pada lelang pasar perdana | >= 80% | >= 85% | >= 90% | 7,5% |
| **B7a** | Transaksi Repo Pasar Sekunder | Tenor minimal 2 minggu (>= 14 hari), dilakukan pada minimal 60% hari kerja setiap periode evaluasi | >= 80% | >= 85% | >= 90% | 20,0% |
| **B7b** | Transaksi SRBI Pasar Sekunder | Sisa jangka waktu 3 bulan, dilakukan pada minimal 60% hari kerja setiap periode evaluasi | >= 80% | >= 85% | >= 90% | 5,0% |
| **B8** | Matchmaking OIS | Tenor 1 dan 3 bulan pada setiap periode matchmaking OIS | >= 80% | >= 85% | >= 90% | 10,0% |

### B. Komponen Operasi Moneter (OM - DPMA) — Total Bobot Maksimal: 40% (Input Rekap / Opsional Simulasi Komposit)
Sediakan fitur input/impor nilai rekap untuk 3 parameter OM agar sistem dapat menyimulasikan **Skor Komposit Total (100%)**:
1. **OM1 - Penawaran Lelang OPT:** Setiap hari lelang (Early >= 70%, Inter >= 80%, End >= 90% | Bobot: 15%).
2. **OM2 - Volume Win SRBI:** KBMI 4 min. 3% total penerbitan; KBMI lainnya min. 1% total penerbitan (Early >= 85%, Inter >= 90%, End >= 95% | Bobot: 20%).
3. **OM3 - Penawaran Lelang BI-FRN:** Setiap hari lelang (Early/Inter/End >= 60% | Bobot: 5%).

### C. Logika Tindak Lanjut Akhir (Berdasarkan Skor Komposit)
- **Skor Komposit == 100%:** Memenuhi seluruh kewajiban (Lulus Penuh).
- **90% <= Skor Komposit < 100%:** Tindak lanjut berupa **Email Pembinaan oleh DSMM**.
- **Skor Komposit < 90%:** Tindak lanjut berupa **Sanksi Administratif Teguran Tertulis**.

## 5. Spesifikasi 5 Modul Fungsional Utama (MVP Workflow)
1. **Smart Multi-Source ETL & Entity Resolution:**
   - Dropzone untuk mengunggah file mentah (.xlsx/.csv) dari Bloomberg, SPPA, Survey, HARTIS, dan DS Antasena.
   - Tabel *Master Entity Resolution* yang memetakan berbagai variasi penulisan nama/sandi 21 Bank DU asli ke satu ID Bank tunggal, dilengkapi fitur *Dynamic Aliasing* (`Bank A` s.d. `Bank U`).
2. **Automated Rekap ALL & Per-Bank Worksheet Splitter:**
   - Menghasilkan tampilan *Master Worksheet BI (Rekap ALL)* dan secara otomatis memisahkannya menjadi 21 *Worksheet Per Bank* yang dapat diunduh sebagai file Excel individual (lengkap dengan daftar transaksi yang gugur/tidak masuk kriteria dan kode `Finding_ID`).
3. **Dual-Mode Workspace & Early Warning System (EWS):**
   - **Mode BI:** Memantau matriks seluruh 21 bank, distribusi skor, dan antrean verifikasi.
   - **Mode DU (Simulasi Eksternal & Paket Konfirmasi):** Menampilkan dashboard spesifik 1 bank terpilih, indikator *Early Warning System (EWS)* atas parameter yang masih kurang sebelum akhir periode, serta form pengajuan sanggahan & unggah bukti berdasarkan `Finding_ID`.
4. **AI-Assisted Reconciliation & Evidence Checker (Human-in-the-Loop):**
   - Ketika bank mengunggah klaim sanggahan dan bukti pada suatu `Finding_ID`, Gemini AI menganalisis klaim tersebut terhadap aturan PADG No. 23/2024 (misal: mengecek apakah spread kuotasi melebihi 20 bps atau tenor di bawah 2 minggu) dan memberikan status rekomendasi (`Rekomendasi Terima` / `Rekomendasi Tolak` beserta rujukan aturan).
   - Petugas BI mengeksekusi keputusan final (*Approve/Reject*). Jika *Approved*, sistem otomatis menghitung ulang (*re-calculate*) skor bank dan mencatat perubahan di *Audit Trail*.
5. **Evaluation Snapshot Locking & Automated Document Generator (M.02 & M.01):**
   - Tombol **"Lock Snapshot Evaluasi"** untuk membekukan versi akhir data pasca-konfirmasi.
   - Generator otomatis (menggunakan data Snapshot dan narasi AI) untuk mengunduh:
     * Dokumen Word **Memorandum M.02** (Laporan Evaluasi ke Pimpinan DPPK).
     * Dokumen Word **Memorandum M.01** (Pengantar Hasil Evaluasi ke DSMM).
     * File Excel/Word **3 Lampiran Resmi**: (1) Hasil Evaluasi Sebelum Threshold, (2) Hasil Evaluasi Setelah Threshold, dan (3) Keterangan Hasil Evaluasi & Tindak Lanjut per Bank.