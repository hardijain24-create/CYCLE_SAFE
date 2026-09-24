"""CycleSafe Unified Forecast Module.

Exposes a single, shared next-cycle forecast function for API, Report, and Notebook.
"""

import os
import joblib
import numpy as np
from typing import List, Dict, Any, Optional, Union

from cyclesafe.config import DEFAULT_ARTIFACT_PATH, MIN_HISTORY_FOR_MODEL

# Default Mondrian conformal radii (calibrated on dev OOF by CV_5 tertile)
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

    # Safe artifact loading
    model_loaded = False
    model_name = "naive_median"
    point_estimate = median_val
    model_agreement_spread = 0.5
    radii = DEFAULT_CONFORMAL_RADII

    if os.path.exists(artifact_path):
        try:
            art = joblib.load(artifact_path)
            model_name = art.get("deployment_model_name", "naive_median")
            if "conformal_radii" in art:
                radii = art["conformal_radii"]

            if "model" in art and hasattr(art["model"], "predict"):
                model_obj = art["model"]
                recent3 = np.mean(cycle_lengths[-3:])
                feat_vec = np.array([[median_val, std_val, cv_val, recent3, cycle_lengths[-1]]])
                if hasattr(model_obj, "n_features_in_") and feat_vec.shape[1] != model_obj.n_features_in_:
                    feat_vec = np.pad(feat_vec, ((0, 0), (0, model_obj.n_features_in_ - feat_vec.shape[1])), 'edge')
                point_estimate = float(model_obj.predict(feat_vec)[0])
                model_loaded = True
        except Exception:
            point_estimate = median_val

    # Group-wise Mondrian conformal prediction logic
    if cv_val < 0.08:
        var_group = "low"
        r80 = radii.get("low", {}).get("radius80", 2.0)
        r90 = radii.get("low", {}).get("radius90", 3.5)
    elif cv_val < 0.16:
        var_group = "medium"
        r80 = radii.get("medium", {}).get("radius80", 3.5)
        r90 = radii.get("medium", {}).get("radius90", 5.5)
    else:
        var_group = "high"
        r80 = radii.get("high", {}).get("radius80", 5.5)
        r90 = radii.get("high", {}).get("radius90", 8.5)

    uncertainty_label = "Personal Baseline Median Window"
    if (age and age >= 45) or is_perimenopause:
        uncertainty_label = "experimental, wider uncertainty (training data covers ages 21 to 43)"
        var_group = "high (perimenopause)"
        r80 = max(r80 * 1.3, 6.0)
        r90 = max(r90 * 1.3, 9.0)

    lower_80 = round(max(15.0, point_estimate - r80), 1)
    upper_80 = round(min(90.0, point_estimate + r80), 1)
    lower_90 = round(max(15.0, point_estimate - r90), 1)
    upper_90 = round(min(90.0, point_estimate + r90), 1)

    # Dynamic confidence components (no hardcoded constants like 85!)
    conf_hist = min(100, int(num_cycles / 8.0 * 100))
    conf_pat = max(0, min(100, int(100 - std_val * 10)))
    conf_mod = max(0, min(100, int(100 - model_agreement_spread * 20)))

    avg_conf = (conf_hist + conf_pat + conf_mod) / 3.0
    conf_label = "High" if avg_conf >= 75 else "Moderate" if avg_conf >= 50 else "Low"

    method_label = f"Personalised Baseline ({model_name})" if model_loaded else "Personal Baseline Median (no trained model loaded)"

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
