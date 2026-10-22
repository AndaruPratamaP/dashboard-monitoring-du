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
    b1_raw = Column(Float, default=0.0)    # Kuotasi Repo (Bobot 2.5%)
    b2_raw = Column(Float, default=0.0)    # Kuotasi SRBI (Bobot 2.5%)
    b3_raw = Column(Float, default=0.0)    # Kuotasi OIS (Bobot 2.5%)
    b4_raw = Column(Float, default=0.0)    # Counterparty Line Repo (Bobot 7.5%)
    b5_raw = Column(Float, default=0.0)    # Counterparty Line OIS (Bobot 2.5%)
    b6_raw = Column(Float, default=0.0)    # Penjualan SRBI Pasar Sekunder (Bobot 7.5%)
    b7a_raw = Column(Float, default=0.0)   # Transaksi Repo Sekunder Tenor >= 14h (Bobot 20.0%)
    b7b_raw = Column(Float, default=0.0)   # Transaksi SRBI Sekunder Sisa 3Bln (Bobot 5.0%)
    b8_raw = Column(Float, default=0.0)    # Matchmaking OIS (Bobot 10.0%)

    # --- 2. Status Lolos / Gagal Terhadap Threshold Aktif (Boolean) ---
    b1_passed = Column(Boolean, default=False)
    b2_passed = Column(Boolean, default=False)
    b3_passed = Column(Boolean, default=False)
    b4_passed = Column(Boolean, default=False)
    b5_passed = Column(Boolean, default=False)
    b6_passed = Column(Boolean, default=False)
    b7a_passed = Column(Boolean, default=False)
    b7b_passed = Column(Boolean, default=False)
    b8_passed = Column(Boolean, default=False)

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

    # --- 4. Slot Input Operasi Moneter (OM - DPMA, Maks 40%) ---
    om1_raw = Column(Float, default=100.0)   # Penawaran Lelang OPT (Bobot 15.0%)
    om1_passed = Column(Boolean, default=True)
    om1_score = Column(Float, default=15.0)

    om2_raw = Column(Float, default=100.0)   # Volume Win SRBI (Bobot 20.0%)
    om2_passed = Column(Boolean, default=True)
    om2_score = Column(Float, default=20.0)

    om3_raw = Column(Float, default=100.0)   # Penawaran Lelang BI-FRN (Bobot 5.0%)
    om3_passed = Column(Boolean, default=True)
    om3_score = Column(Float, default=5.0)

    total_om_score = Column(Float, default=40.0)  # Maks 40.0%

    # --- 5. Skor Komposit & Status Tindak Lanjut Akhir ---
    composite_score = Column(Float, default=100.0)  # Maks 100.0%
    compliance_status = Column(String(50), default="MEMENUHI")
    # Nilai compliance_status:
    # - "MEMENUHI" (100%) -> Lulus Penuh
    # - "PEMBINAAN_DSMM" (90.0% s.d. <100%) -> Email Pembinaan oleh DSMM
    # - "SANKSI_TEGURAN" (<90.0%) -> Sanksi Administratif Teguran Tertulis

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
    BI_Decision_Status = Column(String(30), nullable=False, default="OPEN")  # OPEN / PENDING_REVIEW / APPROVED / REJECTED
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
