"""CycleSafe Life-stage & Uncertainty Calibration Module.

Shared logic for perimenopause and age >= 45 uncertainty widening.
"""

from typing import Dict, Any, Optional

def compute_lifestage_forecast_window(median_val: float, cv_val: float, age: Optional[int] = None, is_perimenopause: bool = False) -> Dict[str, Any]:
    """Computes forecast window and uncertainty label for user based on variability and life-stage context."""
    
    is_perimeno_user = (age is not None and age >= 45) or is_perimenopause

    if is_perimeno_user:
        label = "experimental, wider uncertainty (training data covers ages 21 to 43)"
        var_group = "high (perimenopause)"
        radius80 = 6.0
        radius90 = 9.0
    else:
        if cv_val < 0.08:
            var_group = "low"
            radius80 = 2.5
            radius90 = 4.0
        elif cv_val < 0.16:
            var_group = "medium"
            radius80 = 3.5
            radius90 = 5.5
        else:
            var_group = "high"
            radius80 = 5.0
            radius90 = 8.0
        label = f"Personal Baseline Median Window ({var_group} variability)"

    lower_80 = round(max(15.0, median_val - radius80), 1)
    upper_80 = round(min(90.0, median_val + radius80), 1)
    lower_90 = round(max(15.0, median_val - radius90), 1)
    upper_90 = round(min(90.0, median_val + radius90), 1)

    return {
        "point_estimate": round(median_val, 1),
        "lower_80": lower_80,
        "upper_80": upper_80,
        "lower_90": lower_90,
        "upper_90": upper_90,
        "window_text": f"expected between day {lower_80:.0f} and day {upper_80:.0f}",
        "variability_group": var_group,
        "uncertainty_label": label,
        "is_experimental": is_perimeno_user
    }
