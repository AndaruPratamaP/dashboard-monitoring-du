"""
Entity Resolution Service untuk 21 Bank Dealer Utama PUVA
Memetakan berbagai sandi, ticker, dan variasi penulisan nama bank ke ID tunggal (DU-01 s.d. DU-21).
"""

import re
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from models import MasterBank


def normalize_text(text: str) -> str:
    """Normalisasi string untuk pencocokan toleran."""
    if not text:
        return ""
    t = str(text).upper().strip()
    # Hapus karakter khusus
    t = re.sub(r"[,\.\(\)\-\_\/]", " ", t)
    # Hapus kata-kata korporasi umum
    tokens_to_remove = ["PT", "PERSERO", "TBK", "CABANG", "JAKARTA", "LIMITED", "AG", "BANK"]
    parts = [p for p in t.split() if p not in tokens_to_remove]
    return " ".join(parts)


class EntityResolver:
    def __init__(self, db: Session):
        self.db = db
        self.banks: List[MasterBank] = db.query(MasterBank).all()
        self._build_indexes()

    def _build_indexes(self):
        self.by_id: Dict[str, MasterBank] = {}
        self.by_alias: Dict[str, MasterBank] = {}
        self.by_bloomberg: Dict[str, MasterBank] = {}
        self.by_sppa: Dict[str, MasterBank] = {}
        self.by_exact_name: Dict[str, MasterBank] = {}
        self.by_normalized_name: Dict[str, MasterBank] = {}

        for b in self.banks:
            # 1. Bank ID
            clean_id = b.Bank_ID.upper().replace("-", "")
            self.by_id[b.Bank_ID.upper()] = b
            self.by_id[clean_id] = b

            # 2. Alias
            self.by_alias[b.Masked_Alias.upper()] = b

            # 3. Bloomberg Ticker
            b_ticker = b.Kode_Bloomberg.upper().strip()
            self.by_bloomberg[b_ticker] = b
            # misal 'BBRI' dari 'BBRI IJ'
            ticker_prefix = b_ticker.split()[0]
            self.by_bloomberg[ticker_prefix] = b

            # 4. Kode SPPA / Antasena
            sppa_code = b.Kode_SPPA_Antasena.upper().strip()
            self.by_sppa[sppa_code] = b

            # 5. Nama Resmi & Normalisasi
            self.by_exact_name[b.Nama_Resmi_Bank.upper().strip()] = b
            norm_name = normalize_text(b.Nama_Resmi_Bank)
            if norm_name:
                self.by_normalized_name[norm_name] = b

    def resolve(self, identifier: Any) -> Optional[MasterBank]:
        """
        Mencocokkan sembarang identifier (Bank_ID, Ticker Bloomberg, Kode SPPA/Antasena,
        atau Nama Resmi Bank) ke entitas MasterBank.
        """
        if identifier is None:
            return None
        
        raw_val = str(identifier).strip()
        val_upper = raw_val.upper()

        # 1. Cek langsung Bank ID
        if val_upper in self.by_id:
            return self.by_id[val_upper]
        clean_id = val_upper.replace("-", "")
        if clean_id in self.by_id:
            return self.by_id[clean_id]

        # 2. Cek Alias
        if val_upper in self.by_alias:
            return self.by_alias[val_upper]

        # 3. Cek Kode Bloomberg
        if val_upper in self.by_bloomberg:
            return self.by_bloomberg[val_upper]
        prefix = val_upper.split()[0]
        if prefix in self.by_bloomberg:
            return self.by_bloomberg[prefix]

        # 4. Cek Kode SPPA / Antasena
        if val_upper in self.by_sppa:
            return self.by_sppa[val_upper]

        # 5. Cek Nama Resmi Eksak
        if val_upper in self.by_exact_name:
            return self.by_exact_name[val_upper]

        # 6. Cek Nama Ternormalisasi
        norm_val = normalize_text(raw_val)
        if norm_val in self.by_normalized_name:
            return self.by_normalized_name[norm_val]

        # 7. Substring / Token matching fallback
        for norm_bank_name, bank in self.by_normalized_name.items():
            if norm_val and (norm_val in norm_bank_name or norm_bank_name in norm_val):
                return bank

        return None

    def get_resolution_table(self) -> List[Dict[str, Any]]:
        """Mengembalikan tabel referensi resolusi entitas 21 Bank DU."""
        return [
            {
                "bank_id": b.Bank_ID,
                "masked_alias": b.Masked_Alias,
                "nama_resmi_bank": b.Nama_Resmi_Bank,
                "kelompok_kbmi": b.Kelompok_KBMI,
                "kode_bloomberg": b.Kode_Bloomberg,
                "kode_sppa_antasena": b.Kode_SPPA_Antasena,
            }
            for b in self.banks
        ]
