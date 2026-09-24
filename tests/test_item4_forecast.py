import pytest
import os
from fastapi.testclient import TestClient

def test_item4_forecast_unified_and_safe():
    from cyclesafe.api.main import app
    from cyclesafe.forecast import forecast_next_cycle

    client = TestClient(app)

    # 1. Direct call to forecast_next_cycle with safe path check
    res = forecast_next_cycle([28.0, 29.0, 27.0, 28.0, 30.0], artifact_path="models/cyclesafe_model_artifact.pkl")
    assert res["forecast_available"] == True
    # Confidence values should NOT be hardcoded constants like conf_mod=85 unconditionally
    assert "confidence_components" in res
    assert res["confidence_components"]["model"] != 85 or "coverage_per_tertile" in res

    # 2. Path traversal check (must raise ValueError if outside allowed models dir)
    with pytest.raises(ValueError):
        forecast_next_cycle([28.0, 29.0, 27.0], artifact_path="../untrusted/artifact.pkl")

    # 3. API /forecast route must call unified forecast function
    api_res = client.post("/forecast", json={
        "user_id": "u_fc_test",
        "cycles": [
            {"cycle_length_days": 28.0},
            {"cycle_length_days": 29.0},
            {"cycle_length_days": 27.0},
            {"cycle_length_days": 30.0}
        ]
    })
    assert api_res.status_code == 200
    fc_json = api_res.json()
    assert fc_json["status"] == "success"
    assert "confidence_components" in fc_json or "interval_details" in fc_json
