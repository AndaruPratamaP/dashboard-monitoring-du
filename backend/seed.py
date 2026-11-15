"""
Inisialisasi database PUVA EVAL-CORE.

- Master 21 Bank DU disinkronkan dari backend/data/master_bank_du.json setiap startup.
- Tidak ada data sample: periode evaluasi terbentuk dari file sumber ril yang diproses
  (tanggal di dalam file menentukan triwulan).
- Database lama yang masih memuat periode dataset sample sintetis dibersihkan otomatis.
"""

import os
import json
import logging
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base, ensure_schema
from models import (
    MasterBank, EvaluationPeriod, BankScoreMatrix, FindingTicket, SourceDataset, CounterpartyLine,
    ConfirmationRound, BankReply, DisputeItem, UploadHistory,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

MASTER_BANK_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "master_bank_du.json")


def sync_master_banks(db: Session) -> int:
    """
    Upsert master 21 Bank DU dari backend/data/master_bank_du.json (idempoten).
    Dipanggil setiap startup agar database lama ikut mendapat sandi BI, kode BBG, dan alias.
    """
    with open(MASTER_BANK_JSON, encoding="utf-8") as f:
        banks = json.load(f)["banks"]
    for b in banks:
        bank = db.query(MasterBank).filter(MasterBank.Bank_ID == b["bank_id"]).first()
        if not bank:
            bank = MasterBank(Bank_ID=b["bank_id"])
            db.add(bank)
        bank.Masked_Alias = b["masked_alias"]
        bank.Nama_Resmi_Bank = b["nama_resmi"]
        bank.Nama_Singkat = b["nama_singkat"]
        bank.Kelompok_KBMI = b["kelompok_kbmi"]
        bank.Sandi_BI = b["sandi_bi"]
        bank.Kode_BBG = b["kode_bbg"]
        bank.No_Urut_Konfirmasi = b["no_urut_konfirmasi"]
        bank.Aliases_JSON = json.dumps(b.get("aliases", []))
        aliases = b.get("aliases", [])
        bank.Kode_Bloomberg = next((a for a in aliases if a.endswith(" IJ")), b["kode_bbg"])
        bank.Kode_SPPA_Antasena = b["nama_singkat"].upper()
    db.commit()
    return len(banks)


def purge_sample_periods(db: Session) -> int:
    """
    Hapus periode dari dataset sample sintetis lama: periode tanpa data harian dari file sumber ril
    (tidak ada `source_datasets` dan kalender hari kerja). Periode ril selalu punya keduanya.
    """
    removed = 0
    for period in db.query(EvaluationPeriod).all():
        has_real = period.Working_Days_JSON or db.query(SourceDataset).filter(SourceDataset.period_id == period.id).first()
        if has_real:
            continue
        for model in (DisputeItem, BankReply, ConfirmationRound, CounterpartyLine, UploadHistory, FindingTicket, BankScoreMatrix):
            db.query(model).filter(model.period_id == period.id).delete(synchronize_session=False)
        db.delete(period)
        removed += 1
    if removed:
        db.commit()
        logger.info("Periode dataset sample dihapus: %d", removed)
    return removed


def seed_database(db: Session = None) -> None:
    """Sinkronkan master bank dan bersihkan sisa data sample (dipanggil saat startup)."""
    should_close = db is None
    if db is None:
        Base.metadata.create_all(bind=engine)
        ensure_schema()
        db = SessionLocal()
    try:
        n = sync_master_banks(db)
        purge_sample_periods(db)
        logger.info("Master bank DU tersinkron: %d bank", n)
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    seed_database()
