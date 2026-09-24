import pytest
import os

def test_item9_repo_hygiene():
    # 1. .gitignore exists and contains required patterns
    assert os.path.exists(".gitignore"), ".gitignore file missing"
    with open(".gitignore", "r", encoding="utf-8") as f:
        git_content = f.read()

    required_patterns = ["*.db", "*.pkl", "__pycache__/", "user_data/", ".env", "*.pyc", "data/raw"]
    for pat in required_patterns:
        assert pat in git_content, f"Missing pattern {pat} in .gitignore"

    # 2. Duplicate PDFs in models/ must be removed
    assert not os.path.exists("models/doctor_report_regular.pdf"), "models/doctor_report_regular.pdf should be removed (keep only reports/)"
    assert not os.path.exists("models/doctor_report_perimenopause.pdf"), "models/doctor_report_perimenopause.pdf should be removed"
    assert not os.path.exists("models/doctor_report_menopause.pdf"), "models/doctor_report_menopause.pdf should be removed"
