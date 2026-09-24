import pytest

def test_item6_model_selection_and_core_features():
    from cyclesafe.lifestage import select_deployment_model
    from cyclesafe.config import CORE_FEATURES

    # 1. CORE_FEATURES must NOT contain data_completeness (it is always 0)
    assert "data_completeness" not in CORE_FEATURES, "data_completeness must be removed from CORE_FEATURES"

    # 2. select_deployment_model must rank baselines (naive_median, personal_mean, recent_mean_3) as simplest (1, 2, 3)
    results = [
        {"model": "ridge", "mae": 2.05},
        {"model": "naive_median", "mae": 2.06}, # within margin of 0.03 from 2.05!
        {"model": "random_forest", "mae": 2.10}
    ]

    winning_model = select_deployment_model(results, margin=0.03)
    # Since naive_median (2.06) is within 0.03 margin of best (ridge 2.05), and naive_median is simpler (complexity=1 vs ridge=4), naive_median MUST WIN!
    assert winning_model == "naive_median", f"Expected naive_median to win as simplest model within margin, got {winning_model}"
