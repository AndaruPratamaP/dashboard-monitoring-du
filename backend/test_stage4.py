from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("=== TEST 1: POST /api/reconciliation/{finding_id}/analyze (Bank R B7a) ===")
res_r = client.post("/api/reconciliation/FND-2026Q2-DU18-B7A/analyze")
print("Status:", res_r.status_code)
ai_r = res_r.json()["ai_result"]
print("Bank R AI Recommendation:", ai_r["recommendation_status"])
print("Analysis:", ai_r["analysis_text"][:120], "...")
assert res_r.status_code == 200
assert ai_r["recommendation_status"] == "RECOMMEND_REJECT"

print("\n=== TEST 2: POST /api/reconciliation/{finding_id}/analyze (Bank A B2) ===")
res_a = client.post("/api/reconciliation/FND-2026Q2-DU01-B2/analyze")
print("Status:", res_a.status_code)
ai_a = res_a.json()["ai_result"]
print("Bank A AI Recommendation:", ai_a["recommendation_status"])
print("Analysis:", ai_a["analysis_text"][:120], "...")
assert res_a.status_code == 200
assert ai_a["recommendation_status"] == "RECOMMEND_APPROVE"

print("\n=== TEST 3: POST /api/disputes/submit (Bank DU submits dispute) ===")
res_disp = client.post(
    "/api/disputes/submit",
    data={
        "finding_id": "FND-2026Q2-DU01-B2",
        "nilai_klaim_bank": "85.00% (51/60 Hari Kerja)",
        "alasan_sanggahan": "Spread kuotasi 18 bps telah sesuai batas aturan 20 bps di terminal Bloomberg internal.",
    }
)
print("Status:", res_disp.status_code, "Message:", res_disp.json()["message"])
assert res_disp.status_code == 200
assert res_disp.json()["data"]["bi_decision_status"] == "PENDING_REVIEW"

print("\n=== TEST 4: POST /api/reconciliation/{finding_id}/decide (Petugas BI Approves Bank A) ===")
res_dec = client.post(
    "/api/reconciliation/FND-2026Q2-DU01-B2/decide",
    data={
        "decision": "APPROVED",
        "verified_by": "Verifikator DPPK Bank Indonesia",
        "notes": "Sanggahan diterima sesuai rekomendasi AI dan bukti terminal 18 bps."
    }
)
print("Status:", res_dec.status_code)
print("Decision Result:", res_dec.json()["data"])
assert res_dec.status_code == 200
assert res_dec.json()["data"]["decision"] == "APPROVED"
assert res_dec.json()["data"]["updated_bank_matrix"]["total_puva_score"] == 60.0
assert res_dec.json()["data"]["updated_bank_matrix"]["compliance_status"] == "MEMENUHI"

print("\n=== TEST 5: POST /api/notifications/ews/send-reminder (EWS Email) ===")
res_ews = client.post(
    "/api/notifications/ews/send-reminder",
    data={"bank_id": "DU-18"}
)
print("Status:", res_ews.status_code)
print("Receipt:", res_ews.json()["delivery_receipt"])
assert res_ews.status_code == 200
assert res_ews.json()["delivery_receipt"]["bank_alias"] == "Bank R"

print("\n=== TEST 6: GET /api/audit-trail ===")
res_audit = client.get("/api/audit-trail?limit=5")
print("Status:", res_audit.status_code, "Count:", len(res_audit.json()))
assert res_audit.status_code == 200
for log in res_audit.json()[:3]:
    print(f"  [{log['action']}] {log['performed_by']}: {log['details'][:80]}...")

print("\nALL STAGE 4 BACKEND TESTS PASSED WITH 100% SUCCESS!")
