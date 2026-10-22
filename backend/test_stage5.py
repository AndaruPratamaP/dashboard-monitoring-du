"""
Verification test for Stage 5: Snapshot Locking and Document Generator
"""
import os
import sys

# Ensure backend directory is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_stage5_flow():
    print("=== Testing Stage 5: Snapshot & Document Generator ===")

    # 1. Check Snapshot Status
    res = client.get("/api/snapshot/status")
    assert res.status_code == 200, f"Status check failed: {res.text}"
    status_data = res.json()
    print(f"1. Initial Snapshot Status: is_locked={status_data['is_locked']}, stage={status_data['stage']}")

    # 2. Lock Snapshot
    lock_res = client.post("/api/snapshot/lock", json={"locked_by": "Penguji BI Live Demo"})
    assert lock_res.status_code == 200, f"Lock snapshot failed: {lock_res.text}"
    lock_data = lock_res.json()
    print(f"2. Locked Snapshot: id={lock_data['snapshot_id']}, locked_at={lock_data['locked_at']}")

    # Check status again
    res = client.get("/api/snapshot/status")
    status_data = res.json()
    assert status_data["is_locked"] is True
    assert status_data["snapshot_id"] == lock_data["snapshot_id"]
    print("   Verified snapshot is now LOCKED.")

    # 3. Test Preview M.02 & M.01
    prev_m02 = client.get("/api/export/preview/m02")
    assert prev_m02.status_code == 200
    p02 = prev_m02.json()
    assert p02["type"] == "M.02"
    assert "default_narration" in p02
    assert len(p02["findings"]) > 0
    print(f"3. Preview M.02 OK: {p02['title']}, findings count={len(p02['findings'])}")

    prev_m01 = client.get("/api/export/preview/m01")
    assert prev_m01.status_code == 200
    p01 = prev_m01.json()
    assert p01["type"] == "M.01"
    assert "categories" in p01
    print(f"   Preview M.01 OK: {p01['title']}, lulus={len(p01['categories']['lulus'])}, pembinaan={len(p01['categories']['pembinaan'])}")

    # 4. Test Export M.02 docx
    m02_res = client.get("/api/export/memo/m02?masked=false")
    assert m02_res.status_code == 200
    assert len(m02_res.content) > 1000
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in m02_res.headers["content-type"]
    print(f"4. Export M.02 .docx OK: {len(m02_res.content)} bytes received")

    # 5. Test Export M.01 docx
    m01_res = client.get("/api/export/memo/m01?masked=true")
    assert m01_res.status_code == 200
    assert len(m01_res.content) > 1000
    print(f"5. Export M.01 .docx OK: {len(m01_res.content)} bytes received")

    # 6. Test Export M.02 with custom narration POST
    custom_res = client.post(
        "/api/export/memo/m02/generate",
        json={
            "custom_narration": "Ini adalah narasi eksekutif kustom hasil pengeditan langsung di Live Preview UI sebelum diunduh.",
            "masked": False
        }
    )
    assert custom_res.status_code == 200
    assert len(custom_res.content) > 1000
    print(f"6. Export M.02 with custom narration OK: {len(custom_res.content)} bytes")

    # 7. Test Export Attachments .xlsx
    att_res = client.get("/api/export/attachments?masked=false")
    assert att_res.status_code == 200
    assert len(att_res.content) > 1000
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in att_res.headers["content-type"]
    print(f"7. Export Paket 3 Lampiran .xlsx OK: {len(att_res.content)} bytes received")

    # 8. Unlock Snapshot
    unlock_res = client.post("/api/snapshot/unlock")
    assert unlock_res.status_code == 200
    unlock_data = unlock_res.json()
    assert unlock_data["is_locked"] is False
    print("8. Snapshot unlocked successfully.")

    print("\n>>> ALL STAGE 5 BACKEND TESTS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    test_stage5_flow()
