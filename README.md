# CycleSafe: Privacy-First Longitudinal Women's-Health Record

CycleSafe is a non-diagnostic, privacy-first longitudinal health project (menstrual + perimenopause tracking, cautious pattern flags, doctor-ready report PDF, and small product-access map).

## Core Principles & Spec Alignment
- **Informational, Not Diagnostic**: No disease names or medical diagnosis claims.
- **Defensible Forecasting**: Uses personal median baseline prediction with Mondrian (group-wise) conformal uncertainty ranges.
- **Privacy & Security**: Mandatory HMAC bearer tokens, active consent enforcement, and real SQLite data erasure.
- **Product-Access Map**: Community check-ins verified by multi-IP and multi-token thresholds with input sanitization.

## Project Structure
```
cycle_safe/
├── README.md
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .gitignore
├── cycle_safe.py
├── src/
│   └── cyclesafe/
│       ├── __init__.py
│       ├── config.py
│       ├── forecast.py
│       ├── lifestage.py
│       ├── rules/
│       │   └── engine.py
│       ├── report/
│       │   └── pdf.py
│       ├── privacy/
│       │   └── engine.py
│       ├── map/
│       │   └── engine.py
│       └── api/
│           ├── main.py
│           ├── schemas.py
│           └── auth.py
├── notebooks/
│   └── cycle_safe.ipynb
├── scripts/
│   ├── train_model.py
│   └── generate_demo_reports.py
├── tests/
│   ├── test_item1_auth.py
│   ├── test_item2_consent.py
│   ├── test_item3_flags.py
│   ├── test_item4_forecast.py
│   ├── test_item5_report.py
│   ├── test_item6_model_selection.py
│   ├── test_item7_map.py
│   ├── test_item8_duplication.py
│   ├── test_item9_repo_hygiene.py
│   └── test_regressions.py
├── models/
│   ├── cyclesafe_model_card.json
│   └── experiment_registry.json
├── reports/
│   ├── doctor_report_regular.pdf
│   ├── doctor_report_perimenopause.pdf
│   └── doctor_report_menopause.pdf
├── docs/
│   ├── PRIVACY.md
│   ├── MODEL_CARD.md
│   ├── SPEC_SUMMARY.md
│   └── DOC-20260918-WA0030.docx
└── archive/
```

## Running Tests and API
```bash
# Run pytest from root
python -m pytest

# Start FastAPI server via uvicorn
uvicorn cyclesafe.api.main:app --reload
```
