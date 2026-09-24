# CycleSafe V5 Elite — Privacy-First Longitudinal Women's Health Pipeline

CycleSafe is a privacy-first, non-diagnostic longitudinal health tracking system for menstrual and perimenopausal health records, cautious pattern flags, doctor-ready PDF reports, and product access point mapping.

> **Disclaimer**: CycleSafe is an informational health tracking record, NOT a diagnostic tool or medical device. It does not diagnose diseases, predict fertility, or estimate exact menopause timing.

---

## Directory Structure

```text
cyclesafe/
  ├── README.md                      # Overview, running commands, disclaimers
  ├── requirements.txt               # Pinned runtime dependencies
  ├── requirements-dev.txt           # Testing & dev dependencies (pytest, httpx)
  ├── src/cyclesafe/
  │   ├── config.py                  # Pipeline constants & core features
  │   ├── forecast.py                # Shared unified forecast function
  │   ├── lifestage.py               # Shared perimenopause uncertainty logic
  │   ├── rules/engine.py            # Deterministic non-diagnostic symptom rules
  │   ├── privacy/engine.py          # SQLite consent, export & true deletion engine
  │   ├── map/engine.py              # Product access map with anti-tampering rules
  │   └── api/main.py                # RESTful FastAPI service endpoints
  ├── notebooks/
  │   └── cycle_safe.ipynb           # Thin research notebook (24 cells)
  ├── scripts/
  │   ├── train_model.py             # Model training entrypoint
  │   └── generate_demo_reports.py   # Demo PDF generator (regular, perimenopause, menopause)
  ├── tests/
  │   ├── test_regressions.py        # Comprehensive acceptance test suite
  │   └── test_suite.py              # System acceptance tests
  ├── models/                        # Saved artifacts, model cards & experiment registry
  ├── data/                          # Data dictionaries and data specifications
  ├── reports/                       # Generated demo PDF doctor reports
  ├── docs/                          # Specifications, Privacy docs & Model Cards
  └── archive/                       # Historic patches and legacy backups
```

---

## Quick Start Commands

### 1. Run Complete Acceptance Test Suite
```bash
python tests/test_regressions.py
python test_suite.py
```

### 2. Generate Demo Doctor Reports (PDF)
```bash
python scripts/generate_demo_reports.py
```

### 3. Run FastAPI Web Service
```bash
uvicorn src.cyclesafe.api.main:app --reload --port 8000
```
