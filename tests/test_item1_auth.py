import pytest
from fastapi.testclient import TestClient

def test_item1_auth_real_entrypoint():
    from cyclesafe.api.main import app
    client = TestClient(app)

    # 1. No Authorization header -> 401
    res_no_auth = client.get("/export?user_id=user_auth_1")
    assert res_no_auth.status_code == 401, f"Expected 401 on missing auth header, got {res_no_auth.status_code}"

    # 2. Forged token_victim -> 403
    res_forged = client.get("/export?user_id=user_auth_1", headers={"Authorization": "Bearer token_user_auth_1"})
    assert res_forged.status_code == 403, f"Expected 403 on forged token_victim, got {res_forged.status_code}"

    # Register user_auth_1 & user_auth_2 via POST /consent
    res_c1 = client.post("/consent?user_id=user_auth_1")
    assert res_c1.status_code == 200
    token1 = res_c1.json()["token"]

    res_c2 = client.post("/consent?user_id=user_auth_2")
    assert res_c2.status_code == 200
    token2 = res_c2.json()["token"]

    # 3. Other user's token -> 403
    res_other = client.get("/export?user_id=user_auth_2", headers={"Authorization": f"Bearer {token1}"})
    assert res_other.status_code == 403, f"Expected 403 when using token1 for user_auth_2, got {res_other.status_code}"

    # 4. Own token -> 200
    res_own = client.get("/export?user_id=user_auth_1", headers={"Authorization": f"Bearer {token1}"})
    assert res_own.status_code == 200, f"Expected 200 for own token, got {res_own.status_code}"
