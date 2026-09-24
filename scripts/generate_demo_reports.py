"""Generates demo doctor report PDFs into reports/ directory."""

import os
from cyclesafe.report.pdf import generate_all_demo_reports

if __name__ == "__main__":
    os.makedirs("reports", exist_ok=True)
    generate_all_demo_reports("reports")
    print("Demo reports generated successfully in reports/")
