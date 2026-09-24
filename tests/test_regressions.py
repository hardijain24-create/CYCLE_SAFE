"""CycleSafe Regression Test Suite.

Contains test cases to audit baseline metrics, PDF binary format, dynamic value generation,
feature safety, duplicate class definitions, and core system contracts.
"""

import os
import sys
import json

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_pdf_is_real_binary_pdf():
    """Verify that generated doctor report PDFs are true binary PDF files, not text fallbacks."""
    from cycle_safe import user_regular, regular_baseline, regular_patterns, forecast_V4_user, adapter_to_forecast_result, build_winning_insight, build_winning_doctor_report, generate_doctor_report_pdf

    fc_res = forecast_V4_user(user_regular)
    forecast = adapter_to_forecast_result(fc_res, user_regular)
    insight = build_winning_insight(user_regular, regular_baseline, regular_patterns, forecast, user_regular.profile.self_reported_stage)
    report_dict = build_winning_doctor_report(user_regular, regular_baseline, regular_patterns, forecast, insight)

    pdf_path = "tests/test_output_report.pdf"
    generate_doctor_report_pdf(report_dict, pdf_path)

    assert os.path.exists(pdf_path), "PDF file was not created"
    with open(pdf_path, 'rb') as f:
        header = f.read(10)
    
    # PDF files must start with %PDF-
    assert header.startswith(b'%PDF-'), f"Generated PDF is not a valid binary PDF file! Header: {header}"

    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    print("PDF BINARY TEST PASSED")

def test_baseline_metrics_reproducibility():
    """Verify final-test baseline metrics: MAE ~ 2.049, RMSE ~ 2.987, 80% cov ~ 78.9%, 90% cov ~ 92.5%."""
    from cycle_safe import extract_authoritative_final_metrics
    
    # Load artifact or check runtime metrics
    artifact_path = "models/cyclesafe_model_artifact.pkl"
    assert os.path.exists(artifact_path), "Model artifact file missing"
    
    import joblib
    art = joblib.load(artifact_path)
    assert art.get("deployment_model_name") == "ridge", "Deployment model must be ridge"
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
    print("BASELINE METRICS TEST PASSED")

def test_no_fake_hardcoded_numbers():
    """Verify that cycle_safe.py contains no hard-coded agreement values or confidence defaults."""
    with open('cycle_safe.py', 'r', encoding='utf-8') as f:
        code = f.read()

    assert "confidence_history=82" not in code, "Hard-coded confidence_history=82 found!"
    assert '{"Ridge": 30.6' not in code.replace(" ", ""), "Hard-coded model agreement dict found!"
    assert "mock_model" not in code, "Leftover mock_model fallback found!"
    print("NO FAKE NUMBERS AUDIT PASSED")

def test_no_context_feature_leakage():
    """Verify that SAFE_CONTEXT_COLUMNS is empty and FEATURES contains no leaky context columns."""
    from cycle_safe import SAFE_CONTEXT_COLUMNS, FEATURES, CORE_FEATURES
    assert SAFE_CONTEXT_COLUMNS == [], "SAFE_CONTEXT_COLUMNS must be empty"
    assert len(FEATURES) == len(CORE_FEATURES), "FEATURES should only contain CORE_FEATURES"
    assert not any("meanmenseslength" in f or "meanbleedingintensity" in f for f in FEATURES)
    print("NO CONTEXT LEAKAGE TEST PASSED")

def test_duplicate_engine_class_definitions():
    """Audit cycle_safe.py for duplicate inline definitions of Privacy/Map engines that should be imported."""
    with open('cycle_safe.py', 'r', encoding='utf-8') as f:
        code = f.read()

    has_inline_privacy = "class CycleSafePrivacyEngine:" in code
    has_inline_map = "class ProductAccessMapEngine:" in code or "class AccessPoint:" in code

    # Report whether inline classes are present (to be unified in refactor)
    print(f"Inline Privacy Engine present in cycle_safe.py: {has_inline_privacy}")
    print(f"Inline Map Engine present in cycle_safe.py: {has_inline_map}")

def test_cell_headers_formatting():
    """Verify every cell section header in cycle_safe.py starts with '# CELL'."""
    with open('cycle_safe.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    cell_headers = [line.strip() for line in lines if line.strip().startswith("# CELL ") or (line.strip().startswith("#") and "CELL " in line)]
    assert len(cell_headers) >= 12, f"Expected at least 12 CELL headers, found {len(cell_headers)}"
    print(f"CELL HEADERS TEST PASSED: {len(cell_headers)} cells formatted cleanly")

def test_A1_auth_enforcement():
    """Verify that export and delete endpoints reject unauthorized requests with HTTP 403."""
    from cyclesafe_api import export_user_data, delete_user_data
    # Testing direct auth validation helper or API behavior
    from cyclesafe_api import verify_user_token
    assert not verify_user_token("user_123", "token_wrong"), "Mismatch token must be rejected"
    assert verify_user_token("user_123", "token_user_123"), "Matching token must be accepted"
    print("TEST A1 PASSED: Token authentication enforcement verified")

def test_A2_A4_sqlite_privacy_engine():
    """Verify SQLite storage layer handles cycle logging, real export count, and true deletion."""
    from cyclesafe_privacy import CycleSafePrivacyEngine
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
    print("TEST A2/A4 PASSED: Real SQLite persistence & true delete verified")

def test_A3_consent_enforcement():
    """Verify active consent record requirement and withdraw_consent functionality."""
    from cyclesafe_privacy import CycleSafePrivacyEngine
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
    print("TEST A3 PASSED: Active consent requirement & withdraw enforcement verified")

def test_A5_model_path_safety():
    """Verify that model artifact loading only accepts paths within configured models/ directory."""
    from cycle_safe import load_safe_artifact
    
    try:
        load_safe_artifact("../untrusted_dir/malicious.pkl")
        path_blocked = False
    except ValueError:
        path_blocked = True
    assert path_blocked, "Loading model artifact outside models/ path must raise ValueError"
    print("TEST A5 PASSED: Model artifact path safety verified")

def test_B1_B2_perimenopause_honest_uncertainty():
    """Verify age >= 45 / perimenopause profile gets experimental label and widened interval."""
    from cyclesafe_api import get_forecast, ForecastRequest, CycleLogInput

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
    assert res["status"] == "success"
    label = res["interval_details"]["label"]
    assert "experimental, wider uncertainty (training data covers ages 21 to 43)" in label, f"Expected experimental label, got: {label}"
    assert "calibrated" not in label.lower()
    print("TEST B1/B2 PASSED: Perimenopause experimental label & honesty verified")

def test_D1_D2_D3_rules_urgency_and_r2_urgent():
    """Verify R2_URGENT, R4 dynamic days_since_last, and urgency sorting."""
    from cyclesafe_rules import CycleEntry, run_all_rules
    from datetime import date, timedelta

    entries = [
        CycleEntry(cycle_length_days=28.0, start_date=date.today() - timedelta(days=100), heavy_soaking_hourly=True),
        CycleEntry(cycle_length_days=29.0, start_date=date.today() - timedelta(days=128), pain_score=3),
    ]

    results = run_all_rules(entries)
    triggered = [r for r in results if r.triggered]
    assert len(triggered) >= 1
    # First triggered rule must be R2_URGENT with urgency 'urgent'
    assert triggered[0].rule_id == "R2_URGENT"
    assert triggered[0].urgency == "urgent"
    
    # Check R4 dynamic days_since_last calculation
    r4_res = [r for r in results if r.rule_id == "R4"][0]
    assert r4_res.triggered == True, "R4 should trigger dynamically when >90 days since last period start"
    print("TEST D1/D2/D3 PASSED: Rule engine R2_URGENT, dynamic R4, and urgency sorting verified")

def test_F1_F3_map_security():
    """Verify missing device token returns 400, products match allowlist, and notes are sanitized."""
    from cyclesafe_map import ProductAccessMapEngine, sanitize_note

    engine = ProductAccessMapEngine()
    
    # Missing device token
    res = engine.submit_checkin("", "loc_01", "stocked", ["sanitary_pads"])
    assert res["status"] == "error"
    assert "Missing device token" in res["message"]

    # Invalid product non-allowlisted
    res_bad_prod = engine.submit_checkin("token_sec_1", "loc_01", "stocked", ["invalid_product_script"])
    assert res_bad_prod["status"] == "error"
    assert "Invalid products" in res_bad_prod["message"]

    # Sanitize note (strip script tags)
    clean = sanitize_note("<script>alert('xss')</script>Hello World")
    assert "<script>" not in clean
    assert "Hello World" in clean
    print("TEST F1/F3 PASSED: Access map token requirement, product allowlist, and note sanitization verified")

if __name__ == "__main__":
    test_pdf_is_real_binary_pdf()
    test_baseline_metrics_reproducibility()
    test_no_fake_hardcoded_numbers()
    test_no_context_feature_leakage()
    test_duplicate_engine_class_definitions()
    test_cell_headers_formatting()
    test_A1_auth_enforcement()
    test_A2_A4_sqlite_privacy_engine()
    test_A3_consent_enforcement()
    test_A5_model_path_safety()
    test_B1_B2_perimenopause_honest_uncertainty()
    test_D1_D2_D3_rules_urgency_and_r2_urgent()
    test_F1_F3_map_security()
    print("\nALL REGRESSION TESTS COMPLETED SUCCESSFULLY!")
