import os
import pytest
from pypdf import PdfReader
from cyclesafe.report.pdf import generate_all_demo_reports

def test_pdf_report_text_extraction_and_no_forbidden_claims():
    reports_dir = "reports"
    generate_all_demo_reports(reports_dir)

    regular_pdf = os.path.join(reports_dir, "doctor_report_regular.pdf")
    peri_pdf = os.path.join(reports_dir, "doctor_report_perimenopause.pdf")
    meno_pdf = os.path.join(reports_dir, "doctor_report_menopause.pdf")

    for path in [regular_pdf, peri_pdf, meno_pdf]:
        assert os.path.exists(path), f"PDF file missing at {path}"
        reader = PdfReader(path)
        assert len(reader.pages) >= 1

    # Extract text from perimenopause PDF (age 46)
    peri_text = "".join([p.extract_text() for p in PdfReader(peri_pdf).pages])

    # Assert perimenopause PDF contains experimental label and wider uncertainty note
    assert "experimental, wider uncertainty" in peri_text, "Perimenopause PDF must include experimental label"
    assert "training data covers ages 21 to 43" in peri_text, "Perimenopause PDF must mention training data age limitation"
    assert "forecast may lag the shift" in peri_text, "Perimenopause PDF with >= 3d shift must state forecast may lag shift"

    # Assert forbidden strings on perimenopause PDF
    assert "calibrated on dev OOF" not in peri_text, "Perimenopause PDF must NEVER claim 'calibrated on dev OOF'"

    # Assert forbidden strings are absent across ALL PDFs
    for path in [regular_pdf, peri_pdf, meno_pdf]:
        text = "".join([p.extract_text() for p in PdfReader(path).pages])
        assert "utilizes robust ensemble outputs" not in text, f"Forbidden string 'utilizes robust ensemble outputs' found in {path}"
        assert "High agreement" not in text, f"Forbidden string 'High agreement' found in {path}"

    # Assert Menopause (0 cycles) PDF has no contradiction
    meno_text = "".join([p.extract_text() for p in PdfReader(meno_pdf).pages])
    assert "No significant timing shift detected" not in meno_text, "Menopause 0-cycle report must not claim 'No significant timing shift detected'"
    assert "Recent consistency High" not in meno_text, "Menopause 0-cycle report must not claim 'Recent consistency High'"
    assert "N/A (0 cycles logged)" in meno_text, "Menopause 0-cycle report must show 'N/A (0 cycles logged)'"
