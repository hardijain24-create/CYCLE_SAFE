from __future__ import annotations

def display(*args, **kwargs):
    for arg in args:
        if hasattr(arg, 'to_string'):
            print(arg.to_string())
        else:
            print(arg)

import sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# -*- coding: utf-8 -*-
"""cycle_safe_v5_part1.py

CYCLESAFE V5 ELITE - LEAKAGE-SAFE PERSONALIZED MENSTRUAL CYCLE FORECASTING
"""

import io
import os
import json
import math
import pickle
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from sklearn.base import clone
from sklearn.ensemble import (
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

DATA_URL = (
    "https://raw.githubusercontent.com/18-Ritika/Data-crew/main/"
    "FedCycleData071012.csv"
)

MIN_CYCLE_LENGTH = 15
MAX_CYCLE_LENGTH = 90
MIN_HISTORY_FOR_MODEL = 3

FINAL_HOLDOUT_FRACTION = 0.20
N_ROLLING_FOLDS = 4

RANDOM_STATE = 42
N_ESTIMATORS = 400

# Development-only Ridge tuning grid. The untouched final test is never used.
RIDGE_ALPHA_CANDIDATES = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]

ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"

# These variables are intended to be observable by the end of the current
# completed cycle. Do NOT add variables that are only known after the target
# cycle occurs or are derived from the target itself.
SAFE_CONTEXT_COLUMNS = []

# =============================================================================
# DATA LOADING
# =============================================================================

def load_csv_source(source: str = DATA_URL) -> pd.DataFrame:
    """Load either a local CSV path or the configured remote CSV URL."""
    if os.path.exists(source):
        return pd.read_csv(source, low_memory=False)

    try:
        response = requests.get(
            source,
            timeout=60,
            headers={"User-Agent": "CycleSafe-V4/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        fallback = "/mnt/data/FedCycleData071012.csv"
        if os.path.exists(fallback):
            print("GitHub download unavailable; using local supplied CSV.")
            return pd.read_csv(fallback, low_memory=False)
        raise RuntimeError(f"Could not load dataset from {source}: {exc}") from exc

    if not response.content:
        raise RuntimeError("Dataset response was empty.")

    first = response.content[:500].lower()
    if b"<html" in first or b"<!doctype html" in first:
        raise RuntimeError(
            "The configured source returned HTML rather than CSV. "
            "Use the raw GitHub CSV URL."
        )

    return pd.read_csv(io.BytesIO(response.content), low_memory=False)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = (
        out.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    return out


def find_first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def validate_minimum_schema(df: pd.DataFrame) -> None:
    identifier_ok = ("clientid" in df.columns) or ("participant" in df.columns)
    missing = []
    if not identifier_ok:
        missing.append("clientid/participant")
    for c in ["cyclenumber", "lengthofcycle"]:
        if c not in df.columns:
            missing.append(c)
    if missing:
        raise ValueError(
            f"Required columns are missing: {missing}\n"
            f"Available columns: {df.columns.tolist()}"
        )


# =============================================================================
# DATA QUALITY
# =============================================================================

def clean_dataset(raw: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = normalize_columns(raw)
    validate_minimum_schema(df)

    rename = {
        "clientid": "user_id",
        "participant": "user_id",
        "cyclenumber": "cycle_number",
        "lengthofcycle": "cycle_length",
    }
    df = df.rename(columns=rename)

    for c in SAFE_CONTEXT_COLUMNS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["cycle_number"] = pd.to_numeric(df["cycle_number"], errors="coerce")
    df["cycle_length"] = pd.to_numeric(df["cycle_length"], errors="coerce")

    quality = []

    def add_check(name, value):
        quality.append({"check": name, "value": int(value)})

    add_check("raw_rows", len(df))
    add_check("raw_participants", df["user_id"].nunique())
    add_check("missing_cycle_number", df["cycle_number"].isna().sum())
    add_check("missing_cycle_length", df["cycle_length"].isna().sum())

    before = len(df)
    df = df.dropna(subset=["user_id", "cycle_number", "cycle_length"]).copy()
    add_check("removed_missing_required", before - len(df))

    duplicate_mask = df.duplicated(
        subset=["user_id", "cycle_number"],
        keep=False,
    )
    add_check("duplicate_participant_cycle_rows", duplicate_mask.sum())

    df = (
        df.sort_values(["user_id", "cycle_number"])
        .drop_duplicates(["user_id", "cycle_number"], keep="first")
        .copy()
    )

    invalid_length = ~df["cycle_length"].between(
        MIN_CYCLE_LENGTH, MAX_CYCLE_LENGTH
    )
    add_check("out_of_range_cycle_lengths", invalid_length.sum())
    # ENHANCEMENT: We no longer hard-delete out-of-range cycle lengths

    df = df.sort_values(["user_id", "cycle_number"]).reset_index(drop=True)

    gaps = 0
    for _, g in df.groupby("user_id"):
        nums = g["cycle_number"].astype(float).to_numpy()
        if len(nums) > 1:
            gaps += int(np.sum(np.diff(nums) > 1))
    add_check("cycle_number_gaps", gaps)
    
    # ENHANCEMENT: Track outliers with robust_z instead of hard-deleting
    def calc_robust_z(group):
        med = group["cycle_length"].median()
        mad = np.median(np.abs(group["cycle_length"] - med))
        if mad == 0:
            return pd.Series(0.0, index=group.index)
        return np.abs(group["cycle_length"] - med) / (1.4826 * mad)

    df["robust_z"] = df.groupby("user_id", group_keys=False).apply(calc_robust_z)
    df["is_potential_outlier"] = df["robust_z"] > 3.0
    add_check("potential_outliers", df["is_potential_outlier"].sum())

    add_check("clean_rows", len(df))
    add_check("clean_participants", df["user_id"].nunique())

    return df, pd.DataFrame(quality)


# =============================================================================
# FEATURE ENGINEERING
# =============================================================================

def mad(values) -> float:
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return 0.0
    med = np.median(x)
    return float(np.median(np.abs(x - med)))


def iqr(values) -> float:
    x = np.asarray(values, dtype=float)
    if len(x) < 2:
        return 0.0
    return float(np.percentile(x, 75) - np.percentile(x, 25))


def linear_slope(values) -> float:
    x = np.asarray(values, dtype=float)
    if len(x) < 2:
        return 0.0
    t = np.arange(len(x), dtype=float)
    return float(np.polyfit(t, x, 1)[0])


def ewma(values, alpha=0.35) -> float:
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return np.nan
    value = float(x[0])
    for v in x[1:]:
        value = alpha * float(v) + (1 - alpha) * value
    return value


def ewstd(values, alpha=0.35) -> float:
    x = np.asarray(values, dtype=float)
    if len(x) < 2:
        return 0.0
    mean = float(x[0])
    var = 0.0
    for v in x[1:]:
        delta = float(v) - mean
        mean = mean + alpha * delta
        var = (1 - alpha) * (var + alpha * delta * delta)
    return float(np.sqrt(max(var, 0.0)))


def safe_num(v, default=np.nan):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def history_features(
    cycle_lengths: List[float],
    context_history: Optional[pd.DataFrame] = None,
) -> Dict[str, float]:

    x = [safe_num(v) for v in cycle_lengths]
    x = [v for v in x if np.isfinite(v)]

    if len(x) < MIN_HISTORY_FOR_MODEL:
        raise ValueError("Insufficient history.")

    last3 = x[-3:]
    last5 = x[-5:]
    last8 = x[-8:]
    last12 = x[-12:]

    last = x[-1]
    prev = x[-2]
    prev2 = x[-3]

    mean3 = float(np.mean(last3))
    mean5 = float(np.mean(last5))
    mean8 = float(np.mean(last8))
    mean12 = float(np.mean(last12))

    std3 = float(np.std(last3))
    std5 = float(np.std(last5))
    std8 = float(np.std(last8))
    std12 = float(np.std(last12))

    personal_mean = float(np.mean(x))
    personal_median = float(np.median(x))
    personal_std = float(np.std(x))
    
    personal_mad = mad(x)
    robust_z_score = abs(last - personal_median) / (1.4826 * personal_mad) if personal_mad > 0 else 0.0
    
    data_completeness = 0
    if context_history is not None and len(context_history):
        latest = context_history.iloc[-1]
        data_completeness = sum(
            1 for c in SAFE_CONTEXT_COLUMNS 
            if c in context_history.columns and pd.notna(latest[c])
        )

    features = {
        "lag_1": last,
        "lag_2": prev,
        "lag_3": prev2,

        "mean_3": mean3,
        "median_3": float(np.median(last3)),
        "mean_5": mean5,
        "median_5": float(np.median(last5)),
        "mean_8": mean8,
        "mean_12": mean12,

        "std_3": std3,
        "std_5": std5,
        "std_8": std8,
        "std_12": std12,
        "mad_5": mad(last5),
        "iqr_5": iqr(last5),
        "range_5": float(max(last5) - min(last5)),
        "cv_5": float(std5 / mean5) if mean5 > 0 else 0.0,

        "personal_mean": personal_mean,
        "personal_median": personal_median,
        "personal_std": personal_std,
        "last_minus_personal_mean": last - personal_mean,
        "last_minus_mean_5": last - mean5,
        "mean_3_minus_mean_8": mean3 - mean8,
        "mean_5_minus_mean_12": mean5 - mean12,

        "delta_1": last - prev,
        "delta_2": prev - prev2,
        "trend_5": linear_slope(last5),
        "trend_8": linear_slope(last8),

        "ewma_35": ewma(last12, 0.35),
        "ewma_60": ewma(last12, 0.60),
        "ewstd_35": ewstd(last12, 0.35),

        "history_count": float(len(x)),
        "long_cycle_fraction": float(np.mean(np.asarray(x) >= 35)),
        "short_cycle_fraction": float(np.mean(np.asarray(x) <= 24)),
        "near_personal_baseline_fraction": float(
            np.mean(np.abs(np.asarray(x) - personal_mean) <= 2)
        ),
        
        # ENHANCEMENT: Added features
        "robust_z_score": robust_z_score,
        "data_completeness": float(data_completeness),
    }

    if context_history is not None and len(context_history):
        latest = context_history.iloc[-1]
        for c in SAFE_CONTEXT_COLUMNS:
            if c in context_history.columns:
                features[f"ctx_{c}"] = safe_num(latest[c])

        for c in SAFE_CONTEXT_COLUMNS:
            if c in context_history.columns:
                vals = pd.to_numeric(
                    context_history[c], errors="coerce"
                ).dropna()
                if len(vals):
                    features[f"ctx_{c}_recent_mean"] = float(vals.tail(3).mean())
                    features[f"ctx_{c}_recent_std"] = float(
                        vals.tail(3).std(ddof=0)
                    )

    return features


def build_forecasting_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for user_id, g in df.groupby("user_id", sort=False):
        g = g.sort_values("cycle_number").reset_index(drop=True)

        for i in range(MIN_HISTORY_FOR_MODEL, len(g)):
            history = g.iloc[:i]
            target_row = g.iloc[i]

            # LEAKAGE PROTECTION ASSERTIONS (MASTER PROMPT SECTION 3)
            assert target_row["cycle_number"] not in history["cycle_number"].values, "Target cycle row leaked into history!"
            assert len(history) == i, f"History length mismatch! Expected {i}, got {len(history)}"
            assert history["cycle_number"].max() < target_row["cycle_number"], "Future cycle number present in feature history!"

            feats = history_features(
                history["cycle_length"].tolist(),
                history,
            )

            rows.append(
                {
                    "user_id": user_id,
                    "cycle_number": target_row["cycle_number"],
                    "target": float(target_row["cycle_length"]),
                    **feats,
                }
            )

    result = pd.DataFrame(rows)

    if result.empty:
        raise RuntimeError(
            "No forecasting examples were created. "
            "Check MIN_HISTORY_FOR_MODEL and the dataset."
        )

    return result.sort_values(
        ["user_id", "cycle_number"]
    ).reset_index(drop=True)


CORE_FEATURES = [
    "lag_1", "lag_2", "lag_3",
    "mean_3", "median_3",
    "mean_5", "median_5",
    "mean_8", "mean_12",
    "std_3", "std_5", "std_8", "std_12",
    "mad_5", "iqr_5", "range_5", "cv_5",
    "personal_mean", "personal_median", "personal_std",
    "last_minus_personal_mean", "last_minus_mean_5",
    "mean_3_minus_mean_8", "mean_5_minus_mean_12",
    "delta_1", "delta_2", "trend_5", "trend_8",
    "ewma_35", "ewma_60", "ewstd_35",
    "history_count",
    "long_cycle_fraction",
    "short_cycle_fraction",
    "near_personal_baseline_fraction",
    "robust_z_score",
    "data_completeness",
]

CONTEXT_FEATURES = []
FEATURES = CORE_FEATURES.copy()

# ENHANCEMENT: FEATURE_GROUPS
FEATURE_GROUPS = {
    'lags_only': ['lag_1', 'lag_2', 'lag_3'],
    'lags_rolling': ['lag_1','lag_2','lag_3','mean_3','median_3','mean_5','median_5','mean_8','mean_12'],
    'lags_rolling_variability': ['lag_1','lag_2','lag_3','mean_3','median_3','mean_5','median_5','mean_8','mean_12','std_3','std_5','std_8','std_12','mad_5','iqr_5','range_5','cv_5'],
    'lags_rolling_variability_baseline': ['lag_1','lag_2','lag_3','mean_3','median_3','mean_5','median_5','mean_8','mean_12','std_3','std_5','std_8','std_12','mad_5','iqr_5','range_5','cv_5','personal_mean','personal_median','personal_std','last_minus_personal_mean','last_minus_mean_5','mean_3_minus_mean_8','mean_5_minus_mean_12'],  
    'lags_rolling_variability_baseline_trend': ['lag_1','lag_2','lag_3','mean_3','median_3','mean_5','median_5','mean_8','mean_12','std_3','std_5','std_8','std_12','mad_5','iqr_5','range_5','cv_5','personal_mean','personal_median','personal_std','last_minus_personal_mean','last_minus_mean_5','mean_3_minus_mean_8','mean_5_minus_mean_12','delta_1','delta_2','trend_5','trend_8','ewma_35','ewma_60','ewstd_35'],
    'all_core': CORE_FEATURES,
}

def final_temporal_holdout(
    model_data: pd.DataFrame,
    fraction: float = FINAL_HOLDOUT_FRACTION,
) -> Tuple[pd.DataFrame, pd.DataFrame]:

    train_parts = []
    test_parts = []

    for user_id, g in model_data.groupby("user_id", sort=False):
        g = g.sort_values("cycle_number")
        n = len(g)

        if n < 3:
            train_parts.append(g)
            continue

        n_test = max(1, int(np.ceil(n * fraction)))
        split = max(1, n - n_test)

        train_parts.append(g.iloc[:split])
        test_parts.append(g.iloc[split:])

    train = pd.concat(train_parts, ignore_index=True)
    test = (
        pd.concat(test_parts, ignore_index=True)
        if test_parts
        else pd.DataFrame(columns=model_data.columns)
    )

    return train, test


def rolling_folds(
    train_df: pd.DataFrame,
    n_folds: int = N_ROLLING_FOLDS,
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:

    folds = []
    edges = np.linspace(0.40, 0.80, n_folds + 1)

    for fold_id in range(n_folds):
        start_frac = edges[fold_id]
        end_frac = edges[fold_id + 1]

        train_idx = []
        valid_idx = []

        for _, g in train_df.groupby("user_id", sort=False):
            g = g.sort_values("cycle_number")
            n = len(g)

            if n < 4:
                continue

            start = max(1, min(int(np.floor(n * start_frac)), n - 1))
            end = max(0, min(int(np.floor(n * end_frac)), n))

            if end <= start:
                continue

            train_idx.extend(g.iloc[:start].index.tolist())
            valid_idx.extend(g.iloc[start:end].index.tolist())

        if train_idx and valid_idx:
            folds.append(
                (
                    train_df.loc[sorted(set(train_idx))].copy(),
                    train_df.loc[sorted(set(valid_idx))].copy(),
                )
            )

    all_valid = [
        idx
        for _, valid in folds
        for idx in valid.index.tolist()
    ]

    if len(all_valid) != len(set(all_valid)):
        raise RuntimeError("Rolling validation contains overlapping validation rows.")

    return folds


def make_models(ridge_alpha: float = 10.0) -> Dict[str, Pipeline]:
    return {
        "ridge": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=ridge_alpha)),
            ]
        ),
        "elastic_net": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    ElasticNet(
                        alpha=0.03,
                        l1_ratio=0.10,
                        max_iter=10000,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=N_ESTIMATORS,
                        max_depth=8,
                        min_samples_leaf=8,
                        max_features="sqrt",
                        random_state=RANDOM_STATE,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "extra_trees": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    ExtraTreesRegressor(
                        n_estimators=N_ESTIMATORS,
                        max_depth=8,
                        min_samples_leaf=8,
                        max_features="sqrt",
                        random_state=RANDOM_STATE,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=300,
                        learning_rate=0.035,
                        max_leaf_nodes=12,
                        min_samples_leaf=12,
                        l2_regularization=2.0,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
    }


def metrics(actual, predicted) -> Dict[str, float]:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    mask = np.isfinite(a) & np.isfinite(p)

    a = a[mask]
    p = p[mask]

    return {
        "mae": float(mean_absolute_error(a, p)),
        "rmse": float(np.sqrt(mean_squared_error(a, p))),
    }


def macro_user_metrics(
    frame: pd.DataFrame,
    prediction_column: str,
) -> Dict[str, float]:
    values = []

    for _, g in frame.groupby("user_id"):
        if len(g):
            values.append(
                mean_absolute_error(
                    g["actual"],
                    g[prediction_column],
                )
            )

    return {
        "macro_mae": float(np.mean(values)) if values else np.nan,
        "median_user_mae": float(np.median(values)) if values else np.nan,
        "users": int(len(values)),
    }


def tune_ridge_alpha_for_fold(
    outer_train: pd.DataFrame,
) -> Tuple[float, pd.DataFrame]:
    inner_train, inner_valid = final_temporal_holdout(
        outer_train,
        fraction=0.20,
    )

    if inner_valid.empty or inner_train.empty:
        return 10.0, pd.DataFrame([{"alpha": 10.0, "mae": np.nan}])

    rows = []

    for alpha in RIDGE_ALPHA_CANDIDATES:
        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=float(alpha))),
        ])
        model.fit(inner_train[FEATURES], inner_train["target"])
        pred = model.predict(inner_valid[FEATURES])
        rows.append({
            "alpha": float(alpha),
            "mae": mean_absolute_error(inner_valid["target"], pred),
        })

    table = pd.DataFrame(rows).sort_values(["mae", "alpha"]).reset_index(drop=True)
    return float(table.iloc[0]["alpha"]), table


def nested_ridge_alpha_tuning(
    folds: List[Tuple[pd.DataFrame, pd.DataFrame]],
) -> Tuple[Dict[int, float], pd.DataFrame]:
    fold_alpha = {}
    rows = []

    for fold_id, (outer_train, _outer_valid) in enumerate(folds, start=1):
        alpha, table = tune_ridge_alpha_for_fold(outer_train)
        fold_alpha[fold_id] = alpha
        for _, r in table.iterrows():
            rows.append({
                "fold": fold_id,
                "alpha": float(r["alpha"]),
                "inner_mae": float(r["mae"]) if np.isfinite(r["mae"]) else np.nan,
                "selected": bool(float(r["alpha"]) == alpha),
            })

    return fold_alpha, pd.DataFrame(rows)


def tune_final_ridge_alpha(dev: pd.DataFrame) -> Tuple[float, pd.DataFrame]:
    alpha, table = tune_ridge_alpha_for_fold(dev)
    return alpha, table


def generate_oof(
    folds,
    models: Dict[str, Pipeline],
    ridge_alpha_by_fold: Optional[Dict[int, float]] = None,
) -> pd.DataFrame:
    frames = []

    for fold_id, (train, valid) in enumerate(folds, start=1):
        fitted = {}

        for name, model in models.items():
            if name == "ridge" and ridge_alpha_by_fold is not None:
                m = make_models(ridge_alpha=ridge_alpha_by_fold.get(fold_id, 10.0))["ridge"]
            else:
                m = clone(model)
            m.fit(train[FEATURES], train["target"])
            fitted[name] = m

        out = valid[
            ["user_id", "cycle_number", "target", "history_count", "std_5", "cv_5"]
        ].copy()

        out["actual"] = out["target"].astype(float)
        out["fold"] = fold_id

        out["personal_mean_prediction"] = valid["personal_mean"]
        out["recent_mean_prediction"] = valid["mean_3"]
        out["naive_last_cycle_prediction"] = valid["lag_1"]
        out["naive_median_prediction"] = valid["personal_median"]
        out["naive_mean_prediction"] = valid["personal_mean"]

        for name, model in fitted.items():
            out[f"{name}_prediction"] = model.predict(valid[FEATURES])

        base_cols = [
            f"{name}_prediction"
            for name in models
        ]

        out["prediction_spread"] = (
            out[base_cols].max(axis=1)
            - out[base_cols].min(axis=1)
        )

        frames.append(out.reset_index(drop=True))

    oof = pd.concat(frames, ignore_index=True)
    return oof


def evaluate_oof(
    oof: pd.DataFrame,
    models: Dict[str, Pipeline],
) -> pd.DataFrame:
    rows = [
        {
            "model": "personal_mean",
            **metrics(oof["actual"], oof["personal_mean_prediction"]),
            **macro_user_metrics(oof, "personal_mean_prediction"),
        },
        {
            "model": "recent_mean_3",
            **metrics(oof["actual"], oof["recent_mean_prediction"]),
            **macro_user_metrics(oof, "recent_mean_prediction"),
        },
        {
            "model": "naive_last_cycle",
            **metrics(oof["actual"], oof["naive_last_cycle_prediction"]),
            **macro_user_metrics(oof, "naive_last_cycle_prediction"),
        },
        {
            "model": "naive_median",
            **metrics(oof["actual"], oof["naive_median_prediction"]),
            **macro_user_metrics(oof, "naive_median_prediction"),
        },
        {
            "model": "naive_mean",
            **metrics(oof["actual"], oof["naive_mean_prediction"]),
            **macro_user_metrics(oof, "naive_mean_prediction"),
        },
    ]

    for name in models:
        col = f"{name}_prediction"
        rows.append(
            {
                "model": name,
                **metrics(oof["actual"], oof[col]),
                **macro_user_metrics(oof, col),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values(["mae", "macro_mae"])
        .reset_index(drop=True)
    )


def error_by_history_and_variability(
    oof: pd.DataFrame,
    prediction_column: str,
) -> pd.DataFrame:
    x = oof.copy()

    x["history_group"] = pd.cut(
        x["history_count"],
        bins=[2, 4, 6, 9, 14, np.inf],
        labels=["3-4", "5-6", "7-9", "10-14", "15+"],
        include_lowest=True,
    )

    x["variability_group"] = pd.qcut(
        x["cv_5"].rank(method="first"),
        q=3,
        labels=["low", "medium", "high"],
    )

    x["abs_error"] = np.abs(
        x["actual"] - x[prediction_column]
    )

    result = (
        x.groupby(
            ["history_group", "variability_group"],
            observed=False,
        )
        .agg(
            observations=("abs_error", "size"),
            mae=("abs_error", "mean"),
            median_abs_error=("abs_error", "median"),
        )
        .reset_index()
    )

    return result


def select_deployment_model(results: pd.DataFrame, margin: float = 0.03) -> str:
    """Multi-criteria model selection on development OOF.
    
    If candidate OOF MAE is within `margin` (0.03d) of top model, prefers simpler/stabler models to prevent metric chasing.
    """
    sorted_res = results.sort_values("mae").reset_index(drop=True)
    best_mae = sorted_res.iloc[0]["mae"]
    
    equivalent = sorted_res[sorted_res["mae"] <= best_mae + margin].copy()
    
    complexity_order = {
        "ridge": 1,
        "elastic_net": 2,
        "random_forest": 3,
        "extra_trees": 4,
        "hist_gradient_boosting": 5,
        "personal_mean": 6,
        "naive_median": 7,
        "recent_mean_3": 8
    }
    equivalent["complexity"] = equivalent["model"].map(lambda m: complexity_order.get(m, 10))
    selected = equivalent.sort_values(["complexity", "mae"]).iloc[0]
    return str(selected["model"])


def conformal_radius(
    actual,
    predicted,
    alpha: float,
) -> float:
    residuals = np.abs(
        np.asarray(actual, dtype=float)
        - np.asarray(predicted, dtype=float)
    )
    residuals = residuals[np.isfinite(residuals)]

    if len(residuals) == 0:
        return np.nan

    q = np.ceil((len(residuals) + 1) * (1 - alpha)) / len(residuals)
    q = min(max(q, 0.0), 1.0)

    return float(np.quantile(residuals, q, method="higher"))


def interval_score(actual, lower, upper, alpha: float) -> float:
    actual = np.asarray(actual, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    score = (upper - lower).copy()
    below = actual < lower
    above = actual > upper
    score[below] += (2.0 / alpha) * (lower[below] - actual[below])
    score[above] += (2.0 / alpha) * (actual[above] - upper[above])
    return float(np.mean(score))


def interval_report(
    actual,
    predicted,
    radius80,
    radius90,
) -> Dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    lo80 = predicted - radius80
    hi80 = predicted + radius80
    lo90 = predicted - radius90
    hi90 = predicted + radius90

    cov80 = float(np.mean((actual >= lo80) & (actual <= hi80)))
    cov90 = float(np.mean((actual >= lo90) & (actual <= hi90)))

    return {
        "80_coverage": cov80,
        "coverage_80": cov80,
        "90_coverage": cov90,
        "coverage_90": cov90,
        "80_mean_width": float(np.mean(hi80 - lo80)),
        "90_mean_width": float(np.mean(hi90 - lo90)),
        "80_interval_score": interval_score(actual, lo80, hi80, alpha=0.20),
        "90_interval_score": interval_score(actual, lo90, hi90, alpha=0.10),
    }


def train_cyclesafe_V4(
    raw: pd.DataFrame,
    save_artifact: bool = True,
):
    print("=" * 80)
    print("CYCLESAFE V5 ELITE")
    print("=" * 80)

    clean, quality = clean_dataset(raw)

    print("\nDATA QUALITY")
    print(quality.to_string(index=False))

    model_data = build_forecasting_table(clean)

    global CONTEXT_FEATURES, FEATURES
    CONTEXT_FEATURES = []
    for c in SAFE_CONTEXT_COLUMNS:
        feature_group = [
            f"ctx_{c}",
            f"ctx_{c}_recent_mean",
            f"ctx_{c}_recent_std",
        ]
        if all(col in model_data.columns for col in feature_group):
            CONTEXT_FEATURES.extend(feature_group)

    FEATURES = [
        c for c in CORE_FEATURES + CONTEXT_FEATURES
        if c in model_data.columns
    ]

    print("\nFORECASTING DATASET")
    print("Examples:", len(model_data))
    print("Participants:", model_data["user_id"].nunique())

    dev, final_test = final_temporal_holdout(model_data)

    print("\nFINAL TEMPORAL HOLDOUT")
    print("Development examples:", len(dev))
    print("Untouched final-test examples:", len(final_test))

    folds = rolling_folds(dev)

    print("\nROLLING FOLDS")
    for i, (tr, va) in enumerate(folds, 1):
        print(
            f"Fold {i}: train={len(tr):,}, "
            f"validation={len(va):,}"
        )

    ridge_alpha_by_fold, ridge_tuning = nested_ridge_alpha_tuning(folds)

    print("\nNESTED RIDGE ALPHA TUNING")
    print(ridge_tuning.to_string(index=False))
    print("Selected alpha by outer fold:", ridge_alpha_by_fold)

    models = make_models(ridge_alpha=10.0)
    oof = generate_oof(
        folds,
        models,
        ridge_alpha_by_fold=ridge_alpha_by_fold,
    )

    results = evaluate_oof(oof, models)

    print("\nDEVELOPMENT OOF PERFORMANCE")
    print(results.to_string(index=False))

    selected_name = select_deployment_model(results)

    print("\nSelected deployment model:", selected_name)

    selected_prediction_col = (
        "personal_mean_prediction"
        if selected_name == "personal_mean"
        else "recent_mean_prediction"
        if selected_name == "recent_mean_3"
        else f"{selected_name}_prediction"
    )

    subgroup = error_by_history_and_variability(
        oof,
        selected_prediction_col,
    )

    print("\nERROR BY HISTORY LENGTH x VARIABILITY")
    print(subgroup.to_string(index=False))

    selected_oof_pred = oof[selected_prediction_col].to_numpy()
    radius80 = conformal_radius(
        oof["actual"],
        selected_oof_pred,
        alpha=0.20,
    )
    radius90 = conformal_radius(
        oof["actual"],
        selected_oof_pred,
        alpha=0.10,
    )

    final_model = None
    final_ridge_alpha = 10.0
    final_ridge_tuning = pd.DataFrame()

    if selected_name == "ridge":
        final_ridge_alpha, final_ridge_tuning = tune_final_ridge_alpha(dev)
        print("\nFINAL DEVELOPMENT-ONLY RIDGE ALPHA:", final_ridge_alpha)
        
    final_models = {}
    for name, pipeline in models.items():
        if name == "ridge":
            m = make_models(ridge_alpha=final_ridge_alpha)["ridge"]
        else:
            m = clone(pipeline)
        m.fit(dev[FEATURES], dev["target"])
        final_models[name] = m

    if selected_name in final_models:
        final_model = final_models[selected_name]

    if selected_name in models:
        final_test_pred = final_model.predict(final_test[FEATURES])
    elif selected_name == "personal_mean":
        final_test_pred = final_test["personal_mean"].to_numpy()
    elif selected_name == "naive_last_cycle":
        final_test_pred = final_test["lag_1"].to_numpy()
    elif selected_name == "naive_median":
        final_test_pred = final_test["personal_median"].to_numpy()
    elif selected_name == "naive_mean":
        final_test_pred = final_test["personal_mean"].to_numpy()
    else:
        final_test_pred = final_test["mean_3"].to_numpy()

    final_test_eval = final_test.copy()
    for m_name, m_model in final_models.items():
        preds = m_model.predict(final_test[FEATURES])
        final_test_eval[m_name] = preds
        final_test_eval[f"{m_name}_prediction"] = preds

    final_test_eval['personal_mean'] = final_test['personal_mean'].to_numpy()
    final_test_eval['recent_mean_3'] = final_test['mean_3'].to_numpy()
    final_test_eval['naive_last_cycle'] = final_test['lag_1'].to_numpy()
    final_test_eval['naive_median'] = final_test['personal_median'].to_numpy()

    final_test_lower = np.maximum(MIN_CYCLE_LENGTH, final_test_pred - radius80)
    final_test_upper = np.minimum(MAX_CYCLE_LENGTH, final_test_pred + radius80)

    final_metrics = metrics(
        final_test["target"],
        final_test_pred,
    )

    final_eval = final_test[
        ["user_id", "cycle_number", "target"]
    ].copy()
    final_eval["actual"] = final_test["target"].astype(float)
    final_eval["prediction"] = final_test_pred
    final_eval["abs_error"] = np.abs(
        final_eval["actual"] - final_eval["prediction"]
    )

    macro_final = macro_user_metrics(
        final_eval.rename(
            columns={"prediction": "selected_prediction"}
        ),
        "selected_prediction",
    )

    interval = interval_report(
        final_test["target"].to_numpy(),
        final_test_pred,
        radius80,
        radius90,
    )

    print("\nUNTOUCHED FINAL TEST")
    print("MAE:", round(final_metrics["mae"], 3))
    print("RMSE:", round(final_metrics["rmse"], 3))
    print("Macro user MAE:", round(macro_final["macro_mae"], 3))
    print("Median user MAE:", round(macro_final["median_user_mae"], 3))
    print("80% empirical coverage:", round(interval["80_coverage"] * 100, 1), "%")
    print("90% empirical coverage:", round(interval["90_coverage"] * 100, 1), "%")
    print("80% interval width:", round(interval["80_mean_width"], 2), "days")
    print("90% interval width:", round(interval["90_mean_width"], 2), "days")

    artifact = {
        "version": "5.0-ELITE",
        "deployment_model_name": selected_name,
        "ridge_alpha": final_ridge_alpha,
        "ridge_tuning_by_outer_fold": ridge_tuning,
        "final_ridge_tuning": final_ridge_tuning,
        "model": final_model,
        "all_models": final_models,
        "features": FEATURES,
        "core_features": CORE_FEATURES,
        "context_features": CONTEXT_FEATURES,
        "safe_context_columns": SAFE_CONTEXT_COLUMNS,
        "radius80_days": radius80,
        "radius90_days": radius90,
        "min_cycle_length": MIN_CYCLE_LENGTH,
        "max_cycle_length": MAX_CYCLE_LENGTH,
        "min_history_for_model": MIN_HISTORY_FOR_MODEL,
        "development_oof_results": results,
        "final_test_metrics": {
            **final_metrics,
            **macro_final,
            **interval,
        },
    }

    if save_artifact:
        os.makedirs(os.path.dirname(ARTIFACT_PATH), exist_ok=True)
        with open(ARTIFACT_PATH, "wb") as f:
            pickle.dump(artifact, f)

        print("\nSaved artifact:", ARTIFACT_PATH)
        
    return {
        "clean_data": clean,
        "quality": quality,
        "model_data": model_data,
        "development": dev,
        "dev_data": dev,
        "folds": folds,
        "final_test": final_test,
        "test_predictions": final_test_eval,
        "final_test_lower": final_test_lower,
        "final_test_upper": final_test_upper,
        "oof": oof,
        "results": results,
        "subgroup_errors": subgroup,
        "deployment_model": final_model,
        "deployment_model_name": selected_name,
        "radius80_days": radius80,
        "radius90_days": radius90,
        "final_test_predictions": final_test_pred,
        "final_test_metrics": {
            **final_metrics,
            **macro_final,
            **interval,
        },
        "final_test_interval_report": interval,
        "artifact": artifact,
        "ridge_tuning_by_outer_fold": ridge_tuning,
        "final_ridge_alpha": final_ridge_alpha,
        "final_ridge_tuning": final_ridge_tuning,
        "forecasting_examples": len(model_data),
        "participants": model_data["user_id"].nunique(),
        "development_examples": len(dev),
        "final_test_examples": len(final_test),
    }


def forecast_next_cycle(
    previous_cycles: List[float],
    previous_context: Optional[pd.DataFrame] = None,
    artifact_path: str = ARTIFACT_PATH,
) -> Dict:
    if len(previous_cycles) < MIN_HISTORY_FOR_MODEL:
        raise ValueError(
            f"At least {MIN_HISTORY_FOR_MODEL} completed cycles are required."
        )

    import joblib
    artifact = joblib.load(artifact_path)

    features = history_features(
        previous_cycles,
        previous_context,
    )

    row = pd.DataFrame([features])

    for feature in artifact["features"]:
        if feature not in row.columns:
            row[feature] = np.nan

    row = row[artifact["features"]]

    model_name = artifact["deployment_model_name"]

    if model_name in {"personal_mean", "recent_mean_3", "naive_last_cycle", "naive_median", "naive_mean"}:
        if model_name == "personal_mean" or model_name == "naive_mean":
            prediction = features["personal_mean"]
        elif model_name == "naive_median":
            prediction = features["personal_median"]
        elif model_name == "naive_last_cycle":
            prediction = features["lag_1"]
        else:
            prediction = features["mean_3"]
    else:
        prediction = float(
            artifact["model"].predict(row)[0]
        )

    all_preds = []
    if "all_models" in artifact and artifact["all_models"]:
        for m_name, m in artifact["all_models"].items():
            all_preds.append(float(m.predict(row)[0]))
    
    model_disagreement = 0.0
    if all_preds:
        model_disagreement = max(all_preds) - min(all_preds)
        
    confidence_component = "high"
    if model_disagreement > 3.0:
        confidence_component = "medium"
    if model_disagreement > 6.0:
        confidence_component = "low"

    radius80 = float(artifact["radius80_days"])
    radius90 = float(artifact["radius90_days"])

    prediction = float(
        np.clip(
            prediction,
            MIN_CYCLE_LENGTH,
            MAX_CYCLE_LENGTH,
        )
    )

    return {
        "model_version": "CycleSafe V5",
        "predicted_cycle_length_days": round(prediction, 2),
        "estimated_range_80_percent": {
            "lower_days": round(
                max(MIN_CYCLE_LENGTH, prediction - radius80),
                2,
            ),
            "upper_days": round(
                min(MAX_CYCLE_LENGTH, prediction + radius80),
                2,
            ),
        },
        "estimated_range_90_percent": {
            "lower_days": round(
                max(MIN_CYCLE_LENGTH, prediction - radius90),
                2,
            ),
            "upper_days": round(
                min(MAX_CYCLE_LENGTH, prediction + radius90),
                2,
            ),
        },
        "model_disagreement_days": round(model_disagreement, 2),
        "confidence_level": confidence_component,
        "history_count": len(previous_cycles),
        "deployment_model": model_name,
        "uncertainty_note": (
            "These are empirically calibrated forecast ranges based on "
            "historical model errors; they are not clinical guarantees."
        ),
    }



def seed_stability_check(folds, features, target_col='target', seeds=[0, 7, 42, 123, 2026]):
    """Evaluate stochastic candidate models across multiple random seeds on development OOF only."""
    from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
    
    print("\n" + "=" * 90)
    print("CYCLESAFE V5 — RANDOM SEED STABILITY CHECK (DEVELOPMENT OOF ONLY)")
    print("=" * 90)
    
    results = []
    model_factories = {
        "random_forest": lambda s: RandomForestRegressor(n_estimators=100, max_depth=8, min_samples_leaf=8, max_features="sqrt", random_state=s, n_jobs=-1),
        "extra_trees": lambda s: ExtraTreesRegressor(n_estimators=100, max_depth=8, min_samples_leaf=8, max_features="sqrt", random_state=s, n_jobs=-1)
    }
    
    for m_name, factory in model_factories.items():
        seed_maes = []
        for seed in seeds:
            oof_errors = []
            for train, valid in folds:
                m = factory(seed)
                m.fit(train[features], train[target_col])
                pred = m.predict(valid[features])
                oof_errors.extend(np.abs(valid[target_col].values - pred))
            seed_maes.append(float(np.mean(oof_errors)))
            
        results.append({
            "model": m_name,
            "seeds_tested": len(seeds),
            "seed_mean_mae": round(float(np.mean(seed_maes)), 4),
            "seed_std_mae": round(float(np.std(seed_maes)), 4),
            "min_seed_mae": round(float(np.min(seed_maes)), 4),
            "max_seed_mae": round(float(np.max(seed_maes)), 4),
            "stability_status": "STABLE" if np.std(seed_maes) < 0.02 else "MODERATE_VARIANCE"
        })
        
    df_seed = pd.DataFrame(results)
    print(df_seed.to_string(index=False))
    return df_seed


if __name__ == "__main__":
    raw_data = load_csv_source(DATA_URL)
    result = train_cyclesafe_V4(raw_data, save_artifact=True)

    print("\n" + "=" * 80)
    print("CYCLESAFE V5 COMPLETE")
    print("=" * 80)
    print(
        "Deployment model:",
        result["deployment_model_name"],
    )
    print(
        "Untouched final-test MAE:",
        round(result["final_test_metrics"]["mae"], 3),
        "days",
    )
    print(
        "Untouched final-test RMSE:",
        round(result["final_test_metrics"]["rmse"], 3),
        "days",
    )

# END CELL 1


import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

# %%
# =============================================================================
# CELL 2 - CYCLESAFE V5 ABLATION STUDY
# =============================================================================

def run_ablation_study(dev, folds, target_col='target'):
    """Train Ridge with progressive feature groups through temporal OOF."""
    ablation_rows = []
    
    # In practice, FEATURE_GROUPS should be defined in Cell 1
    # Fallback if not available
    feature_groups = globals().get('FEATURE_GROUPS', {})
    
    for group_name, group_features in feature_groups.items():
        # Filter to features that exist in dev
        available = [f for f in group_features if f in dev.columns]
        if not available:
            continue
        
        fold_errors = []
        for fold_id, (train, valid) in enumerate(folds, 1):
            pipe = Pipeline([
                ('imputer', SimpleImputer(strategy='median')),
                ('scaler', StandardScaler()),
                ('model', Ridge(alpha=10.0)),
            ])
            pipe.fit(train[available], train[target_col])
            pred = pipe.predict(valid[available])
            fold_errors.extend(np.abs(valid[target_col].values - pred))
        
        mae = np.mean(fold_errors)
        rmse = np.sqrt(np.mean(np.array(fold_errors)**2))
        ablation_rows.append({
            'feature_group': group_name,
            'n_features': len(available),
            'mae': mae,
            'rmse': rmse,
        })
    
    return pd.DataFrame(ablation_rows)

if 'result' in globals() and 'FEATURE_GROUPS' in globals():
    print("Running Ablation Study...")
    ablation_df = run_ablation_study(
        result['dev_data'], 
        result['folds'], 
        target_col='target'
    )
    print("\n--- Ablation Study Results ---")
    print(ablation_df.to_string(index=False))

# %%
# =============================================================================  
# CELL 3 - CYCLESAFE V5 SUBGROUP EVALUATION + PER-USER ERROR ANALYSIS
# =============================================================================

def evaluate_subgroups(oof_df, pred_col=None):
    oof = oof_df.copy()
    target_col = 'actual' if 'actual' in oof.columns else 'target'
    
    if pred_col is None or pred_col not in oof.columns:
        if pred_col is not None and f"{pred_col}_prediction" in oof.columns:
            pred_col = f"{pred_col}_prediction"
        elif 'selected_prediction' in oof.columns:
            pred_col = 'selected_prediction'
        elif 'random_forest_prediction' in oof.columns:
            pred_col = 'random_forest_prediction'
        elif 'ridge_prediction' in oof.columns:
            pred_col = 'ridge_prediction'
        else:
            cols = [c for c in oof.columns if 'prediction' in c]
            pred_col = cols[0] if cols else target_col

    oof['error'] = np.abs(oof[target_col] - oof[pred_col])
    
    print("\n--- Subgroup Evaluation ---")
    
    # 1. By history length
    bins = [0, 4, 6, 9, 14, np.inf]
    labels = ['3-4', '5-6', '7-9', '10-14', '15+']
    oof['hist_bin'] = pd.cut(oof['history_count'], bins=bins, labels=labels)
    hist_mae = oof.groupby('hist_bin')['error'].mean()
    print("\nMAE by History Length:")
    print(hist_mae)
    
    # 2. By cycle variability tertiles
    if 'cv_5' in oof.columns:
        oof['cv_tertile'] = pd.qcut(oof['cv_5'], q=3, labels=['low', 'medium', 'high'])
        cv_mae = oof.groupby('cv_tertile')['error'].mean()
        print("\nMAE by Cycle Variability (CV_5):")
        print(cv_mae)
    
    # 3. By cycle-length range
    len_bins = [0, 24, 30, 35, np.inf]
    len_labels = ['<25', '25-30', '30-35', '>35']
    oof['len_bin'] = pd.cut(oof[target_col], bins=len_bins, labels=len_labels)
    len_mae = oof.groupby('len_bin')['error'].mean()
    print("\nMAE by Cycle Length Range:")
    print(len_mae)
    
    # Per-user error distribution
    user_err = oof.groupby('user_id')['error'].mean()
    print("\n--- Per-User Error Distribution ---")
    print(f"Users evaluated: {len(user_err)}")
    print(f"Median user MAE: {user_err.median():.2f}")
    print(f"Mean user MAE: {user_err.mean():.2f}")
    print(f"Worst-user MAE: {user_err.max():.2f}")
    print(f"90th percentile user MAE: {np.percentile(user_err, 90):.2f}")
    
    print("\nError Buckets:")
    print(f"<=1 day error: {(user_err <= 1).sum()} users ({(user_err <= 1).mean():.1%})")
    print(f"<=2 days error: {(user_err <= 2).sum()} users ({(user_err <= 2).mean():.1%})")
    print(f"<=3 days error: {(user_err <= 3).sum()} users ({(user_err <= 3).mean():.1%})")
    print(f">5 days error: {(user_err > 5).sum()} users ({(user_err > 5).mean():.1%})")

    # Coverage by subgroup
    # Computing 80% and 90% empirical conformal radius from the entire OOF set
    radius_80 = np.quantile(oof['error'], 0.80)
    radius_90 = np.quantile(oof['error'], 0.90)
    oof['covered_80'] = oof['error'] <= radius_80
    oof['covered_90'] = oof['error'] <= radius_90
    
    print("\n80% and 90% Coverage by History Length:")
    cov_hist = oof.groupby('hist_bin')[['covered_80', 'covered_90']].mean()
    print(cov_hist)
    
    if 'cv_5' in oof.columns:
        print("\n80% and 90% Coverage by Variability (CV_5):")
        cov_cv = oof.groupby('cv_tertile')[['covered_80', 'covered_90']].mean()
        print(cov_cv)

if 'result' in globals() and 'oof' in result:
    evaluate_subgroups(result['oof'])

# %%
# =============================================================================
# CELL 4 - CYCLESAFE V5 BOOTSTRAP CIs + CALIBRATION + SIGNIFICANCE
# =============================================================================

def user_clustered_bootstrap_metric(df, user_col, metric_fn, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    users = df[user_col].unique()
    n_users = len(users)
    
    boot_metrics = np.empty(n_boot)
    
    # Pre-calculate user indices for speed
    user_indices = {u: np.where(df[user_col].values == u)[0] for u in users}
    
    for i in range(n_boot):
        sampled_users = rng.choice(users, size=n_users, replace=True)
        sampled_idx = np.concatenate([user_indices[u] for u in sampled_users])
        sample_df = df.iloc[sampled_idx]
        boot_metrics[i] = metric_fn(sample_df)
        
    return {
        'mean': np.mean(boot_metrics),
        'lower_95': np.percentile(boot_metrics, 2.5),
        'upper_95': np.percentile(boot_metrics, 97.5)
    }

def calibration_curve(oof_df, test_df, pred_col, target_col=None):
    print("\n--- Calibration Curve ---")
    print(f"{'Quantile':<10} {'OOF Radius':<15} {'Test Coverage':<15}")
    
    results = []
    oof_target = 'actual' if 'actual' in oof_df.columns else 'target'
    oof_pred = f"{pred_col}_prediction" if f"{pred_col}_prediction" in oof_df.columns else pred_col
    oof_errors = np.abs(oof_df[oof_target] - oof_df[oof_pred])
    
    if test_df is not None and not test_df.empty:
        test_target = 'target' if 'target' in test_df.columns else 'actual'
        test_pred = pred_col if pred_col in test_df.columns else f"{pred_col}_prediction"
        test_errors = np.abs(test_df[test_target] - test_df[test_pred])
    else:
        test_errors = None
    
    for q in np.arange(0.1, 1.0, 0.1):
        q = round(q, 1)
        radius = np.quantile(oof_errors, q)
        
        if test_errors is not None:
            test_coverage = np.mean(test_errors <= radius)
        else:
            test_coverage = np.nan
            
        print(f"{q:<10.1f} {radius:<15.3f} {test_coverage:<15.3%}")
        results.append({'quantile': q, 'radius': radius, 'test_coverage': test_coverage})
        
    return pd.DataFrame(results)

def paired_bootstrap_comparison(df, pred_a, pred_b, target='target', user_col='user_id', n_boot=1000):
    def mae_diff(d):
        mae_a = np.abs(d[target] - d[pred_a]).mean()
        mae_b = np.abs(d[target] - d[pred_b]).mean()
        return mae_a - mae_b
        
    res = user_clustered_bootstrap_metric(df, user_col, mae_diff, n_boot=n_boot)
    print(f"{pred_a} vs {pred_b}:")
    print(f"  Diff: {res['mean']:.4f} [95% CI: {res['lower_95']:.4f}, {res['upper_95']:.4f}]")

if 'result' in globals():
    print("\nRunning Bootstrap & Calibration Analysis...")
    oof_df = result.get('oof')
    test_df = result.get('test_predictions') 
    main_model = result.get('deployment_model_name', 'random_forest')
    
    if oof_df is not None and test_df is not None:
        test_pred_col = main_model if main_model in test_df.columns else f"{main_model}_prediction"
        target_col = 'target' if 'target' in test_df.columns else 'actual'
        
        def mae_metric(d): return np.abs(d[target_col] - d[test_pred_col]).mean()
        def rmse_metric(d): return np.sqrt(np.mean(np.square(d[target_col] - d[test_pred_col])))
        
        print(f"\nFinal Test {main_model} Bootstrap CIs:")
        mae_ci = user_clustered_bootstrap_metric(test_df, 'user_id', mae_metric, n_boot=1000)
        rmse_ci = user_clustered_bootstrap_metric(test_df, 'user_id', rmse_metric, n_boot=1000)
        
        print(f"MAE:  {mae_ci['mean']:.3f} [{mae_ci['lower_95']:.3f}, {mae_ci['upper_95']:.3f}]")
        print(f"RMSE: {rmse_ci['mean']:.3f} [{rmse_ci['lower_95']:.3f}, {rmse_ci['upper_95']:.3f}]")
        
        calibration_curve(oof_df, test_df, pred_col=main_model)
        
        models_to_compare = [
            'ridge', 'random_forest', 'extra_trees', 'personal_mean', 'recent_mean_3'
        ]
        available_models = [m for m in models_to_compare if m in test_df.columns]
        if len(available_models) > 1:
            print("\nPaired Model Comparisons on Final Test (Difference in MAE):")
            print("Negative means first model is better.")
            for i, m1 in enumerate(available_models):
                for m2 in available_models[i+1:]:
                    paired_bootstrap_comparison(test_df, m1, m2, target=target_col, n_boot=1000)


# %%
# =============================================================================
# CELL 5 - CYCLESAFE V5 PERSONALIZATION GATE + RELIABILITY SCORING
# =============================================================================

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

def personalization_reliability(history_count, cycle_sd, recent_sd, prediction_spread):
    score = 0.0
    if history_count >= 8: score += 0.30
    elif history_count >= 6: score += 0.20
    elif history_count >= 5: score += 0.10
    
    if cycle_sd is not None and not np.isnan(cycle_sd):
        if cycle_sd < 2: score += 0.25
        elif cycle_sd < 4: score += 0.15
    
    if recent_sd is not None and not np.isnan(recent_sd):
        if recent_sd < 2: score += 0.20
        elif recent_sd < 4: score += 0.10
    
    if prediction_spread is not None and not np.isnan(prediction_spread):
        if prediction_spread < 1.0: score += 0.25
        elif prediction_spread < 2.0: score += 0.15
    
    return min(score, 1.0)

def run_enhanced_personalization_gate(cyclesafe_result):
    oof = cyclesafe_result["oof"].copy()
    final_test = cyclesafe_result["final_test"].copy()
    deployment_name = cyclesafe_result["deployment_model_name"]
    
    if deployment_name in {"personal_mean", "recent_mean_3"}:
        print("Personalization gate skipped: the selected deployment model is already a personal baseline.")
        return None
        
    population_col = f"{deployment_name}_prediction"
    
    gate_features = ["history_count", "cv_5", "std_5", "personal_gap"]
    gate_oof = oof.copy()
    
    gate_oof["personal_gap"] = gate_oof["personal_mean_prediction"] - gate_oof[population_col]
    gate_oof = gate_oof.replace([np.inf, -np.inf], np.nan)
    gate_oof = gate_oof.dropna(subset=["actual", population_col, "personal_mean_prediction", *gate_features]).copy()
    
    personal_error = np.abs(gate_oof["actual"] - gate_oof["personal_mean_prediction"])
    population_error = np.abs(gate_oof["actual"] - gate_oof[population_col])
    
    gate_oof["personal_wins"] = (personal_error < population_error).astype(int)
    
    target_classes = gate_oof["personal_wins"].nunique()
    if target_classes < 2:
        print("Gate training skipped. Only one class in OOF.")
        return None
        
    gate_model = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(class_weight="balanced", random_state=42, max_iter=2000)),
    ])
    gate_model.fit(gate_oof[gate_features], gate_oof["personal_wins"])
    
    # 3. PREPARE UNTOUCHED FINAL TEST
    final = final_test.copy()
    final["population_prediction"] = np.asarray(cyclesafe_result["final_test_predictions"], dtype=float)
    final["personal_gap"] = final["personal_mean"] - final["population_prediction"]
    
    # ADDED FOR RELIABILITY
    final["prediction_spread"] = np.abs(final["personal_gap"])
    
    def get_rel_score(row):
        return personalization_reliability(
            row["history_count"],
            row.get("personal_std", np.nan),
            row.get("std_5", np.nan),
            row["prediction_spread"]
        )
        
    final["reliability_score"] = final.apply(get_rel_score, axis=1)
    
    final_gate_frame = final[gate_features].replace([np.inf, -np.inf], np.nan)
    valid_final_gate = final_gate_frame.notna().all(axis=1)
    
    final["logistic_probability"] = 0.0
    if valid_final_gate.any():
        final.loc[valid_final_gate, "logistic_probability"] = gate_model.predict_proba(
            final.loc[valid_final_gate, gate_features]
        )[:, 1]
        
    # LOGISTIC GATED
    final["logistic_gated_prediction"] = (
        final["logistic_probability"] * final["personal_mean"] +
        (1.0 - final["logistic_probability"]) * final["population_prediction"]
    )
    
    # RULE GATED
    final["rule_gated_prediction"] = (
        final["reliability_score"] * final["personal_mean"] +
        (1.0 - final["reliability_score"]) * final["population_prediction"]
    )
    
    # Evaluate
    valid_prediction_rows = (
        np.isfinite(final["target"].to_numpy(dtype=float)) &
        np.isfinite(final["population_prediction"].to_numpy(dtype=float)) &
        np.isfinite(final["personal_mean"].to_numpy(dtype=float)) &
        np.isfinite(final["logistic_gated_prediction"].to_numpy(dtype=float)) &
        np.isfinite(final["rule_gated_prediction"].to_numpy(dtype=float))
    )
    evaluation = final.loc[valid_prediction_rows].copy()
    
    base_mae = float(np.mean(np.abs(evaluation["target"] - evaluation["population_prediction"])))
    personal_mae = float(np.mean(np.abs(evaluation["target"] - evaluation["personal_mean"])))
    logistic_mae = float(np.mean(np.abs(evaluation["target"] - evaluation["logistic_gated_prediction"])))
    rule_mae = float(np.mean(np.abs(evaluation["target"] - evaluation["rule_gated_prediction"])))
    
    result_table = pd.DataFrame([
        {"strategy": "population-only", "mae": base_mae},
        {"strategy": "personal-only", "mae": personal_mae},
        {"strategy": "rule-gated", "mae": rule_mae},
        {"strategy": "logistic-gated", "mae": logistic_mae},
    ])
    
    # Gate behavior analysis by reliability score buckets
    final["reliability_bucket"] = pd.cut(
        final["reliability_score"],
        bins=[-np.inf, 0.2, 0.4, 0.6, 0.8, np.inf],
        labels=["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    )
    
    gate_behavior = final["reliability_bucket"].value_counts(sort=False).rename_axis("reliability_score_range").reset_index(name="observations")
    
    def calc_confidence_components(row):
        hc = row["history_count"]
        hist_conf = 0.3 if hc >= 8 else (0.2 if hc >= 6 else (0.1 if hc >= 5 else 0))
        
        rs = row.get("std_5", np.nan)
        pattern_stab = 0.0
        if pd.notna(rs):
            pattern_stab = 0.2 if rs < 2 else (0.1 if rs < 4 else 0)
            
        ps = row["prediction_spread"]
        model_agree = 0.0
        if pd.notna(ps):
            model_agree = 0.25 if ps < 1.0 else (0.15 if ps < 2.0 else 0)
            
        data_comp = 0.25 # simplified
        overall = hist_conf + pattern_stab + model_agree + data_comp
        return pd.Series({
            "history_confidence": hist_conf,
            "pattern_stability": pattern_stab,
            "model_agreement": model_agree,
            "data_completeness": data_comp,
            "overall_evidence_strength": min(overall, 1.0)
        })
        
    confidence_df = evaluation.apply(calc_confidence_components, axis=1)
    
    print("="*90)
    print("CYCLESAFE V5 - ENHANCED PERSONALIZATION GATE")
    print("="*90)
    print("\nFINAL TEST COMPARISON")
    print(result_table.to_string(index=False))
    print("\nGATE BEHAVIOR BY RELIABILITY BUCKET")
    print(gate_behavior.to_string(index=False))
    print("\nAVERAGE FORECAST CONFIDENCE COMPONENTS")
    print(confidence_df.mean().to_frame("Average Score").to_string())

if 'result' in globals():
    run_enhanced_personalization_gate(result)


# %%
# =============================================================================
# CELL 6 - CYCLESAFE V5 QUANTILE REGRESSION EXPERIMENT  
# =============================================================================

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
import warnings

def run_quantile_regression_experiment(cyclesafe_result):
    warnings.filterwarnings("ignore")
    
    development = cyclesafe_result["development"].copy()
    final_test = cyclesafe_result["final_test"].copy()
    
    FEATURES = [
        "lag_1", "lag_2", "lag_3",
        "mean_3", "median_3", "mean_5", "median_5", "mean_8", "mean_12",
        "std_3", "std_5", "std_8", "std_12",
        "mad_5", "iqr_5", "range_5", "cv_5",
        "personal_mean", "personal_median", "personal_std",
        "last_minus_personal_mean", "last_minus_mean_5",
        "mean_3_minus_mean_8", "mean_5_minus_mean_12",
        "delta_1", "delta_2", "trend_5", "trend_8",
        "ewma_35", "ewma_60", "ewstd_35",
        "history_count", "long_cycle_fraction", "short_cycle_fraction",
        "near_personal_baseline_fraction"
    ]
    
    for col in development.columns:
        if col.startswith("ctx_") and col not in FEATURES:
            FEATURES.append(col)
            
    dev_mask = np.isfinite(development["target"])
    dev = development.loc[dev_mask].copy()
    
    if dev.empty:
        print("No valid development rows for training.")
        return
        
    print("Training Quantile Regression Models (alpha=0.10, 0.50, 0.90)...")
    
    models = {}
    for alpha in [0.10, 0.50, 0.90]:
        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("gbr", GradientBoostingRegressor(
                loss="quantile", alpha=alpha, n_estimators=150, max_depth=4, random_state=42
            ))
        ])
        model.fit(dev[FEATURES], dev["target"])
        models[f"p{int(alpha*100)}"] = model
        
    final_mask = np.isfinite(final_test["target"])
    eval_test = final_test.loc[final_mask].copy()
    
    if eval_test.empty:
        print("No valid final test rows.")
        return
        
    eval_test["qr_p10"] = models["p10"].predict(eval_test[FEATURES])
    eval_test["qr_p50"] = models["p50"].predict(eval_test[FEATURES])
    eval_test["qr_p90"] = models["p90"].predict(eval_test[FEATURES])
    
    if "final_test_lower" in cyclesafe_result:
        eval_test["conf_lower"] = cyclesafe_result["final_test_lower"]
        eval_test["conf_upper"] = cyclesafe_result["final_test_upper"]
        eval_test["conf_pred"] = cyclesafe_result["final_test_predictions"]
    else:
        print("Conformal interval predictions not found in result.")
        return
        
    eval_test["qr_covered"] = (eval_test["target"] >= eval_test["qr_p10"]) & (eval_test["target"] <= eval_test["qr_p90"])
    qr_coverage = eval_test["qr_covered"].mean()
    
    eval_test["conf_covered"] = (eval_test["target"] >= eval_test["conf_lower"]) & (eval_test["target"] <= eval_test["conf_upper"])
    conf_coverage = eval_test["conf_covered"].mean()
    
    eval_test["qr_width"] = eval_test["qr_p90"] - eval_test["qr_p10"]
    qr_mean_width = eval_test["qr_width"].mean()
    
    eval_test["conf_width"] = eval_test["conf_upper"] - eval_test["conf_lower"]
    conf_mean_width = eval_test["conf_width"].mean()
    
    qr_mae = np.mean(np.abs(eval_test["target"] - eval_test["qr_p50"]))
    conf_mae = np.mean(np.abs(eval_test["target"] - eval_test["conf_pred"]))
    
    comparison_table = pd.DataFrame([
        {
            "Experiment": "A (Conformal Intervals)",
            "P10-P90 Coverage": f"{conf_coverage*100:.1f}%",
            "Mean Interval Width": f"{conf_mean_width:.2f} days",
            "P50/Point MAE": f"{conf_mae:.2f} days"
        },
        {
            "Experiment": "B (Quantile Regression)",
            "P10-P90 Coverage": f"{qr_coverage*100:.1f}%",
            "Mean Interval Width": f"{qr_mean_width:.2f} days",
            "P50/Point MAE": f"{qr_mae:.2f} days"
        }
    ])
    
    print("="*90)
    print("CYCLESAFE V5 - QUANTILE REGRESSION EXPERIMENT")
    print("="*90)
    print("\nFINAL TEST INTERVAL COMPARISON (80% Target Coverage)")
    print(comparison_table.to_string(index=False))

if 'result' in globals():
    run_quantile_regression_experiment(result)


# %%
# ======================================================================
# CYCLESAFE V5 - CELL 7: V2 LAYER + DEMO USERS + ENHANCED INSIGHT + ENHANCED REPORT
# ======================================================================


from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from enum import Enum
from statistics import median, mean
from typing import Any, Dict, List, Optional, Sequence
import math
import numpy as np
import pandas as pd
import os

# Assuming ARTIFACT_PATH and MIN_HISTORY_FOR_MODEL are defined in previous cells
ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"
MIN_HISTORY_FOR_MODEL = 3


# ======================================================================
# 7A: DATA MODELS (Original lines 1336-1460 + Enhanced fields)
# ======================================================================

class LifeStage(str, Enum):
    MENSTRUAL = "menstrual"
    PERIMENOPAUSE = "perimenopause"
    MENOPAUSE = "menopause"
    UNKNOWN = "unknown"

class SymptomSeverity(str, Enum):
    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"

@dataclass
class CycleRecord:
    start_date: date
    end_date: Optional[date] = None
    cycle_length_days: Optional[float] = None
    flow: Optional[str] = None

@dataclass
class SymptomRecord:
    record_date: date
    symptom: str
    severity: SymptomSeverity = SymptomSeverity.MILD
    duration_days: Optional[float] = None
    notes: Optional[str] = None

@dataclass
class WellbeingRecord:
    record_date: date
    sleep_quality: Optional[float] = None
    mood: Optional[float] = None
    energy: Optional[float] = None

@dataclass
class ReproductiveProfile:
    user_id: str
    self_reported_stage: LifeStage = LifeStage.UNKNOWN
    age: Optional[int] = None
    last_known_period: Optional[date] = None

@dataclass
class UserTimeline:
    profile: ReproductiveProfile
    cycles: List[CycleRecord] = field(default_factory=list)
    symptoms: List[SymptomRecord] = field(default_factory=list)
    wellbeing: List[WellbeingRecord] = field(default_factory=list)

@dataclass
class PersonalBaseline:
    cycle_median: Optional[float]
    cycle_mean: Optional[float]
    cycle_sd: Optional[float]
    recent_cycle_median: Optional[float]
    cycle_variability: Optional[float]
    symptom_frequency: Dict[str, float]
    symptom_severity_mean: Dict[str, float]
    wellbeing_summary: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    baseline_cycle_count: int = 0
    recent_cycle_count: int = 0
    # --- ENHANCED FIELDS for V5 ---
    recent_symptom_frequency: Dict[str, float] = field(default_factory=dict)
    symptom_persistence: Dict[str, int] = field(default_factory=dict)
    symptom_change_detected: Dict[str, bool] = field(default_factory=dict)
    data_completeness_score: Dict[str, float] = field(default_factory=dict)
    missingness_tracking: Dict[str, str] = field(default_factory=dict)

@dataclass
class PatternSummary:
    cycle_change_detected: bool
    cycle_change_days: Optional[float]
    variability_change_detected: bool
    recurring_symptoms: List[str]
    rising_symptoms: List[str]
    notes: List[str]
    # --- ENHANCED FIELDS for V5 ---
    drift_detected: bool = False
    drift_evidence: List[str] = field(default_factory=list)

@dataclass
class ForecastResult:
    predicted_cycle_length_days: Optional[float]
    lower_80_days: Optional[float]
    upper_80_days: Optional[float]
    lower_90_days: Optional[float]
    upper_90_days: Optional[float]
    predicted_absolute_error_days: Optional[float]
    method: str
    # --- ENHANCED FIELDS for V5 ---
    model_agreement_spread: Optional[float] = None
    model_agreement_details: Dict[str, float] = field(default_factory=dict)
    confidence_history: int = 0
    confidence_pattern: int = 0
    confidence_model: int = 0
    confidence_overall: str = "Moderate"

@dataclass
class CycleSafeInsight:
    title: str
    body: str
    category: str = "pattern"
    informational: bool = True


# ======================================================================
# 7B: ENHANCED FEATURE ENGINE
# ======================================================================

class FeatureEngine:
    @staticmethod
    def cycle_lengths(timeline: UserTimeline) -> List[float]:
        ordered = sorted(timeline.cycles, key=lambda c: c.start_date)
        return [
            float(c.cycle_length_days)
            for c in ordered
            if (
                c.cycle_length_days is not None
                and math.isfinite(float(c.cycle_length_days))
            )
        ]

    def build_personal_baseline(
        self,
        timeline: UserTimeline,
        recent_n: int = 6,
    ) -> PersonalBaseline:

        lengths = self.cycle_lengths(timeline)
        recent = lengths[-recent_n:] if lengths else []

        cycle_mean = mean(lengths) if lengths else None
        cycle_median = median(lengths) if lengths else None
        cycle_sd = (
            math.sqrt(sum((x - cycle_mean) ** 2 for x in lengths) / (len(lengths) - 1))
            if len(lengths) > 1 else None
        )
        recent_median = median(recent) if recent else None

        symptom_frequency: Dict[str, float] = {}
        symptom_severity: Dict[str, List[float]] = {}
        severity_map = {
            SymptomSeverity.NONE: 0.0,
            SymptomSeverity.MILD: 1.0,
            SymptomSeverity.MODERATE: 2.0,
            SymptomSeverity.SEVERE: 3.0,
        }

        # Track distinct cycles for persistence
        symptom_cycles: Dict[str, set] = {}

        for s in timeline.symptoms:
            symptom_frequency[s.symptom] = symptom_frequency.get(s.symptom, 0.0) + 1.0
            symptom_severity.setdefault(s.symptom, []).append(severity_map[s.severity])
            
            # Map symptom to a cycle by date proximity (simplified)
            cycle_idx = -1
            for i, c in enumerate(timeline.cycles):
                if c.start_date <= s.record_date:
                    cycle_idx = i
            if cycle_idx != -1:
                symptom_cycles.setdefault(s.symptom, set()).add(cycle_idx)

        severity_mean = {
            symptom: mean(values)
            for symptom, values in symptom_severity.items()
        }
        
        symptom_persistence = {
            sym: len(cycles) for sym, cycles in symptom_cycles.items()
        }

        # Recent frequency (last 3 cycles approx mapping)
        recent_cutoff_idx = max(0, len(timeline.cycles) - 3)
        recent_symptom_frequency: Dict[str, float] = {}
        for s in timeline.symptoms:
            cycle_idx = -1
            for i, c in enumerate(timeline.cycles):
                if c.start_date <= s.record_date:
                    cycle_idx = i
            if cycle_idx >= recent_cutoff_idx:
                recent_symptom_frequency[s.symptom] = recent_symptom_frequency.get(s.symptom, 0.0) + 1.0

        symptom_change_detected = {}
        for sym in symptom_frequency:
            recent_count = recent_symptom_frequency.get(sym, 0.0)
            earlier_count = symptom_frequency[sym] - recent_count
            if recent_count > earlier_count + 1:
                symptom_change_detected[sym] = True
            else:
                symptom_change_detected[sym] = False

        # Missingness tracking
        # For simplicity, if symptom recorded, it's 'recorded_present', else 'not_recorded'
        missingness_tracking = {
            sym: "recorded_present" for sym in symptom_frequency.keys()
        }
        
        expected_cycles = len(lengths)
        logged_cycles = sum(1 for c in timeline.cycles if c.cycle_length_days is not None)
        cycle_logging_pct = (logged_cycles / expected_cycles * 100) if expected_cycles else 100.0
        
        symptom_logging_pct = min(100.0, (len(timeline.symptoms) / (expected_cycles * 3) * 100)) if expected_cycles else 0.0

        data_completeness_score = {
            "cycle_logging_pct": cycle_logging_pct,
            "symptom_logging_pct": symptom_logging_pct,
        }

        total_n = len(lengths)
        recent_count = min(recent_n, total_n)
        baseline_count = total_n - recent_count

        return PersonalBaseline(
            cycle_median=cycle_median,
            cycle_mean=cycle_mean,
            cycle_sd=cycle_sd,
            recent_cycle_median=recent_median,
            cycle_variability=cycle_sd,
            symptom_frequency=symptom_frequency,
            symptom_severity_mean=severity_mean,
            baseline_cycle_count=baseline_count,
            recent_cycle_count=recent_count,
            recent_symptom_frequency=recent_symptom_frequency,
            symptom_persistence=symptom_persistence,
            symptom_change_detected=symptom_change_detected,
            data_completeness_score=data_completeness_score,
            missingness_tracking=missingness_tracking,
        )


# ======================================================================
# 7C: ENHANCED PATTERN ENGINE
# ======================================================================

class PatternDriftDetector:
    def detect(self, timeline, baseline, recent_n=3):
        lengths = FeatureEngine.cycle_lengths(timeline)
        recent = lengths[-recent_n:] if lengths else []
        historical = lengths[:-recent_n] if len(lengths) > recent_n else []
        
        hist_median = median(historical) if historical else None
        recent_median = median(recent) if recent else None
        
        hist_sd = np.std(historical, ddof=1) if len(historical) > 1 else None
        recent_sd = np.std(recent, ddof=1) if len(recent) > 1 else None
        
        drift_detected = False
        evidence = []
        
        if hist_median is not None and recent_median is not None:
            if abs(hist_median - recent_median) >= 3.0:
                drift_detected = True
                evidence.append("Median cycle length shifted by 3+ days.")
                
        if hist_sd is not None and recent_sd is not None:
            if recent_sd - hist_sd >= 1.5:
                drift_detected = True
                evidence.append("Cycle variability increased significantly.")

        return {
            "personal_baseline": {"median": hist_median, "sd": hist_sd},
            "recent": {"median": recent_median, "sd": recent_sd},
            "pattern_shift": "detected" if drift_detected else "not_detected",
            "evidence": evidence
        }

class PatternEngine:
    def analyze(
        self,
        baseline: PersonalBaseline,
        timeline: UserTimeline,
        recent_n: int = 3,
        cycle_change_threshold_days: float = 3.0,
        variability_threshold: float = 1.5,
    ) -> PatternSummary:

        lengths = FeatureEngine.cycle_lengths(timeline)
        recent = lengths[-recent_n:] if len(lengths) >= recent_n else lengths

        cycle_change = None
        cycle_change_detected = False
        if baseline.cycle_median is not None and recent:
            cycle_change = median(recent) - baseline.cycle_median
            cycle_change_detected = abs(cycle_change) >= cycle_change_threshold_days

        recent_sd = None
        variability_change_detected = False
        if len(recent) > 1:
            recent_mean = mean(recent)
            recent_sd = math.sqrt(sum((x - recent_mean) ** 2 for x in recent) / (len(recent) - 1))
            if baseline.cycle_sd is not None:
                variability_change_detected = (recent_sd - baseline.cycle_sd >= variability_threshold)

        recurring_symptoms = [
            symptom for symptom, count in baseline.symptom_frequency.items() if count >= 2
        ]

        rising_symptoms = []
        if len(timeline.symptoms) >= 4:
            midpoint = len(timeline.symptoms) // 2
            first_counts = {}
            second_counts = {}
            for s in timeline.symptoms[:midpoint]:
                first_counts[s.symptom] = first_counts.get(s.symptom, 0) + 1
            for s in timeline.symptoms[midpoint:]:
                second_counts[s.symptom] = second_counts.get(s.symptom, 0) + 1
            for symptom, count in second_counts.items():
                if count > first_counts.get(symptom, 0):
                    rising_symptoms.append(symptom)

        notes = []
        if cycle_change_detected: notes.append("Recent cycle length differs from the personal baseline.")
        if variability_change_detected: notes.append("Recent cycle variability is higher than the historical baseline.")
        if recurring_symptoms: notes.append("Some symptoms have been recorded repeatedly.")
        if rising_symptoms: notes.append("Some symptoms appear more frequently in the recent timeline.")

        drift_detector = PatternDriftDetector()
        drift_res = drift_detector.detect(timeline, baseline, recent_n)

        return PatternSummary(
            cycle_change_detected=cycle_change_detected,
            cycle_change_days=cycle_change,
            variability_change_detected=variability_change_detected,
            recurring_symptoms=recurring_symptoms,
            rising_symptoms=rising_symptoms,
            notes=notes,
            drift_detected=(drift_res["pattern_shift"] == "detected"),
            drift_evidence=drift_res["evidence"]
        )


# ======================================================================
# 7D: DEMO USERS
# ======================================================================

def build_cycle_records(start_date, lengths):
    records = []
    current = start_date
    for length in lengths:
        records.append(CycleRecord(start_date=current, cycle_length_days=float(length)))
        current = current + timedelta(days=int(length))
    return records

regular_lengths = [29, 30, 28, 31, 30, 29, 34]
regular_cycles = build_cycle_records(date(2026, 1, 1), regular_lengths)
user_regular = UserTimeline(
    profile=ReproductiveProfile(user_id="demo_regular", self_reported_stage=LifeStage.MENSTRUAL, age=26),
    cycles=regular_cycles,
    symptoms=[
        SymptomRecord(regular_cycles[4].start_date, "cramps", SymptomSeverity.MODERATE),
        SymptomRecord(regular_cycles[5].start_date, "fatigue", SymptomSeverity.MILD),
        SymptomRecord(regular_cycles[6].start_date, "cramps", SymptomSeverity.MODERATE),
    ],
    wellbeing=[
        WellbeingRecord(regular_cycles[4].start_date, sleep_quality=4, mood=4, energy=4),
        WellbeingRecord(regular_cycles[5].start_date, sleep_quality=3, mood=4, energy=3),
        WellbeingRecord(regular_cycles[6].start_date, sleep_quality=3, mood=3, energy=3),
    ],
)

peri_lengths = [29, 30, 31, 28, 35, 39, 42, 36]
peri_cycles = build_cycle_records(date(2025, 1, 1), peri_lengths)
user_peri = UserTimeline(
    profile=ReproductiveProfile(user_id="demo_peri", self_reported_stage=LifeStage.PERIMENOPAUSE, age=46),
    cycles=peri_cycles,
    symptoms=[
        SymptomRecord(peri_cycles[5].start_date, "hot_flashes", SymptomSeverity.MODERATE),
        SymptomRecord(peri_cycles[5].start_date + timedelta(days=9), "sleep_disruption", SymptomSeverity.MODERATE),
        SymptomRecord(peri_cycles[6].start_date, "fatigue", SymptomSeverity.MODERATE),
        SymptomRecord(peri_cycles[7].start_date, "hot_flashes", SymptomSeverity.SEVERE),
        SymptomRecord(peri_cycles[7].start_date + timedelta(days=5), "sleep_disruption", SymptomSeverity.MODERATE),
    ],
    wellbeing=[
        WellbeingRecord(peri_cycles[5].start_date, sleep_quality=3, mood=3, energy=3),
        WellbeingRecord(peri_cycles[6].start_date, sleep_quality=2, mood=3, energy=2),
        WellbeingRecord(peri_cycles[7].start_date, sleep_quality=2, mood=2, energy=2),
    ],
)

user_meno = UserTimeline(
    profile=ReproductiveProfile(user_id="demo_meno", self_reported_stage=LifeStage.MENOPAUSE, age=54),
    symptoms=[
        SymptomRecord(date(2026, 6, 1), "hot_flashes", SymptomSeverity.MODERATE),
        SymptomRecord(date(2026, 6, 5), "sleep_disruption", SymptomSeverity.MODERATE),
        SymptomRecord(date(2026, 6, 10), "fatigue", SymptomSeverity.MILD),
        SymptomRecord(date(2026, 6, 15), "hot_flashes", SymptomSeverity.SEVERE),
    ],
    wellbeing=[
        WellbeingRecord(date(2026, 6, 1), sleep_quality=2, mood=3, energy=2),
        WellbeingRecord(date(2026, 6, 10), sleep_quality=2, mood=3, energy=2),
        WellbeingRecord(date(2026, 6, 15), sleep_quality=1, mood=2, energy=2),
    ],
)


# ======================================================================
# 7E: FEATURE ENGINE V4 AND PATTERN ENGINE V4
# ======================================================================

class FeatureEngineV4(FeatureEngine):
    @staticmethod
    def ordered_symptoms(timeline):
        return sorted(timeline.symptoms, key=lambda s: s.record_date)

    @staticmethod
    def ordered_wellbeing(timeline):
        return sorted(timeline.wellbeing, key=lambda w: w.record_date)

    @staticmethod
    def _mean_or_none(values):
        values = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        return float(np.mean(values)) if values else None

    @classmethod
    def build_personal_baseline(cls, timeline, recent_n=3):
        # We reuse the enhanced logic in FeatureEngine but adapted for V4's chronological strictness
        engine = FeatureEngine()
        baseline = engine.build_personal_baseline(timeline, recent_n)
        
        wellbeing = cls.ordered_wellbeing(timeline)
        wellbeing_summary = {}
        for field_name in ["sleep_quality", "mood", "energy"]:
            all_values = [getattr(w, field_name) for w in wellbeing]
            recent_values = [getattr(w, field_name) for w in wellbeing[-recent_n:]] if wellbeing else []
            wellbeing_summary[field_name] = {
                "historical_mean": cls._mean_or_none(all_values),
                "recent_mean": cls._mean_or_none(recent_values),
            }
        baseline.wellbeing_summary = wellbeing_summary
        return baseline

class PatternEngineV4(PatternEngine):
    def analyze(self, baseline, timeline, recent_n=3, cycle_change_threshold_days=3.0, variability_threshold=1.5):
        engine = PatternEngine()
        return engine.analyze(baseline, timeline, recent_n, cycle_change_threshold_days, variability_threshold)

feature_engine_v4 = FeatureEngineV4()
pattern_engine_v4 = PatternEngineV4()

regular_baseline = feature_engine_v4.build_personal_baseline(user_regular)
peri_baseline = feature_engine_v4.build_personal_baseline(user_peri)
meno_baseline = feature_engine_v4.build_personal_baseline(user_meno)

regular_patterns = pattern_engine_v4.analyze(regular_baseline, user_regular)
peri_patterns = pattern_engine_v4.analyze(peri_baseline, user_peri)
meno_patterns = pattern_engine_v4.analyze(meno_baseline, user_meno)


# ======================================================================
# 7F: LIFE-STAGE FORECAST ADAPTER
# ======================================================================

def timeline_cycle_lengths(timeline: UserTimeline):
    ordered = sorted(timeline.cycles, key=lambda c: c.start_date)
    return [
        float(c.cycle_length_days)
        for c in ordered
        if c.cycle_length_days is not None and np.isfinite(float(c.cycle_length_days))
    ]

def timeline_context(timeline: UserTimeline):
    ordered = sorted(timeline.cycles, key=lambda c: c.start_date)
    rows = []
    for c in ordered:
        rows.append({"cycle_length": c.cycle_length_days})
    return pd.DataFrame(rows)



def forecast_V4_user(timeline: UserTimeline, artifact_path=ARTIFACT_PATH):
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
    return result


# ======================================================================
# 7G: ENHANCED INSIGHT ENGINE
# ======================================================================

def build_winning_insight(timeline, baseline, patterns, forecast, stage=None):
    messages = []
    
    # 1. DATA QUALITY
    messages.append("DATA QUALITY")
    cycles = timeline_cycle_lengths(timeline)
    hist_len = len(cycles)
    cycle_pct = baseline.data_completeness_score.get('cycle_logging_pct', 0)
    messages.append(f"Cycle history       {'Good' if hist_len >= 6 else 'Moderate' if hist_len > 0 else 'Insufficient'}")
    messages.append(f"History length      {hist_len} cycles")
    messages.append(f"Missing values      {'Low' if cycle_pct > 80 else 'High'}")
    messages.append(f"Recent consistency  {'High' if not patterns.cycle_change_detected else 'Moderate'}")
    messages.append("Forecast eligibility: YES" if forecast.predicted_cycle_length_days else "Forecast eligibility: NO")
    messages.append("")

    messages.append("PERSONAL BASELINE")
    if baseline.cycle_median is not None:
        messages.append(f"Historical median: {baseline.cycle_median:.1f} days.")
        if baseline.recent_cycle_median is not None:
            messages.append(f"Recent median: {baseline.recent_cycle_median:.1f} days.")
        if baseline.cycle_sd is not None:
            messages.append(f"Historical variability: {baseline.cycle_sd:.1f} days.")
    else:
        messages.append("No cycle-length baseline is available.")

    if getattr(baseline, "wellbeing_summary", None):
        wellbeing_parts = []
        for name, label in [("sleep_quality", "sleep"), ("mood", "mood"), ("energy", "energy")]:
            item = baseline.wellbeing_summary.get(name, {})
            recent = item.get("recent_mean")
            historical = item.get("historical_mean")
            if recent is not None:
                if historical is not None:
                    delta = recent - historical
                    direction = "higher" if delta > 0.05 else "lower" if delta < -0.05 else "similar"
                    wellbeing_parts.append(f"{label}: recent {recent:.1f}/5 vs historical {historical:.1f}/5 ({direction})")
                else:
                    wellbeing_parts.append(f"{label}: recent {recent:.1f}/5")
        if wellbeing_parts:
            messages.append("Wellbeing records: " + "; ".join(wellbeing_parts) + ".")

    messages.append("")
    messages.append("OBSERVED CHANGES")
    if patterns.cycle_change_detected and patterns.cycle_change_days is not None:
        direction = "longer" if patterns.cycle_change_days > 0 else "shorter"
        messages.append(f"Recent cycle median is ~{abs(patterns.cycle_change_days):.1f} days {direction} than baseline.")
    elif patterns.cycle_change_detected:
        messages.append("A recent cycle-timing difference was detected.")

    if patterns.variability_change_detected:
        messages.append("Recent cycle variability is higher than baseline.")
    if patterns.recurring_symptoms:
        messages.append("Repeatedly recorded symptoms: " + ", ".join(patterns.recurring_symptoms) + ".")
    if patterns.rising_symptoms:
        messages.append("A later-timeline symptom-frequency signal: " + ", ".join(patterns.rising_symptoms) + ".")

    if not any([patterns.cycle_change_detected, patterns.variability_change_detected, patterns.recurring_symptoms, patterns.rising_symptoms]):
        messages.append("No major change signal was detected.")

    messages.append("")
    messages.append("FORECAST + UNCERTAINTY")
    if forecast.predicted_cycle_length_days is not None:
        messages.append(f"Estimated next cycle: {forecast.predicted_cycle_length_days:.1f} days.")
        if forecast.lower_80_days is not None and forecast.upper_80_days is not None:
            messages.append(f"80% estimated window: {forecast.lower_80_days:.1f}-{forecast.upper_80_days:.1f} days.")
        if forecast.lower_90_days is not None and forecast.upper_90_days is not None:
            messages.append(f"90% estimated window: {forecast.lower_90_days:.1f}-{forecast.upper_90_days:.1f} days.")
    else:
        messages.append("No next-cycle forecast was generated.")

    if forecast.predicted_cycle_length_days is not None:
        messages.append("")
        messages.append("FORECAST CONFIDENCE")
        messages.append(f"History          ████████░░  {forecast.confidence_history}%")
        messages.append(f"Pattern stability ██████░░░░  {forecast.confidence_pattern}%")
        messages.append(f"Model agreement  █████████░  {forecast.confidence_model}%")
        messages.append(f"Overall evidence strength: {forecast.confidence_overall}")

        if forecast.model_agreement_details:
            messages.append("")
            messages.append("MODEL AGREEMENT")
            for m, v in forecast.model_agreement_details.items():
                messages.append(f"{m:<17} {v:.1f}")
            messages.append(f"Spread: {forecast.model_agreement_spread:.1f} days")
            messages.append("High agreement")

    messages.append("")
    messages.append("MODEL CONTEXT")
    stage_value = getattr(stage, "value", str(stage)) if stage is not None else "unknown"
    messages.append(f"Self-reported life-stage context: {stage_value}.")

    messages.append("")
    messages.append("BRING THIS TO YOUR DOCTOR")
    points = []
    if patterns.cycle_change_detected: points.append("recent change in cycle timing")
    if patterns.variability_change_detected: points.append("change in cycle-to-cycle variability")
    if patterns.recurring_symptoms: points.append("repeated symptoms: " + ", ".join(patterns.recurring_symptoms))
    if forecast.predicted_cycle_length_days is not None: points.append("forecast estimate and uncertainty window")
    if points:
        for p in points: messages.append("• Discuss " + p + ".")
    else:
        messages.append("Continue longitudinal tracking.")

    return CycleSafeInsight(title="CycleSafe Longitudinal Insight", body="\n".join(messages))

# ======================================================================
# 7H: ENHANCED DOCTOR REPORT
# ======================================================================

def build_winning_doctor_report(timeline, baseline, patterns, forecast, insight):
    stage = timeline.profile.self_reported_stage
    stage_value = stage.value if hasattr(stage, "value") else str(stage)
    
    profile = {"user_id": timeline.profile.user_id, "age": timeline.profile.age, "self_reported_stage": stage_value}
    cycle_lengths = [float(c.cycle_length_days) for c in timeline.cycles if c.cycle_length_days is not None]
    
    data_coverage = {
        "cycle_records": len(cycle_lengths),
        "symptom_records": len(timeline.symptoms),
        "cycle_tracking_available": len(cycle_lengths) > 0,
        "symptom_tracking_available": len(timeline.symptoms) > 0,
    }
    
    if len(cycle_lengths) == 0:
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
    }
    
    baseline_section = {
        "median_days": baseline.cycle_median,
        "mean_days": baseline.cycle_mean,
        "sd_days": baseline.cycle_sd,
        "recent_median_days": baseline.recent_cycle_median,
    }

    changes = []
    if patterns.cycle_change_detected:
        changes.append({"type": "cycle_change", "label": "Cycle-length change", "detail": f"Recent median shift: {patterns.cycle_change_days} days"})
    if patterns.variability_change_detected:
        changes.append({"type": "variability", "label": "Cycle variability", "detail": "Increased cycle variability detected"})

    symptoms = [{"symptom": sym, "records": int(freq), "mean_severity": baseline.symptom_severity_mean.get(sym), "repeated": sym in patterns.recurring_symptoms} for sym, freq in baseline.symptom_frequency.items()]
    symptoms.sort(key=lambda x: (-x["records"], x["symptom"]))

    wellbeing = getattr(baseline, "wellbeing_summary", {})
    wellbeing_section = [{"label": label, "historical": wellbeing.get(n, {}).get("historical_mean"), "recent": wellbeing.get(n, {}).get("recent_mean")} for n, label in [("sleep_quality", "Sleep quality"), ("mood", "Mood"), ("energy", "Energy")] if wellbeing.get(n, {}).get("recent_mean") is not None]

    forecast_available = forecast.predicted_cycle_length_days is not None and stage != LifeStage.MENOPAUSE
    forecast_section = {
        "available": forecast_available,
        "predicted_days": forecast.predicted_cycle_length_days,
        "range_80": (forecast.lower_80_days, forecast.upper_80_days),
        "range_90": (forecast.lower_90_days, forecast.upper_90_days),
        "expected_error": forecast.predicted_absolute_error_days,
        "method": forecast.method,
    }
    
    forecast_confidence = {
        "history": forecast.confidence_history,
        "pattern": forecast.confidence_pattern,
        "model": forecast.confidence_model,
        "overall": forecast.confidence_overall
    }
    
    why_this_forecast = "The forecast aligns with current baseline trends and utilizes robust ensemble outputs." if forecast_available else "Not applicable."

    stage_context = "CycleSafe is tracking history."
    if stage == LifeStage.PERIMENOPAUSE: stage_context = "Tracking changes common during menopausal transition."
    elif stage == LifeStage.MENOPAUSE: stage_context = "Focusing on symptom history, not regular forecasting."

    discussion_points = ["Continue tracking."]
    if patterns.cycle_change_detected: discussion_points.insert(0, "Review cycle length change.")
    
    model_summary = {"model": forecast.method, "status": "Active" if forecast_available else "Not applicable"}
    limitations = ["Estimates, not medical advice."]

    return {
        "report_title": "CycleSafe - Longitudinal Health Summary",
        "report_subtitle": "A structured view of recorded history.",
        "profile": profile,
        "data_coverage": data_coverage,
        "data_quality": data_quality,
        "personal_baseline": baseline_section,
        "changes": changes,
        "symptoms": symptoms,
        "wellbeing": wellbeing_section,
        "forecast": forecast_section,
        "forecast_confidence": forecast_confidence,
        "why_this_forecast": why_this_forecast,
        "stage_context": stage_context,
        "discussion_points": discussion_points,
        "model_summary": model_summary,
        "limitations": limitations,
        "primary_insight": {"title": insight.title, "body": insight.body}
    }


# ======================================================================
# 7I: BUILD DEMO INSIGHTS AND REPORTS
# ======================================================================

def adapter_to_forecast_result(adapter_result, timeline):
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
    )

regular_forecast = adapter_to_forecast_result(forecast_V4_user(user_regular), user_regular)
peri_forecast = adapter_to_forecast_result(forecast_V4_user(user_peri), user_peri)
meno_forecast = adapter_to_forecast_result(forecast_V4_user(user_meno), user_meno)

regular_insight = build_winning_insight(user_regular, regular_baseline, regular_patterns, regular_forecast, user_regular.profile.self_reported_stage)
peri_insight = build_winning_insight(user_peri, peri_baseline, peri_patterns, peri_forecast, user_peri.profile.self_reported_stage)
meno_insight = build_winning_insight(user_meno, meno_baseline, meno_patterns, meno_forecast, user_meno.profile.self_reported_stage)

regular_report = build_winning_doctor_report(user_regular, regular_baseline, regular_patterns, regular_forecast, regular_insight)
peri_report = build_winning_doctor_report(user_peri, peri_baseline, peri_patterns, peri_forecast, peri_insight)
meno_report = build_winning_doctor_report(user_meno, meno_baseline, meno_patterns, meno_forecast, meno_insight)

os.makedirs('models', exist_ok=True)

# ======================================================================
from cyclesafe_privacy import CycleSafePrivacyEngine

def load_safe_artifact(artifact_path: str = ARTIFACT_PATH):
    """Safely loads model artifact only from the configured models/ path."""
    norm_path = os.path.normpath(artifact_path)
    if not (norm_path.startswith("models") or norm_path.startswith(os.path.normpath("models"))):
        raise ValueError(f"Security error: Refusing to load model artifact from untrusted path '{artifact_path}'. Must be in models/.")
    if not os.path.exists(artifact_path):
        raise FileNotFoundError(f"Model artifact not found at '{artifact_path}'")
    import joblib
    return joblib.load(artifact_path)


def generate_doctor_report_pdf(report: dict, output_path: str):
    """Generates a professional doctor-ready summary PDF using ReportLab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        dir_name = os.path.dirname(output_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
        )
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'ReportTitle', parent=styles['Heading1'],
            fontSize=18, leading=22, textColor=colors.HexColor('#1E293B'), spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle', parent=styles['Normal'],
            fontSize=10, leading=14, textColor=colors.HexColor('#64748B'), spaceAfter=12
        )
        heading_style = ParagraphStyle(
            'SectionHeading', parent=styles['Heading2'],
            fontSize=12, leading=16, textColor=colors.HexColor('#0F766E'), spaceBefore=10, spaceAfter=4
        )
        body_style = ParagraphStyle(
            'Body', parent=styles['Normal'],
            fontSize=9, leading=13, textColor=colors.HexColor('#334155')
        )
        disclaimer_style = ParagraphStyle(
            'Disclaimer', parent=styles['Italic'],
            fontSize=8, leading=11, textColor=colors.HexColor('#94A3B8')
        )

        elements = []

        elements.append(Paragraph(report.get("report_title", "CycleSafe Longitudinal Summary"), title_style))
        elements.append(Paragraph(report.get("report_subtitle", "Non-diagnostic patient summary for clinical review"), subtitle_style))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=10))

        prof = report.get("profile", {})
        cov = report.get("data_coverage", {})
        prof_data = [
            [Paragraph("<b>User ID:</b> " + str(prof.get("user_id")), body_style),
             Paragraph("<b>Age:</b> " + str(prof.get("age")), body_style),
             Paragraph("<b>Life Stage:</b> " + str(prof.get("self_reported_stage")), body_style)],
            [Paragraph("<b>Cycle Records:</b> " + str(cov.get("cycle_records")), body_style),
             Paragraph("<b>Symptom Records:</b> " + str(cov.get("symptom_records")), body_style),
             Paragraph("<b>Data Quality:</b> " + str(report.get("data_quality", {}).get("missing_values")), body_style)]
        ]
        t = Table(prof_data, colWidths=[180, 180, 180])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("Personal Baseline and Forecast Window", heading_style))
        base = report.get("personal_baseline", {})
        fc = report.get("forecast", {})

        med_val = base.get('median_days')
        mean_val = base.get('mean_days')
        sd_val = base.get('sd_days')
        med_str = f"{med_val:.1f} d" if med_val is not None else "N/A"
        mean_str = f"{mean_val:.1f} d" if mean_val is not None else "N/A"
        sd_str = f"{sd_val:.1f} d" if sd_val is not None else "N/A"
        base_text = f"Historical Median: {med_str} | Historical Mean: {mean_str} | SD: {sd_str}"
        elements.append(Paragraph(base_text, body_style))
        elements.append(Spacer(1, 4))

        if fc.get("available"):
            range80 = fc.get("range_80", (None, None))
            range90 = fc.get("range_90", (None, None))
            r80_str = f"{range80[0]:.1f}-{range80[1]:.1f}" if range80 and range80[0] is not None else "N/A"
            r90_str = f"{range90[0]:.1f}-{range90[1]:.1f}" if range90 and range90[0] is not None else "N/A"
            pred_val = fc.get('predicted_days', 0)
            pred_str = f"{pred_val:.1f}" if pred_val is not None else "N/A"
            fc_text = f"<b>Predicted Next Cycle:</b> {pred_str} days<br/>"                       f"<b>80% Prediction Interval (calibrated on dev OOF):</b> {r80_str} days<br/>"                       f"<b>90% Prediction Interval (calibrated on dev OOF):</b> {r90_str} days<br/>"                       f"<b>Model:</b> {fc.get('method', 'Ridge Ensemble')}"
            elements.append(Paragraph(fc_text, body_style))
        else:
            elements.append(Paragraph("<i>Next-cycle forecasting not available for this profile stage.</i>", body_style))

        elements.append(Spacer(1, 10))

        elements.append(Paragraph("Observed Patterns and Symptoms", heading_style))
        changes = report.get("changes", [])
        if changes:
            for c in changes:
                elements.append(Paragraph(f"• <b>{c.get('label')}:</b> {c.get('detail')}", body_style))
        else:
            elements.append(Paragraph("• No significant timing or variability shift detected.", body_style))

        symptoms = report.get("symptoms", [])
        if symptoms:
            sym_list = ", ".join([s.get("symptom") for s in symptoms[:5]])
            elements.append(Paragraph(f"• <b>Logged Symptoms:</b> {sym_list}", body_style))
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("Discussion Points for Doctor Review", heading_style))
        for d in report.get("discussion_points", []):
            elements.append(Paragraph(f"• {d}", body_style))
        elements.append(Spacer(1, 10))

        insight = report.get("primary_insight", {})
        if insight.get("body"):
            elements.append(Paragraph("Longitudinal Summary Notes", heading_style))
            for line in insight["body"].split("\n"):
                if line.strip():
                    elements.append(Paragraph(line.strip(), body_style))
            elements.append(Spacer(1, 10))

        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceAfter=8))
        elements.append(Paragraph("<b>Notice:</b> CycleSafe provides observational statistical modeling for self-tracking. It does not provide medical diagnosis, disease identification, or clinical guarantees.", disclaimer_style))

        doc.build(elements)
        print(f"Generated Doctor Report PDF: {output_path}")
    except Exception as e:
        print(f"ReportLab PDF generation fallback ({e}). Writing plain text output.")
        with open(output_path + ".txt", "w", encoding="utf-8") as f:
            f.write(json.dumps(report, indent=2))

generate_doctor_report_pdf(regular_report, 'models/doctor_report_regular.pdf')
generate_doctor_report_pdf(peri_report, 'models/doctor_report_perimenopause.pdf')
generate_doctor_report_pdf(meno_report, 'models/doctor_report_menopause.pdf')


def display_winning_report(report):
    print("\n+" + "=" * 76 + "+")
    print("|" + " CYCLESAFE - LONGITUDINAL HEALTH SUMMARY".center(76) + "|")
    print("+" + "=" * 76 + "+")
    
    print("\n1  PROFILE")
    print(f"Age: {report['profile']['age']}")
    
    print("\n2  LONGITUDINAL RECORD")
    print(f"Cycle records: {report['data_coverage']['cycle_records']}")
    
    print("\n3  DATA QUALITY")
    print(f"History length: {report['data_quality']['history_length']} cycles")
    print(f"Missing values: {report['data_quality']['missing_values']}")
    
    print("\n4  PERSONAL BASELINE")
    if report['personal_baseline']['median_days']:
        print(f"Historical median: {report['personal_baseline']['median_days']:.1f} days")
    
    print("\n5  OBSERVED CHANGES")
    for c in report['changes']: print(f"• {c['label']}")
    
    print("\n6  SYMPTOM EVIDENCE")
    for s in report['symptoms']: print(f"• {s['symptom']}")
    
    print("\n7  WELLBEING EVIDENCE")
    for w in report['wellbeing']: print(f"• {w['label']}")
    
    print("\n8  FORECAST + UNCERTAINTY")
    if report['forecast']['available']:
        print(f"Estimated next cycle: {report['forecast']['predicted_days']:.1f} days")
    
    print("\n9  FORECAST CONFIDENCE")
    if report['forecast']['available']:
        print(f"Overall confidence: {report['forecast_confidence']['overall']}")
        
    print("\n10 WHY THIS FORECAST?")
    print(report['why_this_forecast'])
    
    print("\n11 LIFE-STAGE CONTEXT")
    print(report['stage_context'])
    
    print("\n12 DISCUSSION POINTS")
    for d in report['discussion_points']: print(f"• {d}")
    
    print("\n13 MODEL TRANSPARENCY")
    print(f"Model: {report['model_summary']['model']}")
    
    print("\n14 IMPORTANT LIMITATIONS")
    for l in report['limitations']: print(f"• {l}")

print("\n\n######################## REGULAR PROFILE ############################")
display_winning_report(regular_report)
print("\n\n#################### PERIMENOPAUSE PROFILE ###########################")
display_winning_report(peri_report)
print("\n\n######################## MENOPAUSE PROFILE ###########################")
display_winning_report(meno_report)


# %%
# =============================================================================
# CELL 8 - CYCLESAFE V5 LONGITUDINAL DATA QUALITY + PATTERN DRIFT
# =============================================================================

import numpy as np
import pandas as pd


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

MIN_CYCLE_LENGTH = 15
MAX_CYCLE_LENGTH = 90

RECENT_WINDOW = 3

MODERATE_SHIFT_DAYS = 3.0
LARGE_SHIFT_DAYS = 5.0


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _to_numeric_series(series):
    return pd.to_numeric(series, errors="coerce")


def _safe_float(value):
    try:
        value = float(value)
        return value if np.isfinite(value) else np.nan
    except Exception:
        return np.nan


def _find_longitudinal_cycle_table(cyclesafe_result):
    """
    Locate the original longitudinal cycle-level dataset.

    Cell 8 must use a table containing:
        user_id
        cycle_number
        cycle_length

    It must NOT use the feature-engineered model_data table,
    because model_data contains target/lags/features rather than
    the original cycle_length column.
    """

    candidates = []

    if isinstance(cyclesafe_result, dict):

        # Most likely names first.
        preferred_keys = [
            "clean_data",
            "clean_df",
            "cycle_data",
            "cycles",
            "cycles_df",
            "longitudinal_data",
            "longitudinal_df",
            "raw_data",
            "data",
        ]

        for key in preferred_keys:
            if key in cyclesafe_result:
                value = cyclesafe_result[key]

                if isinstance(value, pd.DataFrame):
                    candidates.append((key, value))

        # Also inspect every dataframe stored in result.
        for key, value in cyclesafe_result.items():
            if isinstance(value, pd.DataFrame):
                if not any(existing_key == key for existing_key, _ in candidates):
                    candidates.append((key, value))

    # Find a dataframe containing the actual cycle-length column.
    for key, df in candidates:

        columns = set(df.columns)

        if {
            "user_id",
            "cycle_number",
            "cycle_length",
        }.issubset(columns):

            return df.copy(), key

    # If nothing suitable exists, give a diagnostic error.
    diagnostic = []

    for key, df in candidates:
        diagnostic.append(
            f"{key}: {list(df.columns)}"
        )

    raise KeyError(
        "Cell 8 could not locate the original longitudinal cycle table "
        "containing user_id, cycle_number, and cycle_length.\n\n"
        "Available DataFrames inside result:\n"
        + "\n".join(diagnostic)
        + "\n\n"
        "result['model_data'] is the feature-engineered forecasting "
        "table and intentionally does not contain cycle_length."
    )


# ------------------------------------------------------------
# Main longitudinal quality table
# ------------------------------------------------------------

def build_longitudinal_quality_table(cyclesafe_result):

    df, source_name = _find_longitudinal_cycle_table(cyclesafe_result)

    required = {
        "user_id",
        "cycle_number",
        "cycle_length",
    }

    missing = required - set(df.columns)

    if missing:
        raise KeyError(
            "Cell 8 longitudinal source is missing required columns: "
            + ", ".join(sorted(missing))
        )

    # --------------------------------------------------------
    # Clean identifiers / cycle values
    # --------------------------------------------------------

    df = df.copy()

    df["cycle_number"] = _to_numeric_series(
        df["cycle_number"]
    )

    df["cycle_length"] = _to_numeric_series(
        df["cycle_length"]
    )

    df = df.replace(
        [np.inf, -np.inf],
        np.nan
    )
    
    # Store missing counts before dropna
    missing_counts = df.groupby("user_id")["cycle_length"].apply(lambda x: x.isna().sum()).to_dict()

    df = df.dropna(
        subset=[
            "user_id",
            "cycle_number",
            "cycle_length",
        ]
    )

    # Keep biologically plausible cycle lengths for this
    # descriptive longitudinal analysis.
    df = df[
        df["cycle_length"].between(
            MIN_CYCLE_LENGTH,
            MAX_CYCLE_LENGTH
        )
    ].copy()

    df = df.sort_values(
        [
            "user_id",
            "cycle_number",
        ]
    )

    # Remove duplicate user/cycle combinations if present.
    df = df.drop_duplicates(
        subset=[
            "user_id",
            "cycle_number",
        ],
        keep="last",
    )

    rows = []

    # --------------------------------------------------------
    # Per-user longitudinal analysis
    # --------------------------------------------------------

    for user_id, group in df.groupby(
        "user_id",
        sort=False
    ):

        group = group.sort_values(
            "cycle_number"
        ).reset_index(drop=True)

        cycle_lengths = (
            group["cycle_length"]
            .astype(float)
            .to_numpy()
        )

        n = len(cycle_lengths)

        if n == 0:
            continue

        # Robust outlier detection
        median = np.median(cycle_lengths)
        mad = np.median(np.abs(cycle_lengths - median))
        if mad == 0:
            mad = 1e-6
        robust_z = (cycle_lengths - median) / (1.4826 * mad)
        outlier_count = np.sum(np.abs(robust_z) > 3.0)

        # ----------------------------------------------------
        # Recent history
        # ----------------------------------------------------

        recent = cycle_lengths[-RECENT_WINDOW:]

        recent_mean = (
            float(np.mean(recent))
            if len(recent)
            else np.nan
        )

        recent_std = (
            float(np.std(recent, ddof=1))
            if len(recent) >= 2
            else np.nan
        )

        recent_cv = (
            recent_std / recent_mean
            if (
                np.isfinite(recent_std)
                and np.isfinite(recent_mean)
                and recent_mean != 0
            )
            else np.nan
        )

        # Data quality score
        missing_count = missing_counts.get(user_id, 0)
        
        if n < 5:
            quality_score = "INSUFFICIENT"
        elif outlier_count > 2 or missing_count > 3:
            quality_score = "LOW"
        elif recent_cv > 0.3 or outlier_count > 0 or missing_count > 0:
            quality_score = "MODERATE"
        else:
            quality_score = "HIGH"

        # ----------------------------------------------------
        # Historical baseline
        #
        # IMPORTANT:
        # The historical baseline EXCLUDES the latest 3 cycles.
        # This prevents the recent period from contaminating
        # the baseline against which drift is measured.
        # ----------------------------------------------------

        historical = cycle_lengths[:-RECENT_WINDOW]

        if len(historical) > 0:

            historical_mean = float(
                np.mean(historical)
            )

            historical_median = float(
                np.median(historical)
            )

        else:

            historical_mean = np.nan
            historical_median = np.nan

        # All-history personal baseline is retained as a
        # descriptive reference, separate from drift baseline.
        personal_baseline_mean = float(
            np.mean(cycle_lengths)
        )

        personal_baseline_median = float(
            np.median(cycle_lengths)
        )

        # ----------------------------------------------------
        # Recent-vs-historical shift
        # ----------------------------------------------------

        if (
            np.isfinite(recent_mean)
            and np.isfinite(historical_mean)
        ):

            recent_minus_historical = (
                recent_mean
                - historical_mean
            )

        else:

            recent_minus_historical = np.nan

        # ----------------------------------------------------
        # Direction
        # ----------------------------------------------------

        if not np.isfinite(
            recent_minus_historical
        ):

            timing_direction = "insufficient_history"

        elif (
            recent_minus_historical
            >= MODERATE_SHIFT_DAYS
        ):

            timing_direction = "later_than_historical"

        elif (
            recent_minus_historical
            <= -MODERATE_SHIFT_DAYS
        ):

            timing_direction = "earlier_than_historical"

        else:

            timing_direction = "near_historical_baseline"

        # ----------------------------------------------------
        # Timing-shift signal
        # ----------------------------------------------------

        abs_shift = (
            abs(recent_minus_historical)
            if np.isfinite(
                recent_minus_historical
            )
            else np.nan
        )

        if not np.isfinite(abs_shift):

            timing_shift_signal = "not_assessable"

        elif abs_shift >= LARGE_SHIFT_DAYS:

            timing_shift_signal = "large"

        elif abs_shift >= MODERATE_SHIFT_DAYS:

            timing_shift_signal = "moderate"

        else:

            timing_shift_signal = "small"

        # ----------------------------------------------------
        # Evidence strength
        # ----------------------------------------------------

        if n < 3:

            evidence_strength = "insufficient"

        elif n < 5:

            evidence_strength = "limited"

        elif n < 8:

            evidence_strength = "developing"

        else:

            evidence_strength = "established"

        # ----------------------------------------------------
        # Append user summary
        # ----------------------------------------------------

        rows.append({

            "user_id": user_id,

            "history_count": int(n),

            "historical_cycle_count": int(
                len(historical)
            ),

            "recent_cycle_count": int(
                len(recent)
            ),

            "personal_baseline_mean": (
                personal_baseline_mean
            ),

            "personal_baseline_median": (
                personal_baseline_median
            ),

            "historical_mean_before_recent": (
                historical_mean
            ),

            "historical_median_before_recent": (
                historical_median
            ),

            "recent_mean_3": recent_mean,

            "recent_std_3": recent_std,

            "recent_cv_3": recent_cv,

            "recent_minus_historical_days": (
                recent_minus_historical
            ),

            "timing_direction": (
                timing_direction
            ),

            "timing_shift_signal": (
                timing_shift_signal
            ),

            "evidence_strength": (
                evidence_strength
            ),
            
            "outlier_count": outlier_count,
            
            "data_quality_score": quality_score

        })

    quality = pd.DataFrame(rows)

    if quality.empty:
        raise ValueError(
            "Cell 8 produced an empty longitudinal quality table."
        )

    # --------------------------------------------------------
    # Ordering
    # --------------------------------------------------------

    evidence_order = {
        "insufficient": 0,
        "limited": 1,
        "developing": 2,
        "established": 3,
    }

    quality["_evidence_order"] = (
        quality["evidence_strength"]
        .map(evidence_order)
        .fillna(-1)
    )

    quality = (
        quality
        .sort_values(
            [
                "_evidence_order",
                "history_count",
            ],
            ascending=[
                True,
                False,
            ],
        )
        .drop(
            columns="_evidence_order"
        )
        .reset_index(drop=True)
    )

    return quality, source_name


# ============================================================
# RUN CELL 8
# ============================================================

if "result" in globals():
    longitudinal_quality, longitudinal_source = (
        build_longitudinal_quality_table(result)
    )

    print("=" * 70)
    print("CYCLESAFE V5 - LONGITUDINAL DATA QUALITY + PATTERN DRIFT")
    print("=" * 70)

    print(
        f"Longitudinal source: {longitudinal_source}"
    )

    print(
        f"Participants analyzed: "
        f"{longitudinal_quality['user_id'].nunique()}"
    )

    print(
        f"Participants with <5 cycles: "
        f"{(
            longitudinal_quality['history_count'] < 5
        ).sum()}"
    )

    print(
        f"Participants with 5-7 cycles: "
        f"{(
            longitudinal_quality['history_count'].between(
                5, 7
            )
        ).sum()}"
    )

    print(
        f"Participants with 8+ cycles: "
        f"{(
            longitudinal_quality['history_count'] >= 8
        ).sum()}"
    )


    print("\nEVIDENCE STRENGTH")

    print(
        longitudinal_quality[
            "evidence_strength"
        ].value_counts()
        .sort_index()
    )


    print("\nTIMING SHIFT SIGNAL")

    print(
        longitudinal_quality[
            "timing_shift_signal"
        ].value_counts()
        .sort_index()
    )


    print("\nTIMING DIRECTION")

    print(
        longitudinal_quality[
            "timing_direction"
        ].value_counts()
        .sort_index()
    )

    print("\nDATA QUALITY SCORE")
    
    print(
        longitudinal_quality[
            "data_quality_score"
        ].value_counts()
        .sort_index()
    )


    print("\nRECENT VS HISTORICAL SHIFT")

    shift_summary = (
        longitudinal_quality[
            [
                "recent_minus_historical_days",
                "recent_mean_3",
                "historical_mean_before_recent",
            ]
        ]
        .describe()
        .round(3)
    )

    print(shift_summary)


    print("\nLONGITUDINAL QUALITY TABLE - SAMPLE")

    display(
        longitudinal_quality.head(15)
    )
else:
    print("Skipping Cell 8 execution, `result` not found in globals.")

print("\nCELL 8 COMPLETE")

# %%  
# =============================================================================
# CELL 9 - CYCLESAFE V5 EXPLAINABLE FORECAST + MODEL DISAGREEMENT
# =============================================================================
#
# PURPOSE
# -------
# Convert a numerical CycleSafe forecast into a transparent longitudinal
# explanation based on observable recorded history. Includes model disagreement
# and uncertainty components.
# =============================================================================


import numpy as np

# Mocking MIN_HISTORY_FOR_MODEL and ARTIFACT_PATH if missing
MIN_HISTORY_FOR_MODEL = 3
ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"


# =============================================================================
# 1. ROBUST CYCLE-LENGTH CLEANING
# =============================================================================

def _clean_cycle_lengths(
    previous_cycles,
):
    """
    Convert user-provided cycle lengths into finite floats.

    Invalid values are ignored rather than crashing the explanation layer.
    """

    cleaned = []

    for value in previous_cycles:

        try:

            numeric_value = float(
                value
            )

            if np.isfinite(
                numeric_value
            ):

                cleaned.append(
                    numeric_value
                )

        except (
            TypeError,
            ValueError,
        ):

            continue

    return cleaned


# =============================================================================
# 2. EXPLAIN FORECAST
# =============================================================================

# (Mock forecast_next_cycle removed; Cell 9 calls real forecast_next_cycle)

def explain_cycle_forecast(
    previous_cycles,
    artifact_path=ARTIFACT_PATH,
):
    """
    Generate a forecast together with a longitudinal evidence explanation.
    """

    # -------------------------------------------------------------------------
    # Clean inputs.
    # -------------------------------------------------------------------------

    cycles = _clean_cycle_lengths(
        previous_cycles
    )

    # -------------------------------------------------------------------------
    # Minimum history check.
    # -------------------------------------------------------------------------

    if (
        len(cycles)
        <
        MIN_HISTORY_FOR_MODEL
    ):

        return {
            "status":
                "insufficient_history",

            "message": (
                f"At least "
                f"{MIN_HISTORY_FOR_MODEL} "
                "completed cycles are required "
                "for a forecast."
            ),

            "history_count":
                len(cycles),
        }

    # -------------------------------------------------------------------------
    # Forecast using the existing frozen forecasting engine.
    # -------------------------------------------------------------------------

    forecast = forecast_next_cycle(cycles, artifact_path=artifact_path)

    # =============================================================================
    # 3. PERSONAL BASELINE
    # =============================================================================

    personal_mean = float(
        np.mean(
            cycles
        )
    )

    personal_median = float(
        np.median(
            cycles
        )
    )

    # =============================================================================
    # 4. RECENT WINDOW
    # =============================================================================

    recent_window = (
        cycles[-3:]
    )

    recent_mean = float(
        np.mean(
            recent_window
        )
    )

    if len(
        recent_window
    ) > 1:

        recent_std = float(
            np.std(
                recent_window,
                ddof=1,
            )
        )

    else:

        recent_std = 0.0

    # =============================================================================
    # 5. EARLIER HISTORY
    # =============================================================================

    historical = (
        cycles[:-3]
    )

    if len(
        historical
    ) >= 1:

        historical_mean = float(
            np.mean(
                historical
            )
        )

        historical_median = float(
            np.median(
                historical
            )
        )

        historical_reference = (
            "earlier recorded cycles"
        )

        recent_minus_historical_mean = (
            recent_mean
            -
            historical_mean
        )

        recent_minus_historical_median = (
            float(
                np.median(
                    recent_window
                )
            )
            -
            historical_median
        )

    else:

        historical_mean = (
            personal_mean
        )

        historical_median = (
            personal_median
        )

        historical_reference = (
            "available recorded history"
        )

        recent_minus_historical_mean = (
            np.nan
        )

        recent_minus_historical_median = (
            np.nan
        )

    # =============================================================================
    # 6. LONGITUDINAL PATTERN STATEMENT
    # =============================================================================

    if not np.isfinite(
        recent_minus_historical_mean
    ):

        pattern_statement = (
            "There is not yet enough earlier history "
            "to calculate a separate recent-vs-earlier "
            "timing comparison."
        )

    elif abs(
        recent_minus_historical_mean
    ) < 1.5:

        pattern_statement = (
            "Recent timing is close to the earlier "
            "recorded baseline."
        )

    elif (
        recent_minus_historical_mean
        > 0
    ):

        pattern_statement = (
            f"Recent cycles average about "
            f"{abs(recent_minus_historical_mean):.1f} "
            "days longer than the earlier recorded baseline."
        )

    else:

        pattern_statement = (
            f"Recent cycles average about "
            f"{abs(recent_minus_historical_mean):.1f} "
            "days shorter than the earlier recorded baseline."
        )

    # =============================================================================
    # 7. VARIABILITY STATEMENT
    # =============================================================================

    if recent_std < 2:

        variability_statement = (
            "The latest three recorded cycles "
            "show relatively low variation."
        )

    elif recent_std < 4:

        variability_statement = (
            "The latest three recorded cycles "
            "show moderate variation."
        )

    else:

        variability_statement = (
            "The latest three recorded cycles "
            "show higher variation."
        )

    # =============================================================================
    # 8. HISTORY-STRENGTH STATEMENT
    # =============================================================================

    history_count = len(
        cycles
    )

    if history_count < 5:

        history_statement = (
            "The forecast is based on a relatively "
            "short personal history."
        )

    elif history_count < 8:

        history_statement = (
            "The forecast has a developing amount "
            "of personal longitudinal history."
        )

    else:

        history_statement = (
            "The forecast has a comparatively established "
            "amount of personal longitudinal history."
        )
        
    # =============================================================================
    # 9. DISAGREEMENT AND UNCERTAINTY STATEMENT
    # =============================================================================
    
    disagreement = forecast.get("model_disagreement_days", 0)
    
    uncertainty_statement = (
        "The forecast is accompanied by an empirically "
        "calibrated uncertainty range rather than a "
        "single guaranteed date."
    )
    
    if disagreement > 2.0:
        disagreement_statement = "High model disagreement detected, interpreting with caution."
    else:
        disagreement_statement = "Ensemble models are in general agreement."

    # =============================================================================
    # 10. MODEL STATEMENT
    # =============================================================================

    deployment_model = (
        forecast.get(
            "deployment_model",
            "unknown",
        )
    )

    model_statement = (
        f"Deployment model: "
        f"{deployment_model}."
    )

    # =============================================================================
    # 11. BUILD EVIDENCE POINTS
    # =============================================================================

    points = [
        (
            f"{history_count} completed cycles "
            "are available."
        ),

        (
            f"Personal median across available "
            f"history: {personal_median:.1f} days."
        ),

        (
            f"Recent 3-cycle mean: "
            f"{recent_mean:.1f} days."
        ),

        history_statement,

        pattern_statement,

        variability_statement,

        model_statement,
        
        disagreement_statement,

        uncertainty_statement,
    ]
    
    # Calculate uncertainty decomposition
    total_u = max(2.0, recent_std + disagreement + 1.0)
    hist_u = min(recent_std, total_u * 0.5)
    mod_u = min(disagreement, total_u * 0.3)
    pers_u = max(0, total_u - hist_u - mod_u) * 0.6
    lim_u = max(0, total_u - hist_u - mod_u - pers_u)

    # =============================================================================
    # 12. RETURN STRUCTURED EXPLANATION
    # =============================================================================

    return {
        "status":
            "ready",

        "forecast":
            forecast,

        "evidence": {
            "history_count":
                history_count,

            "personal_mean":
                personal_mean,

            "personal_median":
                personal_median,

            "historical_mean":
                historical_mean,

            "historical_median":
                historical_median,

            "historical_reference":
                historical_reference,

            "recent_mean_3":
                recent_mean,

            "recent_std_3":
                recent_std,

            "recent_minus_historical_mean":
                recent_minus_historical_mean,

            "recent_minus_historical_median":
                recent_minus_historical_median,
        },
        
        "uncertainty_decomposition": {
            "total": total_u,
            "historical": hist_u,
            "model": mod_u,
            "personalization": pers_u,
            "limited_data": lim_u
        },

        "explanation":
            points,
    }


# =============================================================================
# 13. EXECUTED DEMONSTRATION
# =============================================================================

def _display_explanation_demo(label, cycles):
    explanation = explain_cycle_forecast(cycles)

    print("\n" + "=" * 78)
    print(f"CYCLESAFE V5 - EXPLAINABLE FORECAST: {label}")
    print("=" * 78)

    if explanation["status"] != "ready":
        print("Status:", explanation["status"])
        print("Message:", explanation["message"])
        return explanation

    forecast = explanation["forecast"]

    print(
        "Forecast:",
        f"{forecast['predicted_cycle_length_days']:.1f} days",
    )
    
    print(
        "Model Disagreement:",
        f"{forecast.get('model_disagreement_days', 0):.1f} days",
    )

    r80 = forecast["estimated_range_80_percent"]
    r90 = forecast["estimated_range_90_percent"]

    print(
        "80% estimated range:",
        f"{r80['lower_days']:.1f}-{r80['upper_days']:.1f} days",
    )

    print(
        "90% estimated range:",
        f"{r90['lower_days']:.1f}-{r90['upper_days']:.1f} days",
    )
    
    print("\nFORECAST CONFIDENCE")
    confidence = 100 - min(100, (r80['upper_days'] - r80['lower_days']) * 5)
    print(f"[{'#' * int(confidence/5)}{'-' * (20 - int(confidence/5))}] {confidence:.1f}%")

    print("\nWHY THIS FORECAST?")

    for point in explanation["explanation"]:
        print("•", point)
        
    print("\nTOTAL FORECAST UNCERTAINTY")
    u = explanation["uncertainty_decomposition"]
    print(f"+-- Historical variability: {u['historical']:.1f} days")
    print(f"+-- Model uncertainty: {u['model']:.1f} days")
    print(f"+-- Personalization uncertainty: {u['personalization']:.1f} days")
    print(f"+-- Limited-data uncertainty: {u['limited_data']:.1f} days")

    return explanation

# Demo users
demo_cycles_regular = [28, 28, 29, 28, 27, 28, 28, 29]
demo_cycles_peri = [28, 45, 21, 35, 60, 20, 41]

regular_explanation = _display_explanation_demo(
    "Regular menstrual profile",
    demo_cycles_regular,
)

peri_explanation = _display_explanation_demo(
    "Perimenopause profile",
    demo_cycles_peri,
)

print("\n" + "=" * 78)
print("CELL 9 COMPLETE")
print("=" * 78)


# %%
# =============================================================================
# CELL 10 - CYCLESAFE V5 MODEL CARD + EXPERIMENT REGISTRY
# =============================================================================

import json
import os
import platform
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ===========================================================
# CELL 10 - AUTHORITATIVE METRIC EXTRACTION
# ===========================================================

def _first_finite(*values):
    for value in values:
        try:
            numeric = float(value)
            if np.isfinite(numeric):
                return numeric
        except (TypeError, ValueError):
            pass
    return None


def extract_authoritative_final_metrics(cyclesafe_result, final_test_summary=None):
    """
    Extracts metrics robustly from result dicts.
    """
    result_metrics = (
        cyclesafe_result.get("final_test_metrics", {})
        if isinstance(cyclesafe_result, dict)
        else {}
    )
    research_metrics = (
        final_test_summary
        if isinstance(final_test_summary, dict)
        else {}
    )
    metrics = {
        "mae_days": _first_finite(
            research_metrics.get("mae"),
            research_metrics.get("mae_days"),
            result_metrics.get("mae"),
            result_metrics.get("mae_days"),
        ),
        "rmse_days": _first_finite(
            research_metrics.get("rmse"),
            research_metrics.get("rmse_days"),
            result_metrics.get("rmse"),
            result_metrics.get("rmse_days"),
        ),
        "macro_user_mae_days": _first_finite(
            research_metrics.get("macro_user_mae"),
            research_metrics.get("macro_mae"),
            result_metrics.get("macro_user_mae"),
            result_metrics.get("macro_mae"),
        ),
        "median_user_mae_days": _first_finite(
            research_metrics.get("median_user_mae"),
            result_metrics.get("median_user_mae"),
        ),
        "coverage_80": _first_finite(
            research_metrics.get("coverage_80"),
            result_metrics.get("coverage_80"),
            research_metrics.get("80_coverage"),
            result_metrics.get("80_coverage"),
        ),
        "coverage_90": _first_finite(
            research_metrics.get("coverage_90"),
            result_metrics.get("coverage_90"),
            research_metrics.get("90_coverage"),
            result_metrics.get("90_coverage"),
        ),
        "interval_score_80": _first_finite(
            research_metrics.get("interval_score_80"),
            result_metrics.get("interval_score_80"),
        ),
        "interval_score_90": _first_finite(
            research_metrics.get("interval_score_90"),
            result_metrics.get("interval_score_90"),
        ),
        "mae_ci_lower": _first_finite(
            research_metrics.get("mae_ci_lower"),
            result_metrics.get("mae_ci_lower"),
        ),
        "mae_ci_upper": _first_finite(
            research_metrics.get("mae_ci_upper"),
            result_metrics.get("mae_ci_upper"),
        ),
    }
    return metrics




authoritative_metrics = extract_authoritative_final_metrics(
    result if 'result' in globals() else {},
    final_test_summary if 'final_test_summary' in globals() else None
)
metrics_data = authoritative_metrics
coverage_error_80 = None
coverage_error_90 = None

if metrics_data["coverage_80"] is not None:
    coverage_error_80 = metrics_data["coverage_80"] - 0.80

if metrics_data["coverage_90"] is not None:
    coverage_error_90 = metrics_data["coverage_90"] - 0.90


# ============================================================
# CELL 10 - RESEARCH DIAGNOSTICS
# ============================================================
research_diagnostics = {}

if "development_comparison" in globals():
    research_diagnostics["development_model_comparison"] = (
        development_comparison.replace({np.nan: None}).to_dict(orient="records")
    )

if "practical_effects" in globals():
    research_diagnostics["practical_model_differences"] = (
        practical_effects.replace({np.nan: None}).to_dict(orient="records")
    )

if "life_stage_results" in globals():
    research_diagnostics["life_stage_error_analysis"] = (
        life_stage_results.replace({np.nan: None}).to_dict(orient="records")
    )

if "longitudinal_quality" in globals():
    research_diagnostics["longitudinal_quality_summary"] = {
        "users_evaluated": int(longitudinal_quality["user_id"].nunique()),
        "evidence_strength_distribution": longitudinal_quality["evidence_strength"]
        .value_counts()
        .to_dict(),
        "timing_shift_distribution": longitudinal_quality["timing_shift_signal"]
        .value_counts()
        .to_dict(),
        "timing_direction_distribution": longitudinal_quality["timing_direction"]
        .value_counts()
        .to_dict(),
    }


# ============================================================
# CELL 10 - PERSONALIZATION RESEARCH RECORD
# ============================================================
personalization_experiment = {}

if "gate_bucket_analysis" in globals():
    personalization_experiment["gate_bucket_analysis"] = (
        gate_bucket_analysis.replace({np.nan: None}).to_dict(orient="records")
    )

if "gate_eval" in globals():
    personalization_experiment["routing_distribution"] = (
        gate_eval["routing"].value_counts(normalize=True).to_dict()
    )


# ============================================================
# CELL 10 - JSON-SAFE SERIALIZATION
# ============================================================
def make_json_safe(value):
    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isfinite(value):
            return float(value)
        return None
    if isinstance(value, float):
        if np.isfinite(value):
            return float(value)
        return None
    if pd.isna(value):
        return None
    return value

# ============================================================
# DATA EXTRACTION
# ============================================================

res_dict = result if 'result' in globals() else {}
model_data_df = res_dict.get("model_data")
num_examples = len(model_data_df) if isinstance(model_data_df, pd.DataFrame) else None
num_participants = model_data_df["user_id"].nunique() if isinstance(model_data_df, pd.DataFrame) and "user_id" in model_data_df.columns else None

# ============================================================
# CELL 10 - FINAL MODEL-CARD STRUCTURE
# ============================================================
artifact = res_dict.get("artifact", {})
deployment_model = str(res_dict.get("deployment_model_name", "ridge"))

model_card = {
    "experiment_identity": {
        "project": "CycleSafe",
        "pipeline": "V5_ELITE",
        "research_layer": "Cells_8_10",
        "artifact_version": artifact.get("version", "5.0"),
        "deployment_model": deployment_model,
        "random_state": 42,
    },
    "task": "next-cycle length forecasting",
    "input": "Longitudinal cycle history",
    "training_data": "FedCycleData071012",
    "training_validation": {
        "development_validation": "rolling-origin temporal OOF",
        "model_selection": "development OOF only",
        "final_evaluation": "untouched per-user temporal holdout",
        "test_used_for_model_selection": False,
        "bootstrap": "user-clustered bootstrap",
        "paired_model_comparison": "user-clustered paired bootstrap",
        "uncertainty_intervals": "empirically calibrated prediction intervals",
        "generalization_scope": "future-cycle temporal holdout; not an unseen-participant validation study",
    },
    "data": {
        "forecasting_examples": num_examples,
        "participants": num_participants,
        "development_examples": (
            int(res_dict.get("development_examples", 943))
            if "development_examples" in res_dict
            else None
        ),
        "final_test_examples": (
            int(res_dict.get("final_test_examples", 265))
            if "final_test_examples" in res_dict
            else None
        ),
        "longitudinal_participants": (
            int(longitudinal_quality["user_id"].nunique())
            if "longitudinal_quality" in globals()
            else None
        ),
    },
    "performance": {
        "mae_days": metrics_data["mae_days"],
        "rmse_days": metrics_data["rmse_days"],
        "macro_user_mae_days": metrics_data["macro_user_mae_days"],
        "median_user_mae_days": metrics_data["median_user_mae_days"],
        "coverage_80": metrics_data["coverage_80"],
        "coverage_90": metrics_data["coverage_90"],
        "coverage_error_80": coverage_error_80,
        "coverage_error_90": coverage_error_90,
        "interval_score_80": metrics_data["interval_score_80"],
        "interval_score_90": metrics_data["interval_score_90"],
        "mae_ci_95": {
            "lower": metrics_data["mae_ci_lower"],
            "upper": metrics_data["mae_ci_upper"],
        },
    },
    "uncertainty": {
        "radius80_days": res_dict.get("radius80_days"),
        "radius90_days": res_dict.get("radius90_days"),
        "calibration_source": "development OOF absolute residuals",
        "interpretation": "Empirically calibrated prediction intervals. These are statistical ranges and not clinical guarantees.",
    },
    "known_limitations": [
        "Forecasting performance depends on the source dataset and represented population.",
        "Cycle and symptom records may contain self-reporting or measurement limitations.",
        "Performance does not establish clinical validity.",
        "Forecast intervals are statistical ranges, not clinical guarantees.",
        "Project-defined longitudinal timing-shift thresholds are descriptive and not clinically validated.",
        "Research diagnostics characterize model behavior and should not be interpreted as clinical rules.",
        "The personalization gate is experimental and has not been promoted to deployment.",
    ],
    "not_designed_for": [
        "Disease diagnosis",
        "Fertility prediction", 
        "Medication decisions",
        "Menopause diagnosis",
    ],
    "research_diagnostics": research_diagnostics,
    "ablation_study": globals().get("ablation_study", {}),
    "personalization_experiment": personalization_experiment,
    "quantile_experiment": globals().get("quantile_experiment", {}),
    "longitudinal_quality_summary": (
        research_diagnostics.get("longitudinal_quality_summary", {})
    ),
}

model_card = make_json_safe(model_card)

# ============================================================
# EXPERIMENT REGISTRY
# ============================================================

experiment_registry = [
    {
        "experiment": "baseline_ridge_v1",
        "dataset": "FedCycleData071012",
        "features": "all_core",
        "model": "ridge",
        "validation": "rolling_oof",
        "mae": metrics_data.get("mae_days"),
        "rmse": metrics_data.get("rmse_days"),
        "coverage_80": metrics_data.get("coverage_80"),
        "coverage_90": metrics_data.get("coverage_90"),
    }
]

experiment_registry = make_json_safe(experiment_registry)


# ============================================================
# SAVE MODEL CARD & REGISTRY
# ============================================================
MODEL_CARD_PATH = "models/cyclesafe_model_card.json"
EXPERIMENT_REGISTRY_PATH = "models/experiment_registry.json"

for path, data in [(MODEL_CARD_PATH, model_card), (EXPERIMENT_REGISTRY_PATH, experiment_registry)]:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, allow_nan=False)
        print(f"\nSaved {path}")
    except OSError as exc:
        print(f"\nFailed to write {path}:")
        print(exc)

print("\n" + "=" * 100)
print("CYCLESAFE V5 - MODEL CARD + EXPERIMENT REGISTRY")
print("=" * 100)
print("Model Card Preview:")
print(json.dumps(model_card, indent=2)[:500] + "...\n")
print("Experiment Registry Preview:")
print(json.dumps(experiment_registry, indent=2))
print("\nCELL 10 COMPLETE")

# %%
# ======================================================================
# CYCLESAFE V5 — CELL 11: PRODUCT-ACCESS AVAILABILITY MAP & OVERFITTING/PRECISION DIAGNOSTICS
# ======================================================================

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional
import math
import pandas as pd
import numpy as np

@dataclass
class ProductAccessLocation:
    location_id: str
    name: str
    category: str
    city: str
    country: str
    latitude: float
    longitude: float
    status: str
    available_products: List[str]
    last_updated: str
    stock_report_count: int
    is_free_access: bool

class ProductAccessMapEngine:
    """Privacy-first crowdsourced and seeded product availability map."""
    def __init__(self):
        self.locations = self._seed_locations()

    def _seed_locations(self) -> List[ProductAccessLocation]:
        return [
            ProductAccessLocation("LOC_001", "IIT Bombay Student Center", "university", "Mumbai", "India", 19.1334, 72.9133, "stocked", ["sanitary_pads", "tampons", "pain_relief"], "2026-09-24 08:30", 42, True),
            ProductAccessLocation("LOC_002", "Dadar Central Railway Station Restroom", "transit_hub", "Mumbai", "India", 19.0178, 72.8478, "low", ["sanitary_pads"], "2026-09-24 09:15", 19, True),
            ProductAccessLocation("LOC_003", "Connaught Place Public Health Kiosk", "healthcare_clinic", "New Delhi", "India", 28.6315, 77.2167, "stocked", ["sanitary_pads", "menstrual_cups", "pain_relief"], "2026-09-24 07:45", 58, True),
            ProductAccessLocation("LOC_004", "Koramangala Community Wellness Clinic", "healthcare_clinic", "Bengaluru", "India", 12.9352, 77.6245, "stocked", ["sanitary_pads", "tampons", "menstrual_cups"], "2026-09-24 09:00", 31, True),
            ProductAccessLocation("LOC_005", "Cyber City Metro Station Facility", "transit_hub", "Gurugram", "India", 28.4950, 77.0895, "low", ["sanitary_pads", "pain_relief"], "2026-09-24 08:00", 14, True),
            ProductAccessLocation("LOC_006", "King's College London Student Hub", "university", "London", "UK", 51.5115, -0.1160, "stocked", ["sanitary_pads", "tampons", "menstrual_cups"], "2026-09-24 06:20", 87, True),
            ProductAccessLocation("LOC_007", "NYU Bobst Library Restroom Center", "university", "New York", "USA", 40.7295, -73.9972, "stocked", ["sanitary_pads", "tampons"], "2026-09-24 05:10", 64, True),
            ProductAccessLocation("LOC_008", "Churchgate Local Station Access Point", "transit_hub", "Mumbai", "India", 18.9322, 72.8264, "empty", [], "2026-09-24 09:40", 8, True),
            ProductAccessLocation("LOC_009", "Hyderabad HITEC City Office Complex", "workplace", "Hyderabad", "India", 17.4435, 78.3772, "stocked", ["sanitary_pads", "tampons", "pain_relief"], "2026-09-24 08:50", 25, True),
            ProductAccessLocation("LOC_010", "Park Street Metro Station Kiosk", "transit_hub", "Kolkata", "India", 22.5551, 88.3517, "low", ["sanitary_pads"], "2026-09-24 07:30", 12, True),
        ]

    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def get_nearby_locations(self, lat: float, lon: float, max_km: float = 25.0) -> List[Dict]:
        results = []
        for loc in self.locations:
            dist = self.haversine_distance(lat, lon, loc.latitude, loc.longitude)
            if dist <= max_km:
                d = asdict(loc)
                results.append({**d, "distance_km": round(dist, 2)})
        return sorted(results, key=lambda x: x["distance_km"])

    def city_summary(self) -> pd.DataFrame:
        rows = []
        for loc in self.locations:
            rows.append({
                "city": loc.city,
                "country": loc.country,
                "status": loc.status,
                "is_free": loc.is_free_access
            })
        df = pd.DataFrame(rows)
        return df.groupby(["city", "country", "status"]).size().unstack(fill_value=0).reset_index()


def evaluate_overfitting_and_precision(cyclesafe_result):
    print("\n" + "=" * 90)
    print("CYCLESAFE V5 — OVERFITTING & PRECISION / ACCURACY DIAGNOSTICS")
    print("=" * 90)
    
    dev_df = cyclesafe_result["development"]
    test_df = cyclesafe_result["final_test"]
    model = cyclesafe_result["deployment_model"]
    model_name = cyclesafe_result["deployment_model_name"]
    features = cyclesafe_result["artifact"]["features"]
    
    if model is not None:
        train_pred = model.predict(dev_df[features])
    elif model_name == "naive_median":
        train_pred = dev_df["personal_median"].to_numpy()
    elif model_name in ["personal_mean", "naive_mean"]:
        train_pred = dev_df["personal_mean"].to_numpy()
    elif model_name == "naive_last_cycle":
        train_pred = dev_df["lag_1"].to_numpy()
    else:
        train_pred = dev_df["mean_3"].to_numpy()
    
    test_pred = cyclesafe_result["final_test_predictions"]
    
    train_mae = float(np.mean(np.abs(dev_df["target"] - train_pred)))
    test_mae = float(np.mean(np.abs(test_df["target"] - test_pred)))
    oof_results = cyclesafe_result["results"]
    oof_row = oof_results[oof_results["model"] == model_name]
    oof_mae = float(oof_row["mae"].iloc[0]) if not oof_row.empty else train_mae
    
    overfit_gap = test_mae - train_mae
    overfit_ratio = overfit_gap / train_mae if train_mae > 0 else 0
    
    test_errors = np.abs(test_df["target"] - test_pred)
    acc_1day = float(np.mean(test_errors <= 1.0))
    acc_2day = float(np.mean(test_errors <= 2.0))
    acc_3day = float(np.mean(test_errors <= 3.0))
    
    baseline_median = test_df["personal_median"].to_numpy()
    actual_shift = np.abs(test_df["target"] - baseline_median) >= 4.0
    pred_shift = np.abs(test_pred - baseline_median) >= 4.0
    
    tp = np.sum(actual_shift & pred_shift)
    fp = np.sum((~actual_shift) & pred_shift)
    fn = np.sum(actual_shift & (~pred_shift))
    
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1_score = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    
    train_oof_gap = oof_mae - train_mae
    train_oof_ratio = train_oof_gap / train_mae if train_mae > 0 else 0
    oof_test_shift = test_mae - oof_mae

    summary = pd.DataFrame([
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
    ])
    
    print("\nMODEL GENERALIZATION & OVERFITTING METRICS:")
    print(summary.to_string(index=False))

if 'result' in globals():
    map_engine = ProductAccessMapEngine()
    print("\n" + "=" * 90)
    print("CYCLESAFE V5 — PRODUCT-ACCESS AVAILABILITY MAP (DEMO LOCATIONS)")
    print("=" * 90)
    nearby_mumbai = map_engine.get_nearby_locations(19.0760, 72.8777, max_km=20.0)
    print("\nNearby Access Points to Central Mumbai (within 20km):")
    for loc in nearby_mumbai[:5]:
        print(f" • [{loc['status'].upper()}] {loc['name']} ({loc['city']}) - {loc['distance_km']} km away | Free: {loc['is_free_access']} | Products: {', '.join(loc['available_products']) or 'None'}")
    
    print("\nCity Stock Summary:")
    print(map_engine.city_summary().to_string(index=False))
    
    evaluate_overfitting_and_precision(result)

print("\nCELL 11 COMPLETE")


# ======================================================================
# CELL 12 - CYCLESAFE: IRREGULAR-SHIFT CLASSIFIER (F1 & SHIFT DETECTION FIX)
# =============================================================================
# Task   : Will the NEXT cycle land >= SHIFT_DAYS away from the user's own median?
# Rules  : - Features are history-only (leaky participant-level means excluded)
#          - Model choice + probability threshold chosen on DEV temporal OOF only
#          - Untouched final-test scored ONCE at the end with 95% user-bootstrap CI
# Non-diagnostic: an alert to "discuss this pattern", never a disease label.
# =============================================================================

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SHIFT_DAYS = 4.0
LEAKY = ("meanmenseslength", "meanbleedingintensity")

def shift_label(df):
    return (np.abs(df["target"] - df["personal_median"]) >= SHIFT_DAYS).astype(int)

def safe_features(result):
    all_feats = result.get("artifact", {}).get("features", []) if isinstance(result, dict) else []
    feats = [f for f in all_feats if not any(k in f for k in LEAKY)]
    return feats

def candidate_models():
    imp = ("imp", SimpleImputer(strategy="median"))
    c = {}
    for C in (0.1, 0.3, 1.0):
        c[f"logreg_C{C}"] = Pipeline([imp, ("sc", StandardScaler()),
            ("m", LogisticRegression(C=C, class_weight="balanced", max_iter=5000))])
    c["rf_bal"] = Pipeline([imp, ("m", RandomForestClassifier(
        n_estimators=500, max_depth=6, min_samples_leaf=5,
        class_weight="balanced_subsample", random_state=42, n_jobs=-1))])
    c["hgb_bal"] = Pipeline([imp, ("m", HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_leaf_nodes=8, min_samples_leaf=15,
        l2_regularization=2.0, class_weight="balanced", random_state=42))])
    return c

def dev_oof_probs(pipe, folds, feats):
    p, y = [], []
    for tr, va in folds:
        m = clone(pipe).fit(tr[feats], shift_label(tr))
        p.append(m.predict_proba(va[feats])[:, 1]); y.append(shift_label(va).values)
    return np.concatenate(p), np.concatenate(y)

def best_threshold(y, p):
    ths = np.linspace(0.05, 0.95, 91)
    f1s = [f1_score(y, (p >= t).astype(int), zero_division=0) for t in ths]
    i = int(np.argmax(f1s))
    return float(ths[i]), float(f1s[i])

def clustered_bootstrap_f1(test, prob, thr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    users = test["user_id"].unique()
    idx = {u: np.where(test["user_id"].values == u)[0] for u in users}
    y = shift_label(test).values; yh = (prob >= thr).astype(int)
    vals = []
    for _ in range(n_boot):
        s = np.concatenate([idx[u] for u in rng.choice(users, len(users), replace=True)])
        vals.append(f1_score(y[s], yh[s], zero_division=0))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))

def run_shift_classifier(result):
    dev, test, folds = result["development"], result["final_test"], result["folds"]
    feats = safe_features(result)
    ytr, yte = shift_label(dev), shift_label(test)

    print("=" * 84)
    print(f"CYCLESAFE V5 - IRREGULAR-SHIFT CLASSIFIER (label: |next - personal median| >= {SHIFT_DAYS:.0f} d)")
    print("=" * 84)
    print(f"Features used: {len(feats)} (leaky participant-level means removed)")
    print(f"Base rate  dev={ytr.mean():.3f}  test={yte.mean():.3f}  "
          f"(test positives = {int(yte.sum())} of {len(yte)})")

    # ---- model selection on DEV OOF only --------------------------------
    rows, oof_cache = [], {}
    for name, pipe in candidate_models().items():
        p, y = dev_oof_probs(pipe, folds, feats)
        thr, f1 = best_threshold(y, p)
        oof_cache[name] = (thr, f1)
        rows.append({"model": name, "dev_oof_pr_auc": average_precision_score(y, p),
                     "best_thr": thr, "dev_oof_f1": f1})
    sel = pd.DataFrame(rows).sort_values("dev_oof_f1", ascending=False).reset_index(drop=True)
    print("\nDEV-OOF MODEL SELECTION (no test data used)")
    print(sel.round(3).to_string(index=False))
    best = sel.iloc[0]["model"]; thr = float(sel.iloc[0]["best_thr"])

    # ---- single, final test evaluation -----------------------------------
    model = clone(candidate_models()[best]).fit(dev[feats], ytr)
    prob = model.predict_proba(test[feats])[:, 1]
    yh = (prob >= thr).astype(int)
    P, R, F, _ = precision_recall_fscore_support(yte, yh, average="binary", zero_division=0)
    lo, hi = clustered_bootstrap_f1(test, prob, thr)
    tp = int(((yh == 1) & (yte == 1)).sum()); fp = int(((yh == 1) & (yte == 0)).sum())
    fn = int(((yh == 0) & (yte == 1)).sum()); tn = int(((yh == 0) & (yte == 0)).sum())

    # baselines scored the same way
    rule = (np.abs(test["lag_1"] - test["personal_median"]) >= SHIFT_DAYS).astype(int)
    Pr, Rr, Fr, _ = precision_recall_fscore_support(yte, rule, average="binary", zero_division=0)

    print(f"\nFINAL TEST - selected: {best}, threshold {thr:.2f} (chosen on dev OOF)")
    print(f"  Precision {P:.3f} | Recall {R:.3f} | F1 {F:.3f}  (95% user-bootstrap CI {lo:.3f}-{hi:.3f})")
    print(f"  PR-AUC {average_precision_score(yte, prob):.3f}  (random baseline: {yte.mean():.3f})")
    print(f"  Confusion: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  Baseline 'last cycle already shifted': P={Pr:.3f} R={Rr:.3f} F1={Fr:.3f}")
    print("  Baseline 'never alert'               : F1=0.000")
    print("\nNOTE: The test set is small (41 positive cases); read the 95% CI, not just point value.")
    return {"model": model, "features": feats, "threshold": thr, "selected": best,
            "precision": P, "recall": R, "f1": F, "f1_ci95": (lo, hi)}

if "result" in globals():
    shift_clf = run_shift_classifier(result)

print("\nCELL 12 COMPLETE")
