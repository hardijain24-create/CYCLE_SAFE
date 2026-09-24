import pytest
from fastapi.testclient import TestClient

def test_item2_consent_full_lifecycle():
    from cyclesafe.api.main import app
    client = TestClient(app)

    user_id = "user_consent_test"

    # 1. POST /consent -> 200 + token
    res_consent = client.post(f"/consent?user_id={user_id}")
    assert res_consent.status_code == 200, f"Failed consent: {res_consent.text}"
    token = res_consent.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. POST /cycles x 6 -> 200
    for i in range(6):
        c_res = client.post(
            f"/cycles?user_id={user_id}",
            json={"cycle_length_days": 28.0 + (i % 2), "log_date": f"2026-0{(i+1):02d}-01"},
            headers=headers
        )
        assert c_res.status_code == 200, f"Cycle log {i} failed: {c_res.text}"

    # 3. GET /cycles -> returns 6 cycles
    g_res = client.get(f"/cycles?user_id={user_id}", headers=headers)
    assert g_res.status_code == 200
    assert len(g_res.json()) == 6, f"Expected 6 cycles, got {len(g_res.json())}"

    # 4. GET /export -> contains 6 cycles
    exp_res = client.get(f"/export?user_id={user_id}", headers=headers)
    assert exp_res.status_code == 200
    export_data = exp_res.json()
    assert export_data["data"]["cycle_count"] == 6

    # 5. DELETE /data -> deletes data
    del_res = client.delete(f"/data?user_id={user_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # 6. GET /export -> empty cycles
    exp_res2 = client.get(f"/export?user_id={user_id}", headers=headers)
    assert exp_res2.status_code == 200
    assert exp_res2.json()["data"]["cycle_count"] == 0

    # 7. POST /consent/withdraw -> 200
    w_res = client.post(f"/consent/withdraw?user_id={user_id}", headers=headers)
    assert w_res.status_code == 200
    assert w_res.json()["status"] == "withdrawn"

    # 8. POST /cycles returns 403 after withdrawal
    post_after = client.post(
        f"/cycles?user_id={user_id}",
        json={"cycle_length_days": 28.0},
        headers=headers
    )
    assert post_after.status_code == 403, f"Expected 403 after consent withdrawal, got {post_after.status_code}"
