"""CycleSafe ReportLab PDF Generation Module."""

import os
from typing import Dict, Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_doctor_report_pdf(report: Dict[str, Any], output_path: str):
    """Generates a doctor-ready summary PDF using ReportLab without forbidden hardcoded claims."""
    abs_output_path = os.path.abspath(output_path)
    dir_name = os.path.dirname(abs_output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
        
    doc = SimpleDocTemplate(
        abs_output_path,
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

        is_peri_or_older = (prof.get("age") and prof.get("age") >= 45) or prof.get("self_reported_stage") in ["perimenopause", "menopause"]
        interval_label = "experimental, wider uncertainty (training data covers ages 21 to 43)" if is_peri_or_older else "calibrated on dev OOF"

        fc_text = f"<b>Predicted Next Cycle:</b> {pred_str} days<br/>" \
                  f"<b>80% Prediction Interval ({interval_label}):</b> {r80_str} days<br/>" \
                  f"<b>90% Prediction Interval ({interval_label}):</b> {r90_str} days<br/>" \
                  f"<b>Model:</b> {fc.get('method', 'Personal Baseline Median')}"
        
        # If recent-3 median differs from baseline by >= 3 days, report shift lag explicitly
        med = base.get('median_days')
        rec_med = base.get('recent_median_days')
        if med is not None and rec_med is not None and abs(rec_med - med) >= 3.0:
            fc_text += f"<br/><i>Note: Recent 3-cycle median ({rec_med:.1f}d) differs from baseline ({med:.1f}d) by >= 3 days; forecast may lag the shift.</i>"

        elements.append(Paragraph(fc_text, body_style))
    else:
        elements.append(Paragraph("<i>Next-cycle forecasting not available for this profile stage.</i>", body_style))

    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Observed Patterns and Symptoms", heading_style))
    changes = report.get("changes", [])
    if changes:
        for c in changes:
            elements.append(Paragraph(f"• <b>{c.get('label')}:</b> {c.get('detail')}", body_style))
    elif cov.get("cycle_records", 0) == 0:
        elements.append(Paragraph("• No cycle history logged.", body_style))
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

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceAfter=8))
    elements.append(Paragraph("<b>Notice:</b> CycleSafe provides observational statistical modeling for self-tracking. It does not provide medical diagnosis, disease identification, or clinical guarantees.", disclaimer_style))

    doc.build(elements)

def generate_all_demo_reports(output_dir: str = "reports"):
    """Generates regular, perimenopause, and menopause demo PDFs into output_dir."""
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)
    
    # 1. Regular profile report
    reg_report = {
        "report_title": "CycleSafe - Longitudinal Health Summary",
        "report_subtitle": "Non-diagnostic patient summary for clinical review",
        "profile": {"user_id": "demo_reg", "age": 26, "self_reported_stage": "regular"},
        "data_coverage": {"cycle_records": 8, "symptom_records": 3},
        "data_quality": {"missing_values": "Low"},
        "personal_baseline": {"median_days": 28.0, "mean_days": 28.3, "sd_days": 1.2, "recent_median_days": 28.0},
        "forecast": {
            "available": True,
            "predicted_days": 28.0,
            "range_80": (26.0, 30.0),
            "range_90": (24.5, 31.5),
            "method": "Personal Baseline Median (naive_median)"
        },
        "changes": [],
        "symptoms": [{"symptom": "mild_cramps"}],
        "discussion_points": ["Continue regular longitudinal tracking."]
    }
    generate_doctor_report_pdf(reg_report, os.path.join(abs_output_dir, "doctor_report_regular.pdf"))

    # 2. Perimenopause profile report (age 46)
    peri_report = {
        "report_title": "CycleSafe - Longitudinal Health Summary",
        "report_subtitle": "Non-diagnostic patient summary for clinical review",
        "profile": {"user_id": "demo_peri", "age": 46, "self_reported_stage": "perimenopause"},
        "data_coverage": {"cycle_records": 7, "symptom_records": 5},
        "data_quality": {"missing_values": "Low"},
        "personal_baseline": {"median_days": 32.0, "mean_days": 35.0, "sd_days": 5.2, "recent_median_days": 37.0},
        "forecast": {
            "available": True,
            "predicted_days": 34.0,
            "range_80": (28.0, 40.0),
            "range_90": (25.0, 43.0),
            "method": "Personal Baseline Median (naive_median)"
        },
        "changes": [{"label": "Cycle-length change", "detail": "Recent median shift: 5.0 days"}],
        "symptoms": [{"symptom": "hot_flashes"}, {"symptom": "night_sweats"}],
        "discussion_points": ["Discuss recent timing shift and vasomotor symptom history."]
    }
    generate_doctor_report_pdf(peri_report, os.path.join(abs_output_dir, "doctor_report_perimenopause.pdf"))

    # 3. Menopause profile report (0 cycles)
    meno_report = {
        "report_title": "CycleSafe - Longitudinal Health Summary",
        "report_subtitle": "Non-diagnostic patient summary for clinical review",
        "profile": {"user_id": "demo_meno", "age": 54, "self_reported_stage": "menopause"},
        "data_coverage": {"cycle_records": 0, "symptom_records": 4},
        "data_quality": {"missing_values": "N/A (0 cycles logged)"},
        "personal_baseline": {"median_days": None, "mean_days": None, "sd_days": None, "recent_median_days": None},
        "forecast": {"available": False},
        "changes": [],
        "symptoms": [{"symptom": "hot_flashes"}, {"symptom": "sleep_disruption"}],
        "discussion_points": ["Symptom history monitoring without next-cycle forecasting."]
    }
    generate_doctor_report_pdf(meno_report, os.path.join(abs_output_dir, "doctor_report_menopause.pdf"))
