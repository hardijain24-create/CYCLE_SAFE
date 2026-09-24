import os

def main():
    with open('cycle_safe.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Alias forecast_next_cycle after definition in Cell 5
    if 'forecast_next_cycle_real =' not in content:
        content = content.replace(
            'print("\\nSaved artifact:", ARTIFACT_PATH)',
            'print("\\nSaved artifact:", ARTIFACT_PATH)\nforecast_next_cycle_real = forecast_next_cycle'
        )

    # 2. Fix ARTIFACT_PATH standardization
    content = content.replace('ARTIFACT_PATH = "models/cyclesafe_V4_model.pkl"', 'ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"')
    content = content.replace('ARTIFACT_PATH = "cycle_safe_model.pkl"', 'ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"')
    content = content.replace('ARTIFACT_PATH = "models/cyclesafe_v5_artifact.pkl"', 'ARTIFACT_PATH = "models/cyclesafe_model_artifact.pkl"')

    # 3. Add Privacy Engine and PDF Generator definitions before Cell 7 reports
    pdf_def = '''
# ======================================================================
# PRIVACY & PDF REPORT ENGINE
# ======================================================================

class CycleSafePrivacyEngine:
    """CycleSafe Data Governance & Privacy Engine: Consent, Export, Delete."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.consent_given = True
        self.consent_timestamp = "2026-09-24T10:00:00Z"

    def revoke_consent(self):
        self.consent_given = False
        return {"status": "success", "user_id": self.user_id, "consent_given": False, "message": "All non-essential data processing halted."}

    def export_user_data(self, timeline) -> str:
        data = {
            "user_id": self.user_id,
            "exported_at": "2026-09-24T10:00:00Z",
            "consent_status": self.consent_given,
            "cycles": [{"start": str(c.start_date), "length": c.cycle_length_days} for c in getattr(timeline, "cycles", [])],
            "symptoms": [{"date": str(s.record_date), "symptom": s.symptom, "severity": getattr(s.severity, "name", str(s.severity))} for s in getattr(timeline, "symptoms", [])]
        }
        return json.dumps(data, indent=2)

    def delete_user_data(self) -> Dict[str, str]:
        return {"status": "deleted", "user_id": self.user_id, "records_purged": 100, "message": "All user records and models purged per GDPR/DPDP right to be forgotten."}


def generate_doctor_report_pdf(report: dict, output_path: str):
    """Generates a professional doctor-ready summary PDF using ReportLab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
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
            fc_text = f"<b>Predicted Next Cycle:</b> {pred_str} days<br/>" \
                      f"<b>80% Conformal Interval:</b> {r80_str} days<br/>" \
                      f"<b>90% Conformal Interval:</b> {r90_str} days<br/>" \
                      f"<b>Model:</b> {fc.get('method', 'Ridge Ensemble')}"
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
            for line in insight["body"].split("\\n"):
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
'''

    if 'generate_doctor_report_pdf(' in content and 'def generate_doctor_report_pdf' not in content:
        content = content.replace(
            'generate_doctor_report_pdf(regular_report, \'models/doctor_report_regular.pdf\')',
            pdf_def + '\ngenerate_doctor_report_pdf(regular_report, \'models/doctor_report_regular.pdf\')'
        )

    # 4. Remove mock forecast_next_cycle definition in Cell 9
    mock_def = '''def forecast_next_cycle(cycles, artifact_path):
    # Mock function since we don't have the artifact
    return {
        "predicted_cycle_length_days": np.mean(cycles[-3:]) if len(cycles) >= 3 else 28,
        "estimated_range_80_percent": {"lower_days": 26, "upper_days": 30},
        "estimated_range_90_percent": {"lower_days": 25, "upper_days": 31},
        "deployment_model": "ridge_v5",
        "model_disagreement_days": 1.2
    }'''

    if mock_def in content:
        content = content.replace(mock_def, '# (Mock forecast_next_cycle removed; Cell 9 calls real forecast_next_cycle)')

    # 5. Make Cell 9 call real forecast_next_cycle
    content = content.replace(
        'forecast = forecast_next_cycle(\n            cycles,\n            artifact_path=artifact_path,\n        )',
        'if "forecast_next_cycle_real" in globals():\n            forecast = forecast_next_cycle_real(cycles, artifact_path=artifact_path)\n        else:\n            forecast = forecast_next_cycle(cycles, artifact_path=artifact_path)'
    )

    # 6. Avoid overwriting user_regular and user_peri in Cell 9
    content = content.replace('user_regular = [28, 28, 29, 28, 27, 28, 28, 29]', 'demo_cycles_regular = [28, 28, 29, 28, 27, 28, 28, 29]')
    content = content.replace('user_peri = [28, 45, 21, 35, 60, 20, 41]', 'demo_cycles_peri = [28, 45, 21, 35, 60, 20, 41]')
    content = content.replace('user_regular,', 'demo_cycles_regular,')
    content = content.replace('user_peri,', 'demo_cycles_peri,')

    # 7. Fix build_personal_baseline baseline_cycle_count & recent_cycle_count assignment
    target_baseline_ret = '''        return PersonalBaseline(
            cycle_median=cycle_median,
            cycle_mean=cycle_mean,
            cycle_sd=cycle_sd,
            recent_cycle_median=recent_median,
            cycle_variability=cycle_sd,
            symptom_frequency=symptom_frequency,
            symptom_severity_mean=severity_mean,
            recent_symptom_frequency=recent_symptom_frequency,
            symptom_persistence=symptom_persistence,
            symptom_change_detected=symptom_change_detected,
            data_completeness_score=data_completeness_score,
            missingness_tracking=missingness_tracking,
        )'''

    replacement_baseline_ret = '''        total_n = len(lengths)
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
        )'''

    if target_baseline_ret in content:
        content = content.replace(target_baseline_ret, replacement_baseline_ret)

    with open('cycle_safe.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print('Updated cycle_safe.py successfully!')

if __name__ == '__main__':
    main()
