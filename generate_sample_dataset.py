import os
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Set seed agar hasil generate selalu konsisten saat demo
np.random.seed(42)
random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_datasets_puva_2026Q2")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. DAFTAR RESMI 21 BANK DEALER UTAMA PUVA (Sesuai Dokumen Presentasi)
BANKS_DATA = [
    ("DU-01", "Bank A", "PT. BANK RAKYAT INDONESIA (PERSERO), TBK", "KBMI 4", "BBRI IJ", "BRI"),
    ("DU-02", "Bank B", "PT. BANK MANDIRI (PERSERO), TBK", "KBMI 4", "BMRI IJ", "MANDIRI"),
    ("DU-03", "Bank C", "PT. BANK NEGARA INDONESIA (PERSERO), TBK", "KBMI 4", "BBNI IJ", "BNI"),
    ("DU-04", "Bank D", "PT. BANK DANAMON INDONESIA, TBK", "KBMI 3", "BDMN IJ", "DANAMON"),
    ("DU-05", "Bank E", "PT. BANK PERMATA, TBK", "KBMI 3", "BNLI IJ", "PERMATA"),
    ("DU-06", "Bank F", "PT. BANK CENTRAL ASIA, TBK", "KBMI 4", "BBCA IJ", "BCA"),
    ("DU-07", "Bank G", "PT. BANK MAYBANK INDONESIA, TBK", "KBMI 3", "BNII IJ", "MAYBANK"),
    ("DU-08", "Bank H", "PT. PAN INDONESIA BANK", "KBMI 3", "PNBN IJ", "PANIN"),
    ("DU-09", "Bank I", "PT BANK CIMB NIAGA TBK", "KBMI 3", "BNGA IJ", "CIMB NIAGA"),
    ("DU-10", "Bank J", "PT. BANK UOB INDONESIA", "KBMI 3", "UOBI IJ", "UOB"),
    ("DU-11", "Bank K", "PT BANK OCBC NISP, TBK", "KBMI 3", "NISP IJ", "OCBC NISP"),
    ("DU-12", "Bank L", "PT. BANK DBS INDONESIA", "KBMI 2", "DBSI IJ", "DBS"),
    ("DU-13", "Bank M", "STANDARD CHARTERED BANK", "KBMI 2", "SCBI IJ", "STANCHART"),
    ("DU-14", "Bank N", "DEUTSCHE BANK, A.G.", "KBMI 2", "DEUT IJ", "DEUTSCHE"),
    ("DU-15", "Bank O", "BANK OF CHINA (HONG KONG) LIMITED CABANG JAKARTA", "KBMI 2", "BOCH IJ", "BANK OF CHINA"),
    ("DU-16", "Bank P", "PT BANK HSBC INDONESIA", "KBMI 3", "HSBC IJ", "HSBC"),
    ("DU-17", "Bank Q", "PT. BANK JABAR BANTEN, TBK", "KBMI 2", "BJBR IJ", "BJB"),
    ("DU-18", "Bank R", "PT. BPD JAWA TIMUR", "KBMI 2", "BJTM IJ", "BANK JATIM"),
    ("DU-19", "Bank S", "PT. BANK TABUNGAN NEGARA (PERSERO), TBK", "KBMI 3", "BBTN IJ", "BTN"),
    ("DU-20", "Bank T", "PT BANK SMBC INDONESIA TBK", "KBMI 3", "BTPN IJ", "SMBC"),
    ("DU-21", "Bank U", "PT. BANK MEGA, TBK", "KBMI 2", "MEGA IJ", "MEGA"),
]

df_banks = pd.DataFrame(BANKS_DATA, columns=[
    "Bank_ID", "Masked_Alias", "Nama_Resmi_Bank", "Kelompok_KBMI", "Kode_Bloomberg", "Kode_SPPA_Antasena"
])

# Buat 60 Hari Kerja Efektif pada Triwulan II 2026 (April - Juni 2026)
all_weekdays = pd.date_range(start="2026-04-01", end="2026-06-30", freq="B")
working_days = [d.strftime("%Y-%m-%d") for d in all_weekdays[:60]]

# Jadwal Matchmaking OIS (6 periode di Q2 2026: 2 kali per bulan)
ois_matchmaking_dates = [
    "2026-04-08", "2026-04-22", "2026-05-06",
    "2026-05-20", "2026-06-10", "2026-06-24"
]

# Seri SRBI Tradable
srbi_series = [
    ("SRBI-12M-2026A", "2026-09-15", True, "3 Bulan"),
    ("SRBI-12M-2026B", "2026-09-25", True, "3 Bulan"),
    ("SRBI-06M-2026C", "2026-11-20", True, "5 Bulan"),
    ("SRBI-EXPIRED-01", "2026-04-10", False, "0 Bulan"), # Non-tradable untuk jebakan validasi
]
df_srbi_ref = pd.DataFrame(srbi_series, columns=["Seri_SRBI", "Tanggal_Maturity", "Is_Tradable", "Kategori_Sisa_Tenor"])

# ==============================================================================
# FILE 00: MASTER REFERENSI, KALENDER & PARAMETER (00_Master_Referensi_PUVA.xlsx)
# ==============================================================================
with pd.ExcelWriter(f"{OUTPUT_DIR}/00_Master_Referensi_PUVA.xlsx", engine="openpyxl") as writer:
    df_banks.to_excel(writer, sheet_name="Master_21_Bank_DU", index=False)
    pd.DataFrame({"Tanggal_Hari_Kerja": working_days, "Triwulan": "2026-Q2"}).to_excel(writer, sheet_name="Kalender_Kerja_Q2", index=False)
    pd.DataFrame({"Periode_Ke": range(1, 7), "Tanggal_Matchmaking_OIS": ois_matchmaking_dates}).to_excel(writer, sheet_name="Jadwal_OIS", index=False)
    df_srbi_ref.to_excel(writer, sheet_name="Ref_Seri_SRBI", index=False)

# ==============================================================================
# FILE 01: KUOTASI HARGA REPO, SRBI, & OIS (01_Raw_Kuotasi_Bloomberg_SPPA.xlsx)
# Cakupan: Parameter B1 (Repo), B2 (SRBI), B3 (OIS)
# ==============================================================================
quotes_rows = []
for idx, bank in df_banks.iterrows():
    alias = bank["Masked_Alias"]
    b_code = bank["Kode_Bloomberg"]
    s_code = bank["Kode_SPPA_Antasena"]
    
    for day_idx, day in enumerate(working_days):
        # 1. Kuotasi REPO (B1): O/N (spread <= 5 bps), 1W & 1M (spread <= 20 bps)
        # Semua bank 100% lolos B1
        for tenor, max_sp in [("O/N", 4.0), ("1W", 15.0), ("1M", 18.0)]:
            bid = round(6.00 + random.uniform(-0.05, 0.05), 4)
            ask = round(bid + (max_sp / 100.0), 4)
            quotes_rows.append({
                "Tanggal_Kuotasi": day, "Platform": "SPPA", "Kode_Partisipan": s_code,
                "Instrumen": "REPO", "Tenor_atau_Seri": tenor,
                "Bid_Rate": bid, "Ask_Rate": ask, "Spread_Bps": max_sp
            })

        # 2. Kuotasi SRBI (B2): Seri tradable, spread <= 20 bps
        # SKENARIO TEMUAN: Bank A (BRI) gagal di 14 hari kerja (spread 25 bps -> hanya 46/60 = 76.67% ~ 77%)
        if alias == "Bank A" and day_idx >= 46:
            sp_srbi = 25.0 # Melanggar batas maks 20 bps!
        else:
            sp_srbi = 15.0
        bid_s = 6.65
        quotes_rows.append({
            "Tanggal_Kuotasi": day, "Platform": "Bloomberg", "Kode_Partisipan": b_code,
            "Instrumen": "SRBI", "Tenor_atau_Seri": "SRBI-12M-2026A",
            "Bid_Rate": bid_s, "Ask_Rate": round(bid_s + sp_srbi/100.0, 4), "Spread_Bps": sp_srbi
        })

        # 3. Kuotasi OIS (B3): Tenor 1M dan 3M, spread <= 20 bps
        # SKENARIO TEMUAN: Bank B (Mandiri) hanya valid di 13 hari pertama (13/60 = 21.67% ~ 21%)
        if alias == "Bank B" and day_idx >= 13:
            sp_ois_3m = 28.0 # Melanggar batas maks 20 bps pada tenor 3M
        else:
            sp_ois_3m = 16.0
            
        for tenor_ois, sp_val in [("1M", 14.0), ("3M", sp_ois_3m)]:
            bid_o = 6.10
            quotes_rows.append({
                "Tanggal_Kuotasi": day, "Platform": "Bloomberg", "Kode_Partisipan": b_code,
                "Instrumen": "OIS", "Tenor_atau_Seri": tenor_ois,
                "Bid_Rate": bid_o, "Ask_Rate": round(bid_o + sp_val/100.0, 4), "Spread_Bps": sp_val
            })

pd.DataFrame(quotes_rows).to_excel(f"{OUTPUT_DIR}/01_Raw_Kuotasi_Bloomberg_SPPA.xlsx", index=False)

# ==============================================================================
# FILE 02: SURVEY COUNTERPARTY LINE (02_Raw_Survey_Counterparty_Line.xlsx)
# Cakupan: Parameter B4 (Line Repo: 10 DU & 10 Non-DU) & B5 (Line OIS: 10 DU)
# ==============================================================================
survey_rows = []
for idx, bank in df_banks.iterrows():
    alias = bank["Masked_Alias"]
    nama = bank["Nama_Resmi_Bank"]
    
    # SKENARIO TEMUAN: Bank N (Deutsche Bank) hanya punya 5 DU & 4 Non-DU untuk Repo (45% < 50% Early State)
    if alias == "Bank N":
        repo_du_count, repo_non_du_count = 5, 4
    elif alias == "Bank A":
        repo_du_count, repo_non_du_count = 19, 62
    elif alias == "Bank B":
        repo_du_count, repo_non_du_count = 20, 50
    elif alias == "Bank C":
        repo_du_count, repo_non_du_count = 19, 55
    else:
        repo_du_count = random.randint(14, 20)
        repo_non_du_count = random.randint(25, 55)
        
    ois_du_count = 16 if alias in ["Bank A", "Bank C"] else (20 if alias == "Bank B" else random.randint(12, 19))
    
    survey_rows.append({
        "Periode_Evaluasi": "2026-Q2",
        "Nama_Bank_Pelapor": nama,
        "Jml_Line_Repo_Bank_DU": repo_du_count,
        "Jml_Line_Repo_Bank_Non_DU": repo_non_du_count,
        "Jml_Line_OIS_Bank_DU": ois_du_count,
        "Tanggal_CutOff_Survey": "2026-06-30"
    })

pd.DataFrame(survey_rows).to_excel(f"{OUTPUT_DIR}/02_Raw_Survey_Counterparty_Line.xlsx", index=False)

# ==============================================================================
# FILE 03: HARTIS PASAR PERDANA & SEKUNDER (03_Raw_HARTIS_Transaksi.xlsx)
# Cakupan: B6 (Jual SRBI Sekunder >= 30% Win), B7a (Repo >= 2 Minggu di 60% HK), B7b (SRBI Sisa 3Bln di 60% HK)
# ==============================================================================
primary_srbi_rows = []
secondary_tx_rows = []
deal_counter = 10001

for idx, bank in df_banks.iterrows():
    alias = bank["Masked_Alias"]
    nama = bank["Nama_Resmi_Bank"]
    win_perdana = 1000.0 # Rp 1.000 Miliar (1 Triliun) agar mudah diverifikasi
    
    primary_srbi_rows.append({
        "Periode": "2026-Q2", "Nama_Bank_HARTIS": nama,
        "Kelompok_KBMI": bank["Kelompok_KBMI"], "Total_Volume_Win_SRBI_Miliar_Rp": win_perdana
    })
    
    # Target penjualan SRBI sekunder (B6): minimal 30% dari 1.000 M = 300 M
    # SKENARIO TEMUAN: Bank D (Danamon) hanya menjual 195 M (19.5% dari win -> rasio pemenuhan 65% < 80%)
    if alias == "Bank A":
        target_sec_sales = 1780.0 # 178%
    elif alias == "Bank B":
        target_sec_sales = 1420.0 # 142%
    elif alias == "Bank C":
        target_sec_sales = 1750.0 # 175%
    elif alias == "Bank D":
        target_sec_sales = 195.0  # 19.5% (GAGAL B6!)
    else:
        target_sec_sales = float(random.randint(450, 1200))

    # Distribusi Hari Kerja Transaksi Repo Sekunder (B7a: target 60% dari 60 HK = 36 HK)
    # SKENARIO TEMUAN: Bank R (Bank Jatim) punya 38 hari transaksi, tapi 12 hari di antaranya tenornya hanya 7 hari (< 14 hari)!
    # Sehingga yang valid hanya 26 hari kerja (26 / 36 target = 72.2% < 80% Early State!)
    repo_days_count = 57 if alias in ["Bank A", "Bank B", "Bank C"] else (38 if alias == "Bank R" else 52)
    srbi_days_count = 57 if alias == "Bank A" else (53 if alias == "Bank B" else (51 if alias == "Bank C" else 50))

    # Generate transaksi Repo Sekunder (B7a)
    for d_i in range(repo_days_count):
        deal_counter += 1
        # Jika Bank R pada 12 transaksi terakhir, buat tenor 7 hari (tidak memenuhi syarat min 14 hari)
        tenor_hari = 7 if (alias == "Bank R" and d_i >= 26) else 14
        secondary_tx_rows.append({
            "Deal_ID": f"HRT-RP-{deal_counter}", "Tanggal_Transaksi": working_days[d_i],
            "Nama_Bank_HARTIS": nama, "Instrumen": "REPO_SEKUNDER", "Peran": "SELLER/BORROWER",
            "Tenor_Hari": tenor_hari, "Sisa_Jangka_Waktu_Bulan": None,
            "Volume_Miliar_Rp": 50.0, "Status_Settlement": "SETTLED"
        })

    # Generate transaksi SRBI Sekunder (B6 & B7b)
    vol_per_day = round(target_sec_sales / srbi_days_count, 2)
    for d_i in range(srbi_days_count):
        deal_counter += 1
        secondary_tx_rows.append({
            "Deal_ID": f"HRT-SR-{deal_counter}", "Tanggal_Transaksi": working_days[d_i],
            "Nama_Bank_HARTIS": nama, "Instrumen": "SRBI_SEKUNDER", "Peran": "SELLER",
            "Tenor_Hari": None, "Sisa_Jangka_Waktu_Bulan": 3.0, # Memenuhi syarat sisa tenor 3 bulan (B7b)
            "Volume_Miliar_Rp": vol_per_day, "Status_Settlement": "SETTLED"
        })

with pd.ExcelWriter(f"{OUTPUT_DIR}/03_Raw_HARTIS_Transaksi.xlsx", engine="openpyxl") as writer:
    pd.DataFrame(primary_srbi_rows).to_excel(writer, sheet_name="Lelang_Perdana_SRBI", index=False)
    pd.DataFrame(secondary_tx_rows).to_excel(writer, sheet_name="Transaksi_Pasar_Sekunder", index=False)

# ==============================================================================
# FILE 04: DS ANTASENA MATCHMAKING OIS (04_Raw_DS_Antasena_Matchmaking_OIS.xlsx)
# Cakupan: Parameter B8 (Matchmaking OIS Tenor 1 Bulan & 3 Bulan di setiap periode)
# ==============================================================================
antasena_rows = []
for idx, bank in df_banks.iterrows():
    s_code = bank["Kode_SPPA_Antasena"]
    for p_idx, m_date in enumerate(ois_matchmaking_dates, start=1):
        for tenor_ois in ["1 Bulan", "3 Bulan"]:
            antasena_rows.append({
                "Periode_Matchmaking": f"P{p_idx}", "Tanggal_Pelaksanaan": m_date,
                "Kode_Bank_Antasena": s_code, "Tenor_OIS": tenor_ois,
                "Status_Partisipasi": "HADIR & KUOTASI AKTIF", "Nominal_Match_Miliar_Rp": 25.0
            })

pd.DataFrame(antasena_rows).to_excel(f"{OUTPUT_DIR}/04_Raw_DS_Antasena_Matchmaking_OIS.xlsx", index=False)

# ==============================================================================
# FILE 05: DATA SIMULASI SANGGAHAN & BUKTI BANK (05_Simulasi_Sanggahan_Bank_DU.xlsx)
# Digunakan untuk menguji Modul AI Verification & Human-in-the-Loop
# ==============================================================================
disputes_data = [
    {
        "Finding_ID": "FND-2026Q2-DU01-B2",
        "Bank_ID": "DU-01", "Masked_Alias": "Bank A", "Nama_Resmi_Bank": "PT. BANK RAKYAT INDONESIA (PERSERO), TBK",
        "Parameter": "B2 - Kuotasi Harga SRBI",
        "Rekap_Awal_BI": "76.67% (46/60 Hari Kerja)", "Klaim_Bank": "85.00% (51/60 Hari Kerja)",
        "Alasan_Sanggahan_Bank": "Pada tanggal 10-16 Juni 2026 (5 hari kerja), kuotasi SRBI seri SRBI-12M-2026A sudah diinput dengan spread 18 bps di terminal internal, namun tercatat 25 bps di log penarikan awal. Terlampir tangkapan layar terminal kuotasi.",
        "Nama_File_Bukti": "Bukti_Terminal_SRBI_BRI_Juni2026.pdf",
        "Rekomendasi_AI_Expected": "APPROVE (Bukti tangkapan layar menunjukkan spread 18 bps <= 20 bps sesuai PADG No. 23/2024; pemenuhan naik menjadi 85% dan lolos threshold Early State >= 80%)."
    },
    {
        "Finding_ID": "FND-2026Q2-DU02-B3",
        "Bank_ID": "DU-02", "Masked_Alias": "Bank B", "Nama_Resmi_Bank": "PT. BANK MANDIRI (PERSERO), TBK",
        "Parameter": "B3 - Kuotasi Harga OIS",
        "Rekap_Awal_BI": "21.67% (13/60 Hari Kerja)", "Klaim_Bank": "81.67% (49/60 Hari Kerja)",
        "Alasan_Sanggahan_Bank": "Terdapat kendala teknis mapping ticker OIS tenor 3 Bulan pada feeder otomatis Bloomberg sejak akhir April. Bank melampirkan log kuotasi manual yang dikirimkan ke helpdesk.",
        "Nama_File_Bukti": "Tiket_Helpdesk_Bloomberg_OIS_Mandiri.pdf",
        "Rekomendasi_AI_Expected": "PARTIAL / REVIEW PETUGAS (PADG mewajibkan kuotasi tayang di platform; perlu keputusan kebijakan DPPK apakah log kendala teknis dapat dihitung sebagai pemenuhan)."
    },
    {
        "Finding_ID": "FND-2026Q2-DU04-B6",
        "Bank_ID": "DU-04", "Masked_Alias": "Bank D", "Nama_Resmi_Bank": "PT. BANK DANAMON INDONESIA, TBK",
        "Parameter": "B6 - Penjualan SRBI Pasar Sekunder",
        "Rekap_Awal_BI": "19.50% dari Win Perdana (Rasio Pemenuhan 65.00%)", "Klaim_Bank": "31.50% dari Win Perdana (Rasio Pemenuhan 100.00%)",
        "Alasan_Sanggahan_Bank": "Terdapat penjualan SRBI sekunder sebesar Rp 120 Miliar pada tanggal 30 Juni 2026 sore yang baru berstatus Settled pada cut-off akhir hari.",
        "Nama_File_Bukti": "Konfirmasi_Settlement_HARTIS_Danamon_120M.pdf",
        "Rekomendasi_AI_Expected": "APPROVE (Bukti settlement HARTIS berada dalam periode evaluasi Q2 2026; total penjualan menjadi Rp 315 Miliar atau 31.5% >= target 30%)."
    },
    {
        "Finding_ID": "FND-2026Q2-DU14-B4",
        "Bank_ID": "DU-14", "Masked_Alias": "Bank N", "Nama_Resmi_Bank": "DEUTSCHE BANK, A.G.",
        "Parameter": "B4 - Counterparty Line Repo",
        "Rekap_Awal_BI": "45.00% (5 Bank DU & 4 Bank Non-DU)", "Klaim_Bank": "60.00% (6 Bank DU & 6 Bank Non-DU)",
        "Alasan_Sanggahan_Bank": "Penambahan fasilitas counterparty line Repo dengan 1 Bank DU dan 2 Bank Non-DU telah ditandatangani pada 28 Juni 2026 namun terlewat saat pengisian form Survey.",
        "Nama_File_Bukti": "Dokumen_GMRA_Counterparty_Line_DeutscheBank.pdf",
        "Rekomendasi_AI_Expected": "APPROVE (Dokumen perjanjian efektif sebelum akhir periode evaluasi; capaian naik menjadi 60% >= threshold Early State 50%)."
    },
    {
        "Finding_ID": "FND-2026Q2-DU18-B7A",
        "Bank_ID": "DU-18", "Masked_Alias": "Bank R", "Nama_Resmi_Bank": "PT. BPD JAWA TIMUR",
        "Parameter": "B7a - Transaksi Repo Pasar Sekunder",
        "Rekap_Awal_BI": "72.22% (26/36 Target Hari Kerja)", "Klaim_Bank": "100.00% (38/36 Target Hari Kerja)",
        "Alasan_Sanggahan_Bank": "Kami melakukan transaksi Repo sekunder di 38 hari kerja (63% hari kerja), mohon 12 hari transaksi pada bulan Juni tetap diperhitungkan.",
        "Nama_File_Bukti": "Rekap_Deal_Repo_BankJatim_Q2.xlsx",
        "Rekomendasi_AI_Expected": "REJECT / TOLAK (Berdasarkan audit data HARTIS, 12 transaksi yang diklaim hanya memiliki tenor 7 hari, sedangkan PADG No. 23 Tahun 2024 mewajibkan tenor minimal 2 minggu / 14 hari)."
    }
]

pd.DataFrame(disputes_data).to_excel(f"{OUTPUT_DIR}/05_Simulasi_Sanggahan_Bank_DU.xlsx", index=False)
print(f"Berhasil membuat 6 file dataset realistis di dalam folder: {OUTPUT_DIR}")