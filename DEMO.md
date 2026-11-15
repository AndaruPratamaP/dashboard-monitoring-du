# Skenario Demo 10 Menit: Evaluasi DU PUVA TW III 2026

Demo memakai file kerja ril TW III (`dataset real proses as is/`). Folder ini rahasia dan tidak masuk git. Seluruh alur di bawah juga dijalankan otomatis oleh `backend/tests/test_real_tw3.py`, jadi angka yang disebut di sini sudah teruji.

## Persiapan (sebelum audiens masuk)

1. Jalankan aplikasi dengan **database demo kosong**:
   ```bat
   start_app.bat demo
   ```
   Mode `demo` menghapus `backend/demo.db` lalu menjalankan backend dengan database itu. Database kerja `puva_eval.db` tidak tersentuh.
2. Buka `http://localhost:3000`. Matriks masih kosong; hanya master 21 bank yang terisi.
3. (Opsional) Isi nama pejabat di `backend/.env` (`DOC_KADEP_NAMA`, dst., lihat `.env.example`). Bila kosong, dokumen memakai placeholder `[Nama ...]`.
4. Aktifkan **Mode Alias** di bilah atas bila layar dibagikan ke pihak di luar tim.

## Alur demo

| Menit | Layar | Aksi | Yang ditunjukkan |
|---|---|---|---|
| 0–1 | Executive Matrix | Tampilkan matriks kosong | Tidak ada data sample. Periode terbentuk dari tanggal di file sumber. |
| 1–3 | Data Sumber | **Proses Semua File Lokal** (±25 detik) | 7 sumber terbaca: kuotasi Bloomberg Repo/SRBI/OIS, rasio SRBI, transaksi Repo ≥ 2 minggu & SRBI ≥ 3 bulan, MM OIS, ditambah workbook counterparty. Setiap sumber dicocokkan dengan rekap BI. Selisih yang muncul justru koreksi pasca-konfirmasi (mis. Maybank & BOC HK MM OIS). **Riwayat File Diproses** menampilkan SHA-256 setiap file. |
| 3–4 | Executive Matrix | Klik sel merah Deutsche B3 dan HSBC B2 | 19 bank Memenuhi; **Deutsche** (OIS 15,62%, line OIS 7) dan **HSBC** (SRBI 75%) Tidak Memenuhi, sama dengan M.01. Drawer menampilkan tanggal gugur, sumber, dan catatan batas Repo 1 minggu (20 vs 10 bps). |
| 4–5 | Workbook Konfirmasi | Unduh workbook Deutsche | 7 sheet format template DPPK, isinya sama dengan kiriman BI. Line counterparty setelah cut-off ditandai **baru**. |
| 5–7 | Data Sumber → kartu *Balasan bank* | Buka hasil (sudah ikut diproses pada menit 1–3; klik **Lokal** untuk mengulang) | 23 item sanggahan per tanggal dari balasan ril, contohnya BTN SRBI 13 Jul (+ JPEG) dan Mega OIS 14 Jul (+ PNG). Balasan BCA/UOB ber-password dan arsip `.7z` DBS ditandai *perlu tindakan manual*. Tunjukkan **atur sheet**: pemetaan manual bila nama sheet bank tidak dikenali. |
| 7–8 | Rekonsiliasi Sanggahan | Buka BTN → pratinjau JPEG; buka Maybank → **Terima** | Pre-check PADG (rekap BI vs isian bank, spread vs batas, bukti, dampak). Setelah diterima, Maybank B8 naik ke 100% dan tercatat di riwayat. Tolak BTN 13 Jul (spread 85 bps memang di atas 20 bps). |
| 8–9 | Snapshot & Dokumen | Tampilkan ringkasan, matriks sebelum/sesudah threshold | Setelah semua keputusan: **15 bank 100%, 6 belum** (BRI, BCA, Deutsche, HSBC, BTN, Panin). Setelah threshold early stage, **19 lolos dan 2 tidak** (Deutsche, HSBC), sama dengan M.02 ril TW III. |
| 9–10 | Snapshot & Dokumen | **Kunci Snapshot**, lalu **Unduh Semua (ZIP)** | Paket M.02, Lampiran M.02 (matriks, keterangan per tanggal, dan Lampiran II eskalasi bila ada), M.01, Lampiran M.01, Surat ke bank, dan Matriks Excel. Tanda DRAFT hilang setelah snapshot dikunci. Perubahan data ditolak selama terkunci. |

### Keputusan sanggahan yang menghasilkan M.02 ril

Terima semua item **kecuali** tiga item berikut, yang tetap dicantumkan BI sebagai kekurangan:

- BRI: SRBI 28 Sep 2026
- BTN: SRBI 13 Jul 2026 (spread 85 bps)
- Deutsche: Repo 1 minggu 21 Jul 2026 (spread 210 bps)

Untuk mempercepat demo, keputusan massal bisa dijalankan di muka (lihat `test_07_dokumen_sama_dengan_m02_ril`). Di depan audiens cukup tunjukkan satu Terima dan satu Tolak.

### Eskalasi (opsional, +1 menit)

Di Rekonsiliasi Sanggahan, buka ronde baru dengan tenggat, lalu impor ulang balasan. Item yang sudah ditolak tetapi diajukan lagi oleh bank akan dibuka ulang dan ditandai **perlu keputusan pimpinan**. Item itu otomatis masuk Lampiran II M.02 dan poin IV.3 memo.

## Pertanyaan yang mungkin muncul

- **Kenapa ada selisih dengan rekap BI?** Rekap BI adalah versi pasca-konfirmasi. Sistem menghitung dari data mentah, lalu sanggahan yang diterima menutup selisihnya. Itu sebabnya hasil akhir sama dengan M.02.
- **Batas Repo 1 minggu?** Batas resmi masih menunggu konfirmasi. Sistem memakai 20 bps dan menampilkan simulasi 10 bps; di TW III tidak ada bank yang berubah.
- **Apakah bank bisa mengakses sistem?** Tidak. Portal hanya untuk petugas BI. Bank menerima workbook dan surat, lalu membalas lewat email.

## Verifikasi otomatis

```bash
cd backend && python -m pytest
```
Ada 28 test: 17 unit test dan 11 golden test TW III. Golden test dilewati otomatis bila folder dataset ril tidak ada.
