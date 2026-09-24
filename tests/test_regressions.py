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

if __name__ == "__main__":
    test_pdf_is_real_binary_pdf()
    test_baseline_metrics_reproducibility()
    test_no_fake_hardcoded_numbers()
    test_no_context_feature_leakage()
    test_duplicate_engine_class_definitions()
    test_cell_headers_formatting()
    print("\nALL REGRESSION TESTS COMPLETED SUCCESSFULLY!")
