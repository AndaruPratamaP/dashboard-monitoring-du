import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from database import Base


class MasterBank(Base):
    __tablename__ = "master_banks"

    Bank_ID = Column(String(20), primary_key=True, index=True)
    Masked_Alias = Column(String(50), nullable=False, index=True)  # Bank A s.d. Bank U
    Nama_Resmi_Bank = Column(String(255), nullable=False)
    Kelompok_KBMI = Column(String(20), nullable=False)  # KBMI 2, KBMI 3, KBMI 4
    Kode_Bloomberg = Column(String(50), nullable=False)  # Misal: BBRI IJ
    Kode_SPPA_Antasena = Column(String(50), nullable=False)  # Misal: BRI
    Nama_Singkat = Column(String(100), nullable=True)        # Misal: BRI, Mandiri
    Sandi_BI = Column(String(10), nullable=True, index=True)  # Misal: 002 (DS Antasena / HARTIS)
    Kode_BBG = Column(String(20), nullable=True)             # Kode submitter Bloomberg, misal: BRIJ
    No_Urut_Konfirmasi = Column(Integer, nullable=True)      # Nomor file workbook konfirmasi BI
    Aliases_JSON = Column(Text, nullable=True)               # Variasi penulisan nama/kode di file sumber

    # Relationships
    score_matrices = relationship("BankScoreMatrix", back_populates="bank", cascade="all, delete-orphan")
    finding_tickets = relationship("FindingTicket", back_populates="bank", cascade="all, delete-orphan")


class EvaluationPeriod(Base):
    __tablename__ = "evaluation_periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    Tahun = Column(Integer, nullable=False, default=2026)
    Triwulan = Column(String(10), nullable=False, default="2026-Q2")  # e.g. 2026-Q2
    Active_Threshold_Stage = Column(String(20), nullable=False, default="EARLY")  # EARLY, INTERMEDIATE, END_STATE
    Is_Snapshot_Locked = Column(Boolean, nullable=False, default=False)
    Locked_At = Column(DateTime, nullable=True)
    Locked_By = Column(String(100), nullable=True)
    Snapshot_ID = Column(String(50), nullable=True)
    Snapshot_Data_JSON = Column(Text, nullable=True)
    Is_Active = Column(Boolean, nullable=True, default=False)  # Periode yang sedang ditampilkan/diolah
    Working_Days_JSON = Column(Text, nullable=True)      # Daftar hari kerja periode (ISO date)
    MM_OIS_Sessions_JSON = Column(Text, nullable=True)   # Daftar tanggal sesi matchmaking OIS
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    score_matrices = relationship("BankScoreMatrix", back_populates="period", cascade="all, delete-orphan")
    finding_tickets = relationship("FindingTicket", back_populates="period", cascade="all, delete-orphan")


class BankScoreMatrix(Base):
    __tablename__ = "bank_score_matrix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=False, index=True)

    # --- 1. Persentase Realisasi Mentah (Sebelum Threshold, dalam %) ---
    b1_raw = Column(Float, nullable=True)    # Kuotasi Repo (Bobot 2.5%)
    b2_raw = Column(Float, nullable=True)    # Kuotasi SRBI (Bobot 2.5%)
    b3_raw = Column(Float, nullable=True)    # Kuotasi OIS (Bobot 2.5%)
    b4_raw = Column(Float, nullable=True)    # Counterparty Line Repo (Bobot 7.5%)
    b5_raw = Column(Float, nullable=True)    # Counterparty Line OIS (Bobot 2.5%)
    b6_raw = Column(Float, nullable=True)    # Penjualan SRBI Pasar Sekunder (Bobot 7.5%)
    b7a_raw = Column(Float, nullable=True)   # Transaksi Repo Sekunder Tenor >= 14h (Bobot 20.0%)
    b7b_raw = Column(Float, nullable=True)   # Transaksi SRBI Sekunder Sisa 3Bln (Bobot 5.0%)
    b8_raw = Column(Float, nullable=True)    # Matchmaking OIS (Bobot 10.0%)

    # --- 2. Status Lolos / Gagal Terhadap Threshold Aktif (Boolean) ---
    b1_passed = Column(Boolean, nullable=True)
    b2_passed = Column(Boolean, nullable=True)
    b3_passed = Column(Boolean, nullable=True)
    b4_passed = Column(Boolean, nullable=True)
    b5_passed = Column(Boolean, nullable=True)
    b6_passed = Column(Boolean, nullable=True)
    b7a_passed = Column(Boolean, nullable=True)
    b7b_passed = Column(Boolean, nullable=True)
    b8_passed = Column(Boolean, nullable=True)

    # --- 3. Skor Terbobot Setelah Threshold (Jika Lolos dapat bobot penuh, Gagal = 0) ---
    b1_score = Column(Float, default=0.0)   # Maks 2.5%
    b2_score = Column(Float, default=0.0)   # Maks 2.5%
    b3_score = Column(Float, default=0.0)   # Maks 2.5%
    b4_score = Column(Float, default=0.0)   # Maks 7.5%
    b5_score = Column(Float, default=0.0)   # Maks 2.5%
    b6_score = Column(Float, default=0.0)   # Maks 7.5%
    b7a_score = Column(Float, default=0.0)  # Maks 20.0%
    b7b_score = Column(Float, default=0.0)  # Maks 5.0%
    b8_score = Column(Float, default=0.0)   # Maks 10.0%
    total_puva_score = Column(Float, default=0.0)  # Maks 60.0%

    # --- 4. Status Akhir (OM/DPMA dihapus dari ruang lingkup; skor akhir = total PUVA, maks 60%) ---
    compliance_status = Column(String(50), default="DATA_BELUM_LENGKAP")
    # Nilai compliance_status:
    # - "MEMENUHI"            -> seluruh 9 parameter PUVA lolos threshold (skor 60%)
    # - "TIDAK_MEMENUHI"      -> minimal satu parameter di bawah threshold
    # - "DATA_BELUM_LENGKAP"  -> ada parameter yang sumber datanya belum diunggah
    # Catatan: nilai *_raw = NULL berarti sumber data parameter tsb belum diunggah.

    # JSON Rincian pembentuk angka untuk Slide-over Drawer UI
    detail_metrics_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    bank = relationship("MasterBank", back_populates="score_matrices")
    period = relationship("EvaluationPeriod", back_populates="score_matrices")


class FindingTicket(Base):
    __tablename__ = "finding_tickets"

    Finding_ID = Column(String(50), primary_key=True, index=True)  # Misal: FND-2026Q2-DU01-B2
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=True, index=True)
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=False, index=True)
    Parameter_Code = Column(String(20), nullable=False)            # Misal: B2, B3, B4, B6, B7a
    Nilai_Rekap_BI = Column(String(255), nullable=False)           # Misal: 76.67% (46/60 Hari Kerja)
    Detail_Transaksi_Gugur = Column(Text, nullable=True)           # JSON string transaksi yang gugur
    Nilai_Klaim_Bank = Column(String(255), nullable=True)          # Misal: 85.00% (51/60 Hari Kerja)
    Alasan_Sanggahan = Column(Text, nullable=True)
    File_Bukti_Name = Column(String(255), nullable=True)
    AI_Recommendation_Status = Column(String(50), nullable=True)   # APPROVE / REJECT / PARTIAL_REVIEW
    AI_Analysis_Text = Column(Text, nullable=True)
    BI_Decision_Status = Column(String(30), nullable=False, default="OPEN")  # OPEN / PENDING_REVIEW / APPROVED / REJECTED / CLOSED (lolos setelah rekalkulasi)
    Approved_Value = Column(Float, nullable=True)                  # Nilai realisasi (%) yang ditetapkan petugas BI saat APPROVED
    Verified_By = Column(String(100), nullable=True)
    Updated_At = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    bank = relationship("MasterBank", back_populates="finding_tickets")
    period = relationship("EvaluationPeriod", back_populates="finding_tickets")


class AuditTrail(Base):
    __tablename__ = "audit_trails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    action = Column(String(100), nullable=False)
    performed_by = Column(String(100), default="System")
    details = Column(Text, nullable=True)


class SourceDataset(Base):
    """
    Data harian per bank hasil ingest satu sumber (mis. volume Repo 2m harian, spread kuotasi per tenor).
    Menjadi bahan workbook konfirmasi dan jejak file sumber setiap angka di matriks.
    """
    __tablename__ = "source_datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Source = Column(String(30), nullable=False, index=True)    # bbg-repo, repo-2m, mm-ois, ...
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=False, index=True)
    Payload_JSON = Column(Text, nullable=False)
    File_Name = Column(String(255), nullable=True)
    Uploaded_At = Column(DateTime, default=datetime.datetime.utcnow)


class UploadHistory(Base):
    """
    Riwayat file yang diproses sistem (file sumber, workbook counterparty, balasan bank) beserta hash SHA-256,
    sehingga setiap angka di matriks dapat ditelusuri ke file dan versi file yang dipakai.
    """
    __tablename__ = "upload_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=True, index=True)
    Kind = Column(String(20), nullable=False)          # SUMBER / COUNTERPARTY / BALASAN
    Source = Column(String(30), nullable=True)         # kode sumber (bbg-repo, ...) atau bank pengirim
    File_Name = Column(String(255), nullable=False)
    SHA256 = Column(String(64), nullable=False, index=True)
    Size_Bytes = Column(Integer, nullable=True)
    Origin = Column(String(10), nullable=False)        # UNGGAH (dari browser) / LOKAL (folder dataset)
    Uploaded_By = Column(String(100), default="Petugas BI DPPK")
    Uploaded_At = Column(DateTime, default=datetime.datetime.utcnow)
    Result_Note = Column(Text, nullable=True)


class CounterpartyLine(Base):
    """Counterparty line Repo/OIS milik bank DU per periode (dari workbook konfirmasi & balasan bank)."""
    __tablename__ = "counterparty_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=False, index=True)
    Instrument = Column(String(10), nullable=False)             # REPO / OIS
    Counterparty_Sandi = Column(String(10), nullable=False)     # 002
    Counterparty_Nama = Column(String(255), nullable=True)      # 002 - PT. BANK RAKYAT INDONESIA ...
    Status = Column(String(100), nullable=True)                 # Sebelum/Setelah cut-off, Dihapus, kosong
    Source_File = Column(String(255), nullable=True)
    Confirmed_By_Bank = Column(Boolean, nullable=False, default=False)


class BankDirectory(Base):
    """Daftar bank (sandi + nama) untuk pilihan counterparty; diambil dari sheet Index workbook BI."""
    __tablename__ = "bank_directory"

    Sandi = Column(String(10), primary_key=True)
    Nama = Column(String(255), nullable=False)                  # format "002 - PT. BANK ..."


class ConfirmationRound(Base):
    """Satu putaran kirim workbook konfirmasi -> balasan bank (ronde 1, 2, ...) dengan tenggat."""
    __tablename__ = "confirmation_rounds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Round_No = Column(Integer, nullable=False)
    Opened_At = Column(DateTime, default=datetime.datetime.utcnow)
    Deadline = Column(String(10), nullable=True)                # YYYY-MM-DD
    Note = Column(Text, nullable=True)


class BankReply(Base):
    """File balasan bank yang diterima pada satu ronde (workbook, bukti, atau file yang perlu tindakan manual)."""
    __tablename__ = "bank_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Round_No = Column(Integer, nullable=False, default=1)
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=True, index=True)
    File_Name = Column(String(255), nullable=False)
    Stored_Path = Column(String(500), nullable=True)            # salinan lokal untuk pratinjau bukti
    Kind = Column(String(20), nullable=False)                   # WORKBOOK / BUKTI / MANUAL
    Status_Note = Column(Text, nullable=True)                   # alasan perlu tindakan manual / ringkasan sheet
    Summary_JSON = Column(Text, nullable=True)
    Received_At = Column(DateTime, default=datetime.datetime.utcnow)


class DisputeItem(Base):
    """
    Satu selisih isian bank vs rekap BI per tanggal per kewajiban (tiket sanggahan otomatis).
    Status: OPEN -> DITERIMA (hari dihitung memenuhi) / DITOLAK (rekap BI dipertahankan).
    """
    __tablename__ = "dispute_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_id = Column(Integer, ForeignKey("evaluation_periods.id"), nullable=False, index=True)
    Bank_ID = Column(String(20), ForeignKey("master_banks.Bank_ID"), nullable=False, index=True)
    Parameter_Code = Column(String(10), nullable=False)         # B1, B2, B3, B6, B7a, B7b, B8
    Source = Column(String(30), nullable=False)                 # bbg-repo, repo-2m, ...
    Tanggal = Column(String(10), nullable=True)                 # YYYY-MM-DD; None = nilai agregat (B6)
    Tenor = Column(String(20), nullable=True)                   # on / 1w / 1m / any / 3b / 12b / 1b
    Nilai_BI = Column(String(100), nullable=True)
    Nilai_Bank = Column(String(100), nullable=True)
    Klaim_Bank_JSON = Column(Text, nullable=True)               # nilai klaim terstruktur (mis. sekunder & perdana B6)
    Keterangan_Bank = Column(Text, nullable=True)
    Source_File = Column(String(255), nullable=True)
    Round_No = Column(Integer, nullable=False, default=1)       # ronde pertama kali muncul
    Last_Round = Column(Integer, nullable=False, default=1)     # ronde terakhir bank masih menyanggah
    Status = Column(String(20), nullable=False, default="OPEN")
    Decided_By = Column(String(100), nullable=True)
    Decision_Note = Column(Text, nullable=True)
    Decided_At = Column(DateTime, nullable=True)
    History_JSON = Column(Text, nullable=True)


def get_active_period(db) -> "EvaluationPeriod":
    """
    Periode evaluasi aktif: yang ditandai Is_Active, atau periode terbaru bila belum ada.
    Dipakai seluruh endpoint/generator agar matriks, temuan, snapshot, dan dokumen konsisten.
    """
    period = db.query(EvaluationPeriod).filter(EvaluationPeriod.Is_Active.is_(True)).first()
    if period is None:
        period = db.query(EvaluationPeriod).order_by(EvaluationPeriod.id.desc()).first()
    return period
