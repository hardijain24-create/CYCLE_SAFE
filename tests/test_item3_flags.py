import pytest
from fastapi.testclient import TestClient

def test_item3_flags_no_crash_and_reachable_rules():
    from cyclesafe.api.main import app
    client = TestClient(app)

    # Input containing log_date, heavy_soaking_hourly, last_period_date, hot_flash_count, etc.
    req_payload = {
        "user_id": "user_flags_test",
        "age": 47,
        "is_perimenopause": True,
        "cycles": [
            {
                "cycle_length_days": 18.0,
                "log_date": "2026-05-01",
                "pain_score": 3,
                "heavy_soaking_hourly": True,
                "hot_flash_count": 3,
                "hot_flash_severity": 2,
                "night_sweats": True,
                "last_period_date": "2026-01-01"
            },
            {
                "cycle_length_days": 19.0,
                "log_date": "2026-06-01",
                "pain_score": 3,
                "heavy_soaking_hourly": True,
                "hot_flash_count": 4,
                "hot_flash_severity": 2,
                "night_sweats": True
            },
            {
                "cycle_length_days": 20.0,
                "log_date": "2026-07-01",
                "pain_score": 3,
                "heavy_soaking_hourly": True,
                "hot_flash_count": 5,
                "hot_flash_severity": 2,
                "night_sweats": True
            },
            {
                "cycle_length_days": 18.0,
                "log_date": "2026-08-01",
                "pain_score": 3,
                "heavy_soaking_hourly": True,
                "hot_flash_count": 2,
                "hot_flash_severity": 2,
                "night_sweats": True
            }
        ]
    }

    res = client.post("/flags", json=req_payload)
    # Must return 200, NOT 500 crash
    assert res.status_code == 200, f"Expected 200 from /flags, got {res.status_code}: {res.text}"

    data = res.json()
    triggered_ids = [r["rule_id"] for r in data["triggered_rules"]]

    # Must contain R1, R2_URGENT, R4 (if last_period_date supplied > 90d ago) or R7_PERI / R3
    assert "R1" in triggered_ids, f"Expected R1 in triggered rules: {triggered_ids}"
    assert "R2_URGENT" in triggered_ids, f"Expected R2_URGENT in triggered rules: {triggered_ids}"
    assert "R7_PERI" in triggered_ids or "R3" in triggered_ids, f"Expected R7_PERI or R3 in triggered rules: {triggered_ids}"
