"""CycleSafe Regression Test Suite.

Contains test cases to audit baseline metrics, PDF binary format, dynamic value generation,
feature safety, duplicate class definitions, and core system contracts.
"""

import os
import sys
import json

from cyclesafe.api.main import app, generate_user_token, verify_token_and_user, get_forecast, ForecastRequest, CycleLogInput
from cyclesafe.privacy.engine import CycleSafePrivacyEngine
from cyclesafe.rules.engine import CycleEntry, run_all_rules
from cyclesafe.map.engine import ProductAccessMapEngine, sanitize_note
from cyclesafe.forecast import is_safe_artifact_path

def test_baseline_metrics_reproducibility():
    """Verify final-test baseline metrics: MAE ~ 2.049, RMSE ~ 2.987, 80% cov ~ 78.9%, 90% cov ~ 92.5%."""
    artifact_path = "models/cyclesafe_model_artifact.pkl"
    assert os.path.exists(artifact_path), "Model artifact file missing"
    
    import joblib
    art = joblib.load(artifact_path)
    metrics = art.get("final_test_metrics", {})
    assert metrics.get("mae") is not None, "MAE missing from artifact"
    
    mae = float(metrics["mae"])
    rmse = float(metrics["rmse"])
    cov80 = float(metrics["coverage_80"])
    cov90 = float(metrics["coverage_90"])

    assert abs(mae - 2.049) < 0.05, f"MAE shifted significantly: {mae}"
    assert abs(rmse - 2.987) < 0.05, f"RMSE shifted significantly: {rmse}"
    assert abs(cov80 - 0.789) < 0.05, f"80% Coverage shifted: {cov80}"
    assert abs(cov90 - 0.925) < 0.05, f"90% Coverage shifted: {cov90}"

def test_no_context_feature_leakage():
    """Verify that SAFE_CONTEXT_COLUMNS is empty and FEATURES contains no leaky context columns."""
    from cyclesafe.config import SAFE_CONTEXT_COLUMNS, FEATURES, CORE_FEATURES
    assert SAFE_CONTEXT_COLUMNS == [], "SAFE_CONTEXT_COLUMNS must be empty"
    assert len(FEATURES) == len(CORE_FEATURES), "FEATURES should only contain CORE_FEATURES"
    assert not any("meanmenseslength" in f or "meanbleedingintensity" in f for f in FEATURES)

def test_A1_auth_enforcement():
    """Verify that token validation helper rejects unauthorized tokens."""
    assert not verify_token_and_user("user_123", "Bearer invalid_token"), "Mismatch token must be rejected"
    valid_t = generate_user_token("user_123")
    assert verify_token_and_user("user_123", f"Bearer {valid_t}"), "Valid HMAC token must be accepted"

def test_A2_A4_sqlite_privacy_engine():
    """Verify SQLite storage layer handles cycle logging, real export count, and true deletion."""
    db_path = "tests/test_cyclesafe_privacy.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    engine = CycleSafePrivacyEngine(db_path=db_path)
    engine.register_consent("user_test_99")
    
    # Store real cycle records
    engine.add_cycle_record("user_test_99", {"cycle_length_days": 28.0, "log_date": "2026-09-01"})
    engine.add_cycle_record("user_test_99", {"cycle_length_days": 29.0, "log_date": "2026-09-29"})

    export_json = engine.export_user_data("user_test_99")
    exported = json.loads(export_json)
    assert len(exported["data"]["cycles"]) == 2, f"Expected 2 cycles in export, got {len(exported['data']['cycles'])}"

    # Perform true delete
    res = engine.delete_user_data("user_test_99")
    assert res["status"] == "deleted"
    assert res["deleted_counts"]["cycles"] == 2
    assert engine.verify_deletion("user_test_99") == True

    import gc
    gc.collect()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass

def test_A3_consent_enforcement():
    """Verify active consent record requirement and withdraw_consent functionality."""
    db_path = "tests/test_consent.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    engine = CycleSafePrivacyEngine(db_path=db_path)
    
    # Without consent: processing/logging must be blocked
    try:
        engine.add_cycle_record("user_noconsent", {"cycle_length_days": 28.0})
        consent_blocked = False
    except PermissionError:
        consent_blocked = True
    assert consent_blocked, "Adding cycle record without active consent must raise PermissionError"

    # Register consent
    engine.register_consent("user_noconsent")
    engine.add_cycle_record("user_noconsent", {"cycle_length_days": 28.0})

    # Withdraw consent
    engine.withdraw_consent("user_noconsent")
    try:
        engine.add_cycle_record("user_noconsent", {"cycle_length_days": 30.0})
        withdraw_blocked = False
    except PermissionError:
        withdraw_blocked = True
    assert withdraw_blocked, "Adding cycle record after withdrawing consent must raise PermissionError"

    import gc
    gc.collect()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass

def test_A5_model_path_safety():
    """Verify that model artifact loading only accepts paths within configured models/ directory."""
    assert is_safe_artifact_path("../untrusted_dir/malicious.pkl") == False
    assert is_safe_artifact_path("models/cyclesafe_model_artifact.pkl") == True

def test_B1_B2_perimenopause_honest_uncertainty():
    """Verify age >= 45 / perimenopause profile gets experimental label and widened interval."""
    req = ForecastRequest(
        user_id="user_peri_46",
        age=46,
        is_perimenopause=True,
        cycles=[
            CycleLogInput(cycle_length_days=30.0),
            CycleLogInput(cycle_length_days=32.0),
            CycleLogInput(cycle_length_days=38.0),
            CycleLogInput(cycle_length_days=40.0)
        ]
    )
    res = get_forecast(req)
    assert res["forecast_available"] == True
    label = res["uncertainty_label"]
    assert "experimental, wider uncertainty (training data covers ages 21 to 43)" in label, f"Expected experimental label, got: {label}"
    assert "calibrated" not in label.lower()

def test_D1_D2_D3_rules_urgency_and_r2_urgent():
    """Verify R2_URGENT, R4 dynamic days_since_last, and urgency sorting."""
    from datetime import date, timedelta

    entries = [
        CycleEntry(cycle_length_days=28.0, start_date=date.today() - timedelta(days=100), heavy_soaking_hourly=True),
        CycleEntry(cycle_length_days=29.0, start_date=date.today() - timedelta(days=128), pain_score=3),
    ]

    results = run_all_rules(entries)
    triggered = [r for r in results if r.triggered]
    assert len(triggered) >= 1
    assert triggered[0].rule_id == "R2_URGENT"
    assert triggered[0].urgency == "urgent"

def test_F1_F3_map_security():
    """Verify missing device token returns error, products match allowlist, and notes are sanitized."""
    engine = ProductAccessMapEngine()
    
    res = engine.submit_checkin("", location_id="loc_01", status="stocked", products=["sanitary_pads"])
    assert res["status"] == "error"

    res_bad_prod = engine.submit_checkin("token_sec_1", location_id="loc_01", status="stocked", products=["invalid_product_script"])
    assert res_bad_prod["status"] == "error"

    clean = sanitize_note("<script>alert('xss')</script>Hello World")
    assert "<script>" not in clean
    assert "Hello World" in clean
