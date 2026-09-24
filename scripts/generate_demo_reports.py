"""CycleSafe Demo Report Generation Script.

Generates PDF doctor reports for regular, perimenopause, and menopause profiles
into the reports/ directory.
"""

import os
import sys

# Ensure src/ is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from cycle_safe import user_regular, user_peri, user_meno, regular_baseline, peri_baseline, meno_baseline, regular_patterns, peri_patterns, meno_patterns, forecast_V4_user, adapter_to_forecast_result, build_winning_insight, build_winning_doctor_report, generate_doctor_report_pdf

def generate_all_demo_reports():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(out_dir, exist_ok=True)

    profiles = [
        ("doctor_report_regular.pdf", user_regular, regular_baseline, regular_patterns),
        ("doctor_report_perimenopause.pdf", user_peri, peri_baseline, peri_patterns),
        ("doctor_report_menopause.pdf", user_meno, meno_baseline, meno_patterns),
    ]

    for fname, timeline, baseline, patterns in profiles:
        fc_res = forecast_V4_user(timeline)
        forecast = adapter_to_forecast_result(fc_res, timeline)
        insight = build_winning_insight(timeline, baseline, patterns, forecast, timeline.profile.self_reported_stage)
        report_dict = build_winning_doctor_report(timeline, baseline, patterns, forecast, insight)

        pdf_path = os.path.join(out_dir, fname)
        generate_doctor_report_pdf(report_dict, pdf_path)
        print(f"Generated demo report: {pdf_path}")

if __name__ == "__main__":
    generate_all_demo_reports()
