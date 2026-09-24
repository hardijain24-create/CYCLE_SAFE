import re
import os

with open('cycle_safe.py', 'r', encoding='utf-8') as f:
    code = f.read()

# FIX 1
code = re.sub(
    r"SAFE_CONTEXT_COLUMNS = \[\s*\"age\",\s*\"bmi\",\s*\"lengthofmenses\",\s*\"totalmensescore\",\s*\"numberofdaysofintercourse\",\s*\"intercourseinfertilewindow\",\s*\"unusualbleeding\",\s*\"breastfeeding\",\s*\]",
    "SAFE_CONTEXT_COLUMNS = []",
    code
)

# FIX 2
forecast_V4_user_orig = """def forecast_V4_user(timeline: UserTimeline, artifact_path=ARTIFACT_PATH):
    stage = getattr(timeline.profile, "self_reported_stage", LifeStage.UNKNOWN)
    cycles = timeline_cycle_lengths(timeline)

    result = {
        "user_id": timeline.profile.user_id,
        "life_stage": stage.value if hasattr(stage, "value") else str(stage),
        "forecast_available": False,
        "forecast": None,
        "message": None,
        "model_agreement_details": {"Ridge": 30.6, "Random Forest": 31.4, "Extra Trees": 31.1, "Gradient Boost": 31.3},
        "model_agreement_spread": 0.8
    }

    if stage == LifeStage.MENOPAUSE:
        result["message"] = "Menopause stage is recorded. CycleSafe does not issue a normal next-cycle forecast."
        return result

    if len(cycles) < MIN_HISTORY_FOR_MODEL:
        result["message"] = f"At least {MIN_HISTORY_FOR_MODEL} completed cycles are needed for the forecast."
        return result

    if stage == LifeStage.PERIMENOPAUSE:
        result["message"] = "The self-reported perimenopause context is retained."

    try:
        from cycle_safe import forecast_next_cycle
        forecast = forecast_next_cycle(cycles, previous_context=timeline_context(timeline), artifact_path=artifact_path)
    except Exception:
        forecast = forecast_next_cycle_fallback(cycles)

    result["forecast_available"] = True
    result["forecast"] = forecast
    return result"""

forecast_V4_user_new = """def forecast_V4_user(timeline: UserTimeline, artifact_path=ARTIFACT_PATH):
    stage = getattr(timeline.profile, "self_reported_stage", LifeStage.UNKNOWN)
    cycles = timeline_cycle_lengths(timeline)

    result = {
        "user_id": timeline.profile.user_id,
        "life_stage": stage.value if hasattr(stage, "value") else str(stage),
        "forecast_available": False,
        "forecast": None,
        "message": None,
        "model_agreement_details": {},
        "model_agreement_spread": None
    }

    if stage == LifeStage.MENOPAUSE:
        result["message"] = "Menopause stage is recorded. CycleSafe does not issue a normal next-cycle forecast."
        return result

    if len(cycles) < MIN_HISTORY_FOR_MODEL:
        result["message"] = f"At least {MIN_HISTORY_FOR_MODEL} completed cycles are needed for the forecast."
        return result

    if stage == LifeStage.PERIMENOPAUSE:
        result["message"] = "The self-reported perimenopause context is retained."

    forecast = forecast_next_cycle(cycles, previous_context=timeline_context(timeline), artifact_path=artifact_path)
    
    import joblib
    import pandas as pd
    try:
        artifact = joblib.load(artifact_path)
        feats = pd.DataFrame([history_features(cycles, timeline_context(timeline))])
        for f in FEATURES:
            if f not in feats.columns:
                feats[f] = 0.0
        preds = {}
        if "all_models" in artifact:
            for name, model in artifact["all_models"].items():
                preds[name] = float(model.predict(feats[FEATURES])[0])
            result["model_agreement_details"] = preds
            if preds:
                result["model_agreement_spread"] = max(preds.values()) - min(preds.values())
            else:
                result["model_agreement_spread"] = 0.0
    except Exception:
        pass

    result["forecast_available"] = True
    result["forecast"] = forecast
    return result"""

if forecast_V4_user_orig in code:
    code = code.replace(forecast_V4_user_orig, forecast_V4_user_new)
else:
    print("WARNING: forecast_V4_user_orig NOT FOUND")

# FIX 3
adapter_orig = """def adapter_to_forecast_result(adapter_result):
    if not adapter_result.get("forecast_available"):
        return ForecastResult(predicted_cycle_length_days=None, lower_80_days=None, upper_80_days=None, lower_90_days=None, upper_90_days=None, predicted_absolute_error_days=None, method="No forecast generated")

    f = adapter_result["forecast"]
    r80 = f.get("estimated_range_80_percent", {})
    r90 = f.get("estimated_range_90_percent", {})

    return ForecastResult(
        predicted_cycle_length_days=f.get("predicted_cycle_length_days"),
        lower_80_days=r80.get("lower_days"),
        upper_80_days=r80.get("upper_days"),
        lower_90_days=r90.get("lower_days"),
        upper_90_days=r90.get("upper_days"),
        predicted_absolute_error_days=None,
        method=f.get("deployment_model", "CycleSafe V4"),
        model_agreement_details=adapter_result.get("model_agreement_details", {}),
        model_agreement_spread=adapter_result.get("model_agreement_spread", 0.0),
        confidence_history=82,
        confidence_pattern=61,
        confidence_model=91,
        confidence_overall="Moderate"
    )"""

adapter_new = """def adapter_to_forecast_result(adapter_result, timeline):
    if not adapter_result.get("forecast_available"):
        return ForecastResult(predicted_cycle_length_days=None, lower_80_days=None, upper_80_days=None, lower_90_days=None, upper_90_days=None, predicted_absolute_error_days=None, method="No forecast generated")

    f = adapter_result["forecast"]
    r80 = f.get("estimated_range_80_percent", {})
    r90 = f.get("estimated_range_90_percent", {})
    
    cycles = timeline_cycle_lengths(timeline)
    confidence_history = int(min(100, len(cycles) / 8.0 * 100))
    
    import numpy as np
    std_of_last_3 = np.std(cycles[-3:]) if len(cycles) >= 3 else 0
    confidence_pattern = int(max(0, min(100, 100 - std_of_last_3 * 10)))
    spread = adapter_result.get("model_agreement_spread") or 0.0
    confidence_model = int(max(0, min(100, 100 - spread * 20)))
    avg_conf = (confidence_history + confidence_pattern + confidence_model) / 3.0
    
    if avg_conf > 80: confidence_overall = "High"
    elif avg_conf > 50: confidence_overall = "Moderate"
    else: confidence_overall = "Low"

    return ForecastResult(
        predicted_cycle_length_days=f.get("predicted_cycle_length_days"),
        lower_80_days=r80.get("lower_days"),
        upper_80_days=r80.get("upper_days"),
        lower_90_days=r90.get("lower_days"),
        upper_90_days=r90.get("upper_days"),
        predicted_absolute_error_days=None,
        method=f.get("deployment_model", "CycleSafe V4"),
        model_agreement_details=adapter_result.get("model_agreement_details", {}),
        model_agreement_spread=spread,
        confidence_history=confidence_history,
        confidence_pattern=confidence_pattern,
        confidence_model=confidence_model,
        confidence_overall=confidence_overall
    )"""

if adapter_orig in code:
    code = code.replace(adapter_orig, adapter_new)
else:
    print("WARNING: adapter_orig NOT FOUND")

code = code.replace("regular_forecast = adapter_to_forecast_result(forecast_V4_user(user_regular))", "regular_forecast = adapter_to_forecast_result(forecast_V4_user(user_regular), user_regular)")
code = code.replace("peri_forecast = adapter_to_forecast_result(forecast_V4_user(user_peri))", "peri_forecast = adapter_to_forecast_result(forecast_V4_user(user_peri), user_peri)")
code = code.replace("meno_forecast = adapter_to_forecast_result(forecast_V4_user(user_meno))", "meno_forecast = adapter_to_forecast_result(forecast_V4_user(user_meno), user_meno)")

# FIX 4
fallback_orig = '''def forecast_next_cycle_fallback(cycles):
    """Fallback if no model exists."""
    if len(cycles) == 0: return None
    med = float(np.median(cycles))
    return {
        "predicted_cycle_length_days": med,
        "estimated_range_80_percent": {"lower_days": med-2, "upper_days": med+2},
        "estimated_range_90_percent": {"lower_days": med-3, "upper_days": med+3},
        "deployment_model": "Fallback Median"
    }'''
code = code.replace(fallback_orig, "")

code = re.sub(r'forecast_next_cycle_real = forecast_next_cycle\n?', '', code)

explain_orig = """    try:
        if "forecast_next_cycle_real" in globals():
            forecast = forecast_next_cycle_real(cycles, artifact_path=artifact_path)
        else:
            forecast = forecast_next_cycle(cycles, artifact_path=artifact_path)
    except NameError:
        forecast = {
            "predicted_cycle_length_days": 28.0,
            "estimated_range_80_percent": {"lower_days": 26, "upper_days": 30},
            "estimated_range_90_percent": {"lower_days": 25, "upper_days": 31},
            "deployment_model": "mock_model",
            "model_disagreement_days": 0.5
        }"""
explain_new = """    forecast = forecast_next_cycle(cycles, artifact_path=artifact_path)"""
if explain_orig in code:
    code = code.replace(explain_orig, explain_new)
else:
    print("WARNING: explain_orig NOT FOUND")

# Remove mock result block
mock_result_orig = """if "result" not in globals():
    result = {
        "model_data": pd.DataFrame({"user_id":["demo"], "cycle_number":[1], "target":[28], "history_count":[5]}),
        "deployment_model": None,
        "deployment_model_name": "personal_mean",
        "artifact": {"features": ["personal_mean", "personal_median", "lag_1", "mean_3"]},
        "development": pd.DataFrame({"user_id":["demo"], "cycle_number":[1], "target":[28], "personal_mean":[28], "personal_median":[28], "lag_1":[28], "mean_3":[28]}),
        "final_test": pd.DataFrame({"user_id":["demo"], "cycle_number":[2], "target":[29], "personal_mean":[28], "personal_median":[28], "lag_1":[28], "mean_3":[28]}),
        "final_test_predictions": np.array([28]),
        "results": pd.DataFrame({"model": ["personal_mean"], "mae": [1.0]})
    }"""
if mock_result_orig in code:
    code = code.replace(mock_result_orig, "")
else:
    print("WARNING: mock_result_orig NOT FOUND")

# FIX 5
summary_orig = """    summary = pd.DataFrame([
        {"metric": "Train MAE (days)", "value": round(train_mae, 3), "status": "Baseline Fit"},
        {"metric": "Rolling OOF MAE (days)", "value": round(oof_mae, 3), "status": "Development OOF"},
        {"metric": "Train -> OOF Gap (Overfitting)", "value": round(train_oof_gap, 3), "status": "Healthy Fit" if train_oof_gap < 0.5 else "Moderate Gap"},
        {"metric": "Train -> OOF Gap Ratio", "value": f"{train_oof_ratio:.1%}", "status": "Low Overfit" if train_oof_ratio < 0.25 else "Check Variance"},
        {"metric": "Untouched Holdout MAE (days)", "value": round(test_mae, 3), "status": "Final Holdout"},
        {"metric": "OOF -> Test Shift (Temporal Drift)", "value": round(oof_test_shift, 3), "status": "Stable Generalization" if abs(oof_test_shift) < 0.3 else "Shift Observed"},
        {"metric": "Within +/- 1-Day Accuracy", "value": f"{acc_1day:.1%}", "status": "Within +/- 1 Day"},
        {"metric": "Within +/- 2-Day Accuracy", "value": f"{acc_2day:.1%}", "status": "Within +/- 2 Days"},
        {"metric": "Within +/- 3-Day Accuracy", "value": f"{acc_3day:.1%}", "status": "Within +/- 3 Days"},
        {"metric": "Irregular Shift Precision", "value": f"{precision:.1%}", "status": "False Alarm Prevention"},
        {"metric": "Irregular Shift Recall", "value": f"{recall:.1%}", "status": "Shift Detection Rate"},
        {"metric": "Irregular Shift F1-Score", "value": round(f1_score, 3), "status": "Balanced Accuracy"}
    ])"""
summary_new = """    summary = pd.DataFrame([
        {"metric": "Train MAE (days)", "value": round(train_mae, 3), "status": "Baseline Fit"},
        {"metric": "Rolling OOF MAE (days)", "value": round(oof_mae, 3), "status": "Development OOF"},
        {"metric": "Train -> OOF Gap (Overfitting)", "value": round(train_oof_gap, 3), "status": f"{train_oof_gap:.3f} days"},
        {"metric": "Train -> OOF Gap Ratio", "value": f"{train_oof_ratio:.1%}", "status": f"{train_oof_ratio:.1%}"},
        {"metric": "Untouched Holdout MAE (days)", "value": round(test_mae, 3), "status": "Final Holdout"},
        {"metric": "OOF -> Test Shift (Temporal Drift)", "value": round(oof_test_shift, 3), "status": f"{oof_test_shift:.3f} days"},
        {"metric": "Within +/- 1-Day Accuracy", "value": f"{acc_1day:.1%}", "status": "Within +/- 1 Day"},
        {"metric": "Within +/- 2-Day Accuracy", "value": f"{acc_2day:.1%}", "status": "Within +/- 2 Days"},
        {"metric": "Within +/- 3-Day Accuracy", "value": f"{acc_3day:.1%}", "status": "Within +/- 3 Days"},
        {"metric": "Irregular Shift Precision", "value": f"{precision:.1%}", "status": "False Alarm Prevention"},
        {"metric": "Irregular Shift Recall", "value": f"{recall:.1%}", "status": "Shift Detection Rate"},
        {"metric": "Irregular Shift F1 (Regressor Thresholding, Deprecated)", "value": round(f1_score, 3), "status": "See Cell 12 Dedicated Classifier"}
    ])"""
if summary_orig in code:
    code = code.replace(summary_orig, summary_new)
else:
    print("WARNING: summary_orig NOT FOUND")

# FIX 6
data_quality_orig = """    data_quality = {
        "history_length": len(cycle_lengths),
        "missing_values": "Low" if baseline.data_completeness_score.get('cycle_logging_pct', 0) > 80 else "High",
        "recent_consistency": "High" if not patterns.cycle_change_detected else "Moderate",
        "eligible_for_forecast": forecast.predicted_cycle_length_days is not None
    }"""
data_quality_new = """    if len(cycle_lengths) == 0:
        missing_values = "N/A (0 cycles logged)"
        recent_consistency = "N/A"
    else:
        missing_values = "Low" if baseline.data_completeness_score.get('cycle_logging_pct', 0) > 80 else "High"
        recent_consistency = "High" if not patterns.cycle_change_detected else "Moderate"

    data_quality = {
        "history_length": len(cycle_lengths),
        "missing_values": missing_values,
        "recent_consistency": recent_consistency,
        "eligible_for_forecast": forecast.predicted_cycle_length_days is not None
    }"""
if data_quality_orig in code:
    code = code.replace(data_quality_orig, data_quality_new)
else:
    print("WARNING: data_quality_orig NOT FOUND")

# FIX 7
code = code.replace("def build_winning_insight(baseline, patterns, forecast, stage=None):", "def build_winning_insight(timeline, baseline, patterns, forecast, stage=None):")
code = code.replace("regular_insight = build_winning_insight(regular_baseline, regular_patterns, regular_forecast, user_regular.profile.self_reported_stage)", "regular_insight = build_winning_insight(user_regular, regular_baseline, regular_patterns, regular_forecast, user_regular.profile.self_reported_stage)")
code = code.replace("peri_insight = build_winning_insight(peri_baseline, peri_patterns, peri_forecast, user_peri.profile.self_reported_stage)", "peri_insight = build_winning_insight(user_peri, peri_baseline, peri_patterns, peri_forecast, user_peri.profile.self_reported_stage)")
code = code.replace("meno_insight = build_winning_insight(meno_baseline, meno_patterns, meno_forecast, user_meno.profile.self_reported_stage)", "meno_insight = build_winning_insight(user_meno, meno_baseline, meno_patterns, meno_forecast, user_meno.profile.self_reported_stage)")

insight_quality_orig = """    messages.append("DATA QUALITY")
    hist_len = baseline.baseline_cycle_count + baseline.recent_cycle_count
    cycle_pct = baseline.data_completeness_score.get('cycle_logging_pct', 0)
    messages.append(f"Cycle history       {'Good' if hist_len >= 6 else 'Moderate'}")"""
insight_quality_new = """    messages.append("DATA QUALITY")
    cycles = timeline_cycle_lengths(timeline)
    hist_len = len(cycles)
    cycle_pct = baseline.data_completeness_score.get('cycle_logging_pct', 0)
    messages.append(f"Cycle history       {'Good' if hist_len >= 6 else 'Moderate' if hist_len > 0 else 'Insufficient'}")"""
if insight_quality_orig in code:
    code = code.replace(insight_quality_orig, insight_quality_new)
else:
    print("WARNING: insight_quality_orig NOT FOUND")

# FIX 8
code = code.replace("80% Conformal Interval:", "80% Prediction Interval (calibrated on dev OOF):")
code = code.replace("90% Conformal Interval:", "90% Prediction Interval (calibrated on dev OOF):")

# FIX 9
code = re.sub(
    r'with open\(artifact_path, "wb"\) as f:\s*pickle\.dump\(artifact, f\)',
    'import joblib\n        joblib.dump(artifact, artifact_path)',
    code
)

code = re.sub(
    r'with open\(artifact_path, "rb"\) as f:\s*artifact = pickle\.load\(f\)',
    'import joblib\n    artifact = joblib.load(artifact_path)',
    code
)

with open('cycle_safe.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("cycle_safe.py updated.")
