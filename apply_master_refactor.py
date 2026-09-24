import sys
import os
import re

def refactor():
    with open('cycle_safe.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # 1. Ensure FEATURES uses only longitudinal core features
    code = code.replace("FEATURES = CORE_FEATURES.copy() + [f'ctx_{c}' for c in SAFE_CONTEXT_COLUMNS]", "FEATURES = CORE_FEATURES.copy()")
    code = code.replace("SAFE_CONTEXT_COLUMNS = ['meanmenseslength', 'meanbleedingintensity']", "SAFE_CONTEXT_COLUMNS = []")

    # 2. Update forecast_V4_user to call forecast_next_cycle directly without try/except fallback
    v4_old = '''def forecast_V4_user(timeline: UserTimeline, artifact_path=ARTIFACT_PATH):
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
    return result'''

    v4_new = '''def forecast_V4_user(timeline: UserTimeline, artifact_path=ARTIFACT_PATH):
    stage = getattr(timeline.profile, "self_reported_stage", LifeStage.UNKNOWN)
    cycles = timeline_cycle_lengths(timeline)

    result_dict = {
        "user_id": timeline.profile.user_id,
        "life_stage": stage.value if hasattr(stage, "value") else str(stage),
        "forecast_available": False,
        "forecast": None,
        "message": None,
        "model_agreement_details": {},
        "model_agreement_spread": None
    }

    if stage == LifeStage.MENOPAUSE:
        result_dict["message"] = "Menopause stage is recorded. CycleSafe does not issue a normal next-cycle forecast."
        return result_dict

    if len(cycles) < MIN_HISTORY_FOR_MODEL:
        result_dict["message"] = f"At least {MIN_HISTORY_FOR_MODEL} completed cycles are needed for the forecast."
        return result_dict

    if stage == LifeStage.PERIMENOPAUSE:
        result_dict["message"] = "The self-reported perimenopause context is retained."

    # Direct model forecast call without silent fallback (Prompt Directive 1 & 2)
    if "forecast_next_cycle_real" in globals():
        forecast = forecast_next_cycle_real(cycles, artifact_path=artifact_path)
    else:
        forecast = forecast_next_cycle(cycles, artifact_path=artifact_path)

    # Compute actual model agreement details dynamically if artifact available
    if os.path.exists(artifact_path):
        with open(artifact_path, "rb") as f:
            art = pickle.load(f)
        if "all_models" in art and art["all_models"]:
            feats = history_features(cycles)
            row = pd.DataFrame([feats])[art["features"]]
            m_preds = {}
            for m_name, m_obj in art["all_models"].items():
                m_preds[m_name] = round(float(m_obj.predict(row)[0]), 1)
            result_dict["model_agreement_details"] = m_preds
            vals = list(m_preds.values())
            result_dict["model_agreement_spread"] = round(max(vals) - min(vals), 1)

    result_dict["forecast_available"] = True
    result_dict["forecast"] = forecast
    return result_dict'''

    if v4_old in code:
        code = code.replace(v4_old, v4_new)

    # 3. Update adapter_to_forecast_result to compute confidence dynamically
    adapter_old = '''def adapter_to_forecast_result(adapter_result):
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
    )'''

    adapter_new = '''def adapter_to_forecast_result(adapter_result, timeline=None):
    if not adapter_result.get("forecast_available"):
        return ForecastResult(
            predicted_cycle_length_days=None, lower_80_days=None, upper_80_days=None,
            lower_90_days=None, upper_90_days=None, predicted_absolute_error_days=None,
            method="No forecast generated",
            confidence_history=0, confidence_pattern=0, confidence_model=0, confidence_overall="Low"
        )

    f = adapter_result["forecast"]
    r80 = f.get("estimated_range_80_percent", {})
    r90 = f.get("estimated_range_90_percent", {})

    cycles = timeline_cycle_lengths(timeline) if timeline else []
    hist_cnt = len(cycles)
    std3 = float(np.std(cycles[-3:], ddof=1)) if len(cycles) >= 3 else 0.0

    conf_hist = min(100, int(hist_cnt / 8.0 * 100)) if hist_cnt > 0 else 0
    conf_pat = max(0, min(100, int(100 - std3 * 10))) if hist_cnt >= 3 else 50
    
    spread = adapter_result.get("model_agreement_spread")
    if spread is not None:
        conf_mod = max(0, min(100, int(100 - spread * 20)))
    else:
        conf_mod = 70

    avg_conf = (conf_hist + conf_pat + conf_mod) / 3.0
    conf_overall = "High" if avg_conf >= 75 else "Moderate" if avg_conf >= 50 else "Low"

    return ForecastResult(
        predicted_cycle_length_days=f.get("predicted_cycle_length_days"),
        lower_80_days=r80.get("lower_days"),
        upper_80_days=r80.get("upper_days"),
        lower_90_days=r90.get("lower_days"),
        upper_90_days=r90.get("upper_days"),
        predicted_absolute_error_days=None,
        method=f.get("deployment_model", "ridge"),
        model_agreement_details=adapter_result.get("model_agreement_details", {}),
        model_agreement_spread=spread,
        confidence_history=conf_hist,
        confidence_pattern=conf_pat,
        confidence_model=conf_mod,
        confidence_overall=conf_overall
    )'''

    if adapter_old in code:
        code = code.replace(adapter_old, adapter_new)

    # 4. Update adapter_to_forecast_result invocations to pass timeline
    code = code.replace("regular_forecast = adapter_to_forecast_result(forecast_V4_user(user_regular))", "regular_forecast = adapter_to_forecast_result(forecast_V4_user(user_regular), user_regular)")
    code = code.replace("peri_forecast = adapter_to_forecast_result(forecast_V4_user(user_peri))", "peri_forecast = adapter_to_forecast_result(forecast_V4_user(user_peri), user_peri)")
    code = code.replace("meno_forecast = adapter_to_forecast_result(forecast_V4_user(user_meno))", "meno_forecast = adapter_to_forecast_result(forecast_V4_user(user_meno), user_meno)")

    # 5. Fix build_winning_doctor_report data quality labels for 0 cycles
    dq_old = '''    data_quality = {
        "history_length": len(cycle_lengths),
        "missing_values": "Low" if baseline.data_completeness_score.get('cycle_logging_pct', 0) > 80 else "High",
        "recent_consistency": "High" if not patterns.cycle_change_detected else "Moderate",
        "eligible_for_forecast": forecast.predicted_cycle_length_days is not None
    }'''

    dq_new = '''    if len(cycle_lengths) == 0:
        missing_values_label = "N/A (0 cycles logged)"
        recent_consistency_label = "N/A (No history)"
    else:
        missing_values_label = "Low" if baseline.data_completeness_score.get('cycle_logging_pct', 0) > 80 else "High"
        recent_consistency_label = "High" if not patterns.cycle_change_detected else "Moderate"

    data_quality = {
        "history_length": len(cycle_lengths),
        "missing_values": missing_values_label,
        "recent_consistency": recent_consistency_label,
        "eligible_for_forecast": forecast.predicted_cycle_length_days is not None
    }'''

    if dq_old in code:
        code = code.replace(dq_old, dq_new)

    # 6. Relabel old regressor F1 in Cell 11 / 22
    old_f1_str = '''{"metric": "Irregular Shift F1-Score", "value": round(f1_score, 3), "status": "Balanced Accuracy"}'''
    new_f1_str = '''{"metric": "Irregular Shift F1 (Old Regressor Thresholding)", "value": round(f1_score, 3), "status": "Deprecated (See Cell 12 Classifier)"}'''
    if old_f1_str in code:
        code = code.replace(old_f1_str, new_f1_str)

    # 7. Update PDF generator label for Conformal Interval
    code = code.replace("<b>80% Conformal Interval:</b>", "<b>80% Conformal Prediction Interval:</b>")

    with open('cycle_safe.py', 'w', encoding='utf-8') as f:
        f.write(code)

    print("Refactored cycle_safe.py successfully!")

if __name__ == '__main__':
    refactor()
