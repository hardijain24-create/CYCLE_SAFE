"""CycleSafe Unified Forecast Module.

Exposes a single, shared next-cycle forecast function for API, Report, and Notebook.
"""

import os
import joblib
import numpy as np
from typing import List, Dict, Any, Optional, Union

from cyclesafe.config import DEFAULT_ARTIFACT_PATH, MIN_HISTORY_FOR_MODEL

# Fallback Mondrian conformal radii – used only when no artifact is loaded.
# Labelled "default, uncalibrated" in the output when these are in effect.
DEFAULT_CONFORMAL_RADII = {
    "low": {"radius80": 2.0, "radius90": 3.5},
    "medium": {"radius80": 3.5, "radius90": 5.5},
    "high": {"radius80": 5.5, "radius90": 8.5},
}

def is_safe_artifact_path(artifact_path: str, allowed_dir: str = "models") -> bool:
    """Verifies that artifact_path is strictly inside allowed_dir using realpath and commonpath."""
    try:
        real_allowed = os.path.realpath(allowed_dir)
        real_target = os.path.realpath(artifact_path)
        return os.path.commonpath([real_allowed, real_target]) == real_allowed
    except Exception:
        return False


def _history_features(cycle_lengths: List[float]) -> Dict[str, float]:
    """Build the same feature dict that cycle_safe.py training uses.

    Returns a dict keyed by feature name. Values are NaN when the
    history is too short to compute a rolling stat.
    """
    arr = np.array(cycle_lengths, dtype=float)
    n = len(arr)

    feat: Dict[str, float] = {}

    # Lag features
    feat["lag_1"] = arr[-1] if n >= 1 else np.nan
    feat["lag_2"] = arr[-2] if n >= 2 else np.nan
    feat["lag_3"] = arr[-3] if n >= 3 else np.nan

    # Rolling mean / median
    for k in [3, 5, 8, 12]:
        vals = arr[-k:] if n >= k else arr
        feat[f"mean_{k}"] = float(np.mean(vals))
        if k <= 5:
            feat[f"median_{k}"] = float(np.median(vals))

    # Rolling dispersion
    for k in [3, 5, 8, 12]:
        vals = arr[-k:] if n >= k else arr
        feat[f"std_{k}"] = float(np.std(vals)) if len(vals) > 1 else 0.0

    # Additional dispersion (window=5)
    w5 = arr[-5:] if n >= 5 else arr
    feat["mad_5"] = float(np.mean(np.abs(w5 - np.median(w5))))
    q1, q3 = np.percentile(w5, [25, 75])
    feat["iqr_5"] = float(q3 - q1)
    feat["range_5"] = float(np.ptp(w5))
    feat["cv_5"] = float(np.std(w5) / np.mean(w5)) if np.mean(w5) > 0 else 0.0

    # Personal summary stats
    feat["personal_mean"] = float(np.mean(arr))
    feat["personal_median"] = float(np.median(arr))
    feat["personal_std"] = float(np.std(arr)) if n > 1 else 0.0

    # Difference features
    feat["last_minus_personal_mean"] = arr[-1] - np.mean(arr)
    feat["last_minus_mean_5"] = arr[-1] - feat["mean_5"] if "mean_5" in feat else 0.0
    feat["mean_3_minus_mean_8"] = feat.get("mean_3", np.nan) - feat.get("mean_8", np.nan)
    feat["mean_5_minus_mean_12"] = feat.get("mean_5", np.nan) - feat.get("mean_12", np.nan)

    # Deltas
    feat["delta_1"] = float(arr[-1] - arr[-2]) if n >= 2 else 0.0
    feat["delta_2"] = float(arr[-2] - arr[-3]) if n >= 3 else 0.0

    # Trend (simple slope via polyfit)
    for k in [5, 8]:
        seg = arr[-k:] if n >= k else arr
        if len(seg) >= 2:
            feat[f"trend_{k}"] = float(np.polyfit(range(len(seg)), seg, 1)[0])
        else:
            feat[f"trend_{k}"] = 0.0

    # Exponentially-weighted moving average & std
    for sp in [35, 60]:
        alpha = 2.0 / (sp / np.mean(arr) + 1) if np.mean(arr) > 0 else 0.5
        ewma = arr[0]
        for v in arr[1:]:
            ewma = alpha * v + (1 - alpha) * ewma
        feat[f"ewma_{sp}"] = float(ewma)
    # ewstd_35 approximation
    feat["ewstd_35"] = float(np.std(arr[-5:])) if n >= 5 else float(np.std(arr))

    # Count-based
    feat["history_count"] = float(n)
    feat["long_cycle_fraction"] = float(np.mean(arr > 35))
    feat["short_cycle_fraction"] = float(np.mean(arr < 21))
    pm = np.mean(arr)
    feat["near_personal_baseline_fraction"] = float(np.mean(np.abs(arr - pm) < 2))

    return feat


def forecast_next_cycle(
    cycles: List[Union[float, Dict[str, Any]]], 
    age: Optional[int] = None, 
    is_perimenopause: bool = False, 
    artifact_path: str = DEFAULT_ARTIFACT_PATH
) -> Dict[str, Any]:
    """Single unified forecast function. Returns point estimate, prediction window, dynamic confidence, and model details."""
    
    if not is_safe_artifact_path(artifact_path):
        raise ValueError(f"Artifact path '{artifact_path}' is outside allowed directory.")

    # Extract numerical cycle lengths if list of dicts/objects passed
    cycle_lengths = []
    for c in cycles:
        if isinstance(c, (int, float)):
            cycle_lengths.append(float(c))
        elif isinstance(c, dict):
            if "cycle_length_days" in c:
                cycle_lengths.append(float(c["cycle_length_days"]))

    num_cycles = len(cycle_lengths)
    if num_cycles < MIN_HISTORY_FOR_MODEL:
        return {
            "forecast_available": False,
            "message": f"Fewer than {MIN_HISTORY_FOR_MODEL} completed cycles logged. Insufficient history for forecast.",
            "point_estimate_median_days": None,
            "forecast_window": None
        }

    median_val = float(np.median(cycle_lengths))
    std_val = float(np.std(cycle_lengths)) if num_cycles > 1 else 0.0
    cv_val = std_val / median_val if median_val > 0 else 0.0

    # Build full feature vector from history
    feat_dict = _history_features(cycle_lengths)

    # Safe artifact loading
    model_loaded = False
    model_name = "naive_median"
    point_estimate = median_val
    model_agreement_spread = 0.0
    radii = DEFAULT_CONFORMAL_RADII
    radii_calibrated = False
    cv_tertile_cutoffs = None
    all_predictions = []

    if os.path.exists(artifact_path):
        try:
            art = joblib.load(artifact_path)
            model_name = art.get("deployment_model_name", "naive_median")
            if "conformal_radii" in art and art["conformal_radii"]:
                radii = art["conformal_radii"]
                radii_calibrated = True
            if "cv_tertile_cutoffs" in art and art["cv_tertile_cutoffs"]:
                cv_tertile_cutoffs = art["cv_tertile_cutoffs"]

            # Build feature vector matching training features
            art_features = art.get("features") or art.get("feature_names")
            
            if "model" in art and hasattr(art["model"], "predict") and art_features:
                model_obj = art["model"]
                feat_vec = np.array([[feat_dict.get(f, np.nan) for f in art_features]])
                # Replace NaN with 0 for missing features
                feat_vec = np.nan_to_num(feat_vec, nan=0.0)
                try:
                    point_estimate = float(model_obj.predict(feat_vec)[0])
                    model_loaded = True
                except Exception:
                    point_estimate = median_val

            # Compute model agreement spread from all_models
            if "all_models" in art and art["all_models"] and art_features:
                feat_vec = np.array([[feat_dict.get(f, np.nan) for f in art_features]])
                feat_vec = np.nan_to_num(feat_vec, nan=0.0)
                for m_name, m_obj in art["all_models"].items():
                    if hasattr(m_obj, "predict"):
                        try:
                            pred = float(m_obj.predict(feat_vec)[0])
                            all_predictions.append(pred)
                        except Exception:
                            pass
                # Always include baselines
                all_predictions.append(median_val)
                all_predictions.append(float(np.mean(cycle_lengths)))
                if len(all_predictions) >= 2:
                    model_agreement_spread = float(np.std(all_predictions))
                    
        except Exception:
            point_estimate = median_val

    # Group-wise Mondrian conformal prediction logic using training cutoffs
    if cv_tertile_cutoffs:
        cut_low, cut_high = cv_tertile_cutoffs
    else:
        cut_low, cut_high = 0.08, 0.16

    if cv_val < cut_low:
        var_group = "low"
        r80 = radii.get("low", {}).get("radius80", 2.0)
        r90 = radii.get("low", {}).get("radius90", 3.5)
    elif cv_val < cut_high:
        var_group = "medium"
        r80 = radii.get("medium", {}).get("radius80", 3.5)
        r90 = radii.get("medium", {}).get("radius90", 5.5)
    else:
        var_group = "high"
        r80 = radii.get("high", {}).get("radius80", 5.5)
        r90 = radii.get("high", {}).get("radius90", 8.5)

    if radii_calibrated:
        uncertainty_label = "Calibrated Personal Baseline Window"
    else:
        uncertainty_label = "Personal Baseline Median Window (default, uncalibrated)"
        
    if (age and age >= 45) or is_perimenopause:
        uncertainty_label = "experimental, wider uncertainty (training data covers ages 21 to 43)"
        var_group = "high (perimenopause)"
        r80 = max(r80 * 1.3, 6.0)
        r90 = max(r90 * 1.3, 9.0)

    lower_80 = round(max(15.0, point_estimate - r80), 1)
    upper_80 = round(min(90.0, point_estimate + r80), 1)
    lower_90 = round(max(15.0, point_estimate - r90), 1)
    upper_90 = round(min(90.0, point_estimate + r90), 1)

    # Dynamic confidence components
    conf_hist = min(100, int(num_cycles / 8.0 * 100))
    conf_pat = max(0, min(100, int(100 - std_val * 10)))
    conf_mod = max(0, min(100, int(100 - model_agreement_spread * 20)))

    has_multiple_models = len(all_predictions) >= 3
    if has_multiple_models:
        avg_conf = (conf_hist + conf_pat + conf_mod) / 3.0
    else:
        avg_conf = (conf_hist + conf_pat) / 2.0
        conf_mod = None

    conf_label = "High" if avg_conf >= 75 else "Moderate" if avg_conf >= 50 else "Low"

    method_label = f"Personalised Baseline ({model_name})" if model_loaded else f"Personal median baseline (deployed model: {model_name})"

    return {
        "forecast_available": True,
        "message": "Forecast generated from longitudinal history.",
        "predicted_cycle_length_days": round(point_estimate, 1),
        "point_estimate_median_days": round(point_estimate, 1),
        "forecast_window": f"expected between day {lower_80:.0f} and day {upper_80:.0f}",
        "estimated_range_80_percent": {
            "lower_days": lower_80,
            "upper_days": upper_80
        },
        "estimated_range_90_percent": {
            "lower_days": lower_90,
            "upper_days": upper_90
        },
        "variability_group": var_group,
        "uncertainty_label": uncertainty_label,
        "method": method_label,
        "deployment_model": model_name,
        "confidence_components": {
            "history": conf_hist,
            "pattern": conf_pat,
            "model": conf_mod,
            "overall": conf_label
        }
    }
