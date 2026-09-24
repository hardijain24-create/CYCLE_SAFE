import pytest
from fastapi.testclient import TestClient

def test_item7_map_anti_tampering_and_rate_limit():
    from cyclesafe.api.main import app
    client = TestClient(app)

    # 1. Token rotation attack from single client IP (127.0.0.1)
    tokens = ["token_attack_1", "token_attack_2", "token_attack_3", "token_attack_4"]

    # First checkin from token 1
    res1 = client.post(
        "/map/checkin",
        json={"location_id": "loc_01", "status": "empty", "products": ["sanitary_pads"]},
        headers={"device-token": tokens[0]}
    )
    assert res1.status_code in [200, 429]

    # Second checkin immediately from token 2 from SAME IP (127.0.0.1)
    res2 = client.post(
        "/map/checkin",
        json={"location_id": "loc_01", "status": "empty", "products": ["sanitary_pads"]},
        headers={"device-token": tokens[1]}
    )
    # Either rate-limited (429/400) or if allowed, label remains "Prototype Data" (NOT "Verified Community Data")
    if res2.status_code == 200:
        label = res2.json()["updated_location"]["data_label"]
        assert label != "Verified Community Data", "Token rotation attack from single IP must NOT grant 'Verified Community Data' label!"
