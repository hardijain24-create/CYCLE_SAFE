# CycleSafe Model Card & Transparency Report

## Model Details
- **Project**: CycleSafe (Longitudinal Women's Health Record)
- **Model Type**: Personalised Baseline / Regularised Linear Model (`Ridge` regression, $\alpha=100$)
- **Task**: Next-cycle length forecasting (days)
- **Artifact Version**: 5.0-ELITE
- **Date**: September 2026

## Intended Use & Scope
- **Intended Use**: Cautious, longitudinal pattern estimation and uncertainty range output for personal health tracking and doctor discussions.
- **Out-of-Scope & Prohibited Uses**:
  - Medical diagnosis (e.g., PCOS, Endometriosis)
  - Fertility / contraception prediction
  - Precise menopause timing prediction
  - Prescription or medication advice

## Training Data & Provenance
- **Dataset**: `FedCycleData071012` (US Fertility Awareness Study, N=159 participants, 1,649 clean cycle records)
- **Age Range**: 21 to 43 years old.
- **Demographic Limitation**: Training data contains no Indian cohort data and no participants over age 43. For users $\ge 45$ or self-reported perimenopause, forecasts are explicitly flagged as `"experimental, wider uncertainty (training data covers ages 21 to 43)"`.

## Validation Protocol & Empirical Performance
- **Validation**: Rolling-origin temporal out-of-fold (OOF) cross-validation (4 folds). Zero holdout test-set tuning.
- **Untouched Final Temporal Holdout Metrics**:
  - **MAE**: **2.049 days** [95% Bootstrap CI: 1.780 – 2.346 days]
  - **RMSE**: **2.987 days** [95% Bootstrap CI: 2.453 – 3.531 days]
  - **Median User MAE**: 1.768 days
- **Interval Calibration & Coverage**:
  - **80% Prediction Interval**: 78.9% empirical coverage (6.29 days width)
  - **90% Prediction Interval**: 92.5% empirical coverage (9.19 days width)
- **Variability-Conditional Coverage (CV_5 Tertiles)**:
  - Low Variability: 92.6% coverage
  - Medium Variability: 79.0% coverage
  - High Variability: 68.3% coverage

## Baseline Comparison & Honest Assessment
- **Ridge vs. Personal Median Baseline**: The Ridge model (MAE 2.049) is **statistically equivalent** to the simple per-user median baseline (MAE 2.050 days). Paired user-clustered bootstrap difference CI spans zero $[-0.103, +0.072\text{ days}]$.
- **Shift Alert Research Classifier**: Irregular shift detector ($\Delta \ge 4$ days) evaluated strictly as an experimental model (Precision: 26.1%, Recall: 73.2%, F1: 0.385). User-facing alerts use deterministic rule `R6` only.

## Privacy & Safety Controls
- **No Data Leakage**: Context columns (`SAFE_CONTEXT_COLUMNS = []`) removed.
- **Local SQLite Storage**: No external telemetry, ad SDKs, or analytics calls at runtime.
