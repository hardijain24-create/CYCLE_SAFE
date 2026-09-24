import pytest
import os
import pypdf

def extract_pdf_text(pdf_path: str) -> str:
    reader = pypdf.PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def test_item5_report_pdf_claims_and_honest_phrasing():
    # Make sure demo reports are generated
    from scripts.generate_demo_reports import generate_all_demo_reports
    generate_all_demo_reports()

    regular_pdf = "reports/doctor_report_regular.pdf"
    peri_pdf = "reports/doctor_report_perimenopause.pdf"
    meno_pdf = "reports/doctor_report_menopause.pdf"

    assert os.path.exists(regular_pdf), f"Missing {regular_pdf}"
    assert os.path.exists(peri_pdf), f"Missing {peri_pdf}"
    assert os.path.exists(meno_pdf), f"Missing {meno_pdf}"

    txt_reg = extract_pdf_text(regular_pdf)
    txt_peri = extract_pdf_text(peri_pdf)
    txt_meno = extract_pdf_text(meno_pdf)

    # 1. Forbidden strings
    for txt, name in [(txt_reg, "regular"), (txt_peri, "peri"), (txt_meno, "meno")]:
        assert "████████░░" not in txt, f"Hardcoded bar string found in {name} PDF"
        assert "utilizes robust ensemble outputs" not in txt, f"Forbidden string 'utilizes robust ensemble outputs' in {name} PDF"

    # 2. Perimenopause PDF must NOT claim "calibrated on dev OOF"
    assert "calibrated on dev OOF" not in txt_peri, "Perimenopause PDF must not claim 'calibrated on dev OOF'"
    assert "experimental, wider uncertainty" in txt_peri, "Perimenopause PDF must state 'experimental, wider uncertainty'"

    # 3. Menopause PDF must NOT say "No significant timing shift detected" or "Recent consistency High"
    assert "No significant timing shift detected" not in txt_meno, "Menopause PDF must not claim 'No significant timing shift detected'"
    assert "Recent consistency High" not in txt_meno, "Menopause PDF must not claim 'Recent consistency High'"

    # 4. Check shift warning when recent-3 median differs from baseline by >=3 days
    # (Tested via demo script or report builder when shift >= 3 days)
