"""
Konfigurasi pytest: setiap sesi test memakai database SQLite sementara, sehingga database lokal
(`puva_eval.db`) tidak pernah tersentuh. Variabel lingkungan harus diset sebelum `database`/`main` diimpor.
"""
import os
import shutil
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

_TMP = tempfile.mkdtemp(prefix="puva_test_")
os.environ.pop("DATABASE_URL", None)
os.environ["DATABASE_PATH"] = os.path.join(_TMP, "test.db")
for _k in [k for k in os.environ if k.startswith("DOC_")]:  # dokumen memakai placeholder, bukan nama pejabat lokal
    os.environ.pop(_k)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    try:
        from database import engine
        engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TMP, ignore_errors=True)
