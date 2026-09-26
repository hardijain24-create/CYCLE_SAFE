"""CycleSafe Configuration Constants."""

import os

MIN_CYCLE_LENGTH = 15.0
MAX_CYCLE_LENGTH = 90.0
MIN_HISTORY_FOR_MODEL = 3

DEFAULT_MODEL_DIR = os.environ.get("CYCLESAFE_MODEL_DIR", "models")
DEFAULT_ARTIFACT_PATH = os.path.join(DEFAULT_MODEL_DIR, "cyclesafe_model_artifact.pkl")

SAFE_CONTEXT_COLUMNS = []

CORE_FEATURES = [
    "hist_count", "hist_mean", "hist_std", "hist_median", "hist_min", "hist_max", "hist_range", "hist_cv",
    "recent_mean_3", "recent_std_3", "recent_median_3", "recent_cv_3",
    "recent_mean_6", "recent_std_6", "recent_median_6", "recent_cv_6",
    "lag_1", "lag_2", "lag_3", "lag_4", "lag_5", "lag_6",
    "diff_1_2", "diff_2_3", "diff_3_4", "diff_lag1_hist_mean", "diff_lag1_recent3_mean",
    "ratio_lag1_hist_mean", "ratio_recent3_hist_mean", "trend_3", "trend_6",
    "cv_ratio_3_hist", "cv_ratio_6_hist", "ema_3", "ema_6", "baseline_length", "recent_length_change"
]

FEATURES = CORE_FEATURES.copy()
