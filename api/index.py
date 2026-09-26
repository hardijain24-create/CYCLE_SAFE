"""
Vercel entrypoint shim for CycleSafe FastAPI app.
Adds the src/ directory to sys.path so `cyclesafe` package is importable,
then re-exports the FastAPI `app` object for Vercel's Python runtime.
"""
import sys
import os

# Add src/ to Python path so the cyclesafe package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cyclesafe.api.main import app  # noqa: F401 – re-exported for Vercel
