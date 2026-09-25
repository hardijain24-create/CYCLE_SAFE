"""Tests for POST /symptoms closed-list logging endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_symptom_logging_full_lifecycle():
    """Tests: auth, consent, allowlist validation, insert, retrieval, export inclusion, and deletion."""
    from cyclesafe.api.main import app
    client = TestClient(app)

    user_id = "symptom_test_user"

    # 1. Register consent and get token
    res = client.post("/consent", params={"user_id": user_id})
    assert res.status_code == 200
    token = res.json()["token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # 2. POST /symptoms with a valid allowlisted symptom
    res = client.post("/symptoms", params={"user_id": user_id},
                      json={"symptom": "cramps", "severity": 2, "log_date": "2026-09-01"},
                      headers=auth_header)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    assert res.json()["symptom"] == "cramps"
    assert res.json()["severity"] == 2

    # 3. POST another valid symptom
    res = client.post("/symptoms", params={"user_id": user_id},
                      json={"symptom": "bloating", "severity": 1},
                      headers=auth_header)
    assert res.status_code == 200

    # 4. POST an invalid (not in allowlist) symptom → 422
    res = client.post("/symptoms", params={"user_id": user_id},
                      json={"symptom": "self_diagnosed_endometriosis", "severity": 1},
                      headers=auth_header)
    assert res.status_code == 422, f"Expected 422 for invalid symptom, got {res.status_code}"

    # 5. POST without auth → 401
    res = client.post("/symptoms", params={"user_id": user_id},
                      json={"symptom": "cramps", "severity": 1})
    assert res.status_code == 401

    # 6. GET /symptoms returns logged entries
    res = client.get("/symptoms", params={"user_id": user_id}, headers=auth_header)
    assert res.status_code == 200
    symptoms = res.json()
    assert len(symptoms) == 2
    assert symptoms[0]["symptom"] == "cramps"

    # 7. GET /symptoms/allowed returns the full allowlist (no auth needed)
    res = client.get("/symptoms/allowed")
    assert res.status_code == 200
    allowed = res.json()["allowed_symptoms"]
    assert "cramps" in allowed
    assert "bloating" in allowed
    assert len(allowed) == 12  # the 12 allowlisted symptoms

    # 8. Export includes symptom data
    res = client.get("/export", params={"user_id": user_id}, headers=auth_header)
    assert res.status_code == 200
    export = res.json()
    assert export["data"]["symptom_count"] == 2
    assert len(export["data"]["symptoms"]) == 2

    # 9. DELETE /data removes symptoms too
    res = client.delete("/data", params={"user_id": user_id}, headers=auth_header)
    assert res.status_code == 200
    assert res.json()["deleted_counts"]["symptoms"] == 2
