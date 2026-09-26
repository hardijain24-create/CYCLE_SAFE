"""
Vercel entrypoint shim for CycleSafe FastAPI app.

Vercel's serverless filesystem is read-only except /tmp.
This shim:
  1. Adds repo-root src/ to sys.path so the cyclesafe package is importable.
  2. Sets CYCLESAFE_DB_PATH to /tmp so SQLite has a writable location.
  3. Sets CYCLESAFE_MODEL_DIR to the bundled models/ dir at the repo root.
  4. Re-exports the FastAPI `app` object so Vercel can discover it.
"""
import sys
import os

# ── 1. Make `cyclesafe` package importable ────────────────────────────────────
# api/index.py lives in <repo_root>/api/, so we go up one level to reach src/
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_repo_root, "src"))

# ── 2. Point SQLite DB at /tmp (the only writable dir on Vercel) ──────────────
os.environ.setdefault("CYCLESAFE_DB_PATH", "/tmp/cyclesafe_user_data.db")

# ── 3. Point model loader at the bundled models/ dir ─────────────────────────
os.environ.setdefault("CYCLESAFE_MODEL_DIR", os.path.join(_repo_root, "models"))

# ── 4. Import and re-export the app ──────────────────────────────────────────
from cyclesafe.api.main import app  # noqa: F401 – re-exported for Vercel
