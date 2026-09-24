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

def select_deployment_model(results, margin: float = 0.03) -> str:
    """Multi-criteria model selection on development OOF.
    
    If candidate OOF MAE is within `margin` (0.03d) of top model, prefers simpler/stabler models to prevent metric chasing.
    """
    complexity_order = {
        "naive_median": 1,
        "personal_mean": 2,
        "recent_mean_3": 3,
        "ridge": 4,
        "elastic_net": 5,
        "random_forest": 6,
        "extra_trees": 7,
        "hist_gradient_boosting": 8
    }
    if isinstance(results, list):
        sorted_res = sorted(results, key=lambda x: x["mae"])
        best_mae = sorted_res[0]["mae"]
        equivalent = [x for x in sorted_res if x["mae"] <= best_mae + margin]
        for item in equivalent:
            item["complexity"] = complexity_order.get(item["model"], 10)
        equivalent.sort(key=lambda x: (x["complexity"], x["mae"]))
        return str(equivalent[0]["model"])
    else:
        sorted_res = results.sort_values("mae").reset_index(drop=True)
        best_mae = sorted_res.iloc[0]["mae"]
        equivalent = sorted_res[sorted_res["mae"] <= best_mae + margin].copy()
        equivalent["complexity"] = equivalent["model"].map(lambda m: complexity_order.get(m, 10))
        selected = equivalent.sort_values(["complexity", "mae"]).iloc[0]
        return str(selected["model"])
