"""CycleSafe Unified Forecast Module.

Exposes a single, shared next-cycle forecast function for API, Report, and Notebook.
"""

import os
import joblib
import numpy as np
from typing import List, Dict, Any, Optional

from cyclesafe.config import DEFAULT_ARTIFACT_PATH, MIN_HISTORY_FOR_MODEL
from cyclesafe.lifestage import compute_lifestage_forecast_window

def forecast_next_cycle(cycles: List[float], age: Optional[int] = None, is_perimenopause: bool = False, artifact_path: str = DEFAULT_ARTIFACT_PATH) -> Dict[str, Any]:
    """Single unified forecast function. Returns forecast window, confidence components, and model details."""
    num_cycles = len(cycles)
    if num_cycles < MIN_HISTORY_FOR_MODEL:
        return {
            "forecast_available": False,
            "message": f"Fewer than {MIN_HISTORY_FOR_MODEL} completed cycles logged. Insufficient history for forecast.",
            "forecast": None
        }

    median_val = float(np.median(cycles))
    std_val = float(np.std(cycles)) if num_cycles > 1 else 0.0
    cv_val = std_val / median_val if median_val > 0 else 0.0

    # Load artifact if available safely
    model_loaded = False
    model_name = "personal_median"
    if os.path.exists(artifact_path) and artifact_path.startswith("models"):
        try:
            art = joblib.load(artifact_path)
            model_name = art.get("deployment_model_name", "ridge")
            model_loaded = True
        except Exception:
            pass

    window_info = compute_lifestage_forecast_window(median_val, cv_val, age=age, is_perimenopause=is_perimenopause)

    # Dynamic confidence components
    conf_hist = min(100, int(num_cycles / 8.0 * 100))
    conf_pat = max(0, min(100, int(100 - std_val * 10))) if num_cycles >= 3 else 50
    conf_mod = 85 if model_loaded else 60

    avg_conf = (conf_hist + conf_pat + conf_mod) / 3.0
    conf_label = "High" if avg_conf >= 75 else "Moderate" if avg_conf >= 50 else "Low"

    method_label = f"Personalised Baseline ({model_name})" if model_loaded else "Personal Baseline Median (no trained model loaded)"

    return {
        "forecast_available": True,
        "message": "Forecast generated from longitudinal history.",
        "predicted_cycle_length_days": window_info["point_estimate"],
        "forecast_window": window_info["window_text"],
        "estimated_range_80_percent": {
            "lower_days": window_info["lower_80"],
            "upper_days": window_info["upper_80"]
        },
        "estimated_range_90_percent": {
            "lower_days": window_info["lower_90"],
            "upper_days": window_info["upper_90"]
        },
        "variability_group": window_info["variability_group"],
        "uncertainty_label": window_info["uncertainty_label"],
        "method": method_label,
        "deployment_model": model_name,
        "confidence_components": {
            "history": conf_hist,
            "pattern": conf_pat,
            "model": conf_mod,
            "overall": conf_label
        }
    }
