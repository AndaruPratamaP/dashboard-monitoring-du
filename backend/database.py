import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env jika ada (terutama untuk development lokal)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Deteksi DATABASE_URL (PostgreSQL untuk Supabase/Render atau SQLite untuk Lokal)
raw_db_url = os.environ.get("DATABASE_URL")

if raw_db_url:
    # Kompatibilitas SQLAlchemy 2.0: postgres:// -> postgresql://
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URL = raw_db_url
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,  # Otomatis merefresh koneksi stale/putus di cloud
    )
else:
    # Default Lokal: SQLite dengan WAL Mode
    DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "puva_eval.db"))
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30.0}
    )

    # Aktifkan WAL Mode hanya jika engine menggunakan SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if engine.dialect.name == "sqlite":
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()



SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



def ensure_schema():
    """
    Migrasi ringan untuk database yang sudah ada: create_all tidak menambah kolom baru
    ke tabel lama, jadi kolom model yang belum ada di database ditambahkan di sini.
    Kolom lama yang sudah tidak dipakai (mis. OM) dibiarkan dan diabaikan.
    """
    from sqlalchemy import inspect, text

    import models  # noqa: F401  (memastikan seluruh tabel terdaftar di metadata)

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            col_type = col.type.compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col_type}'))
