import os
import shutil

ROOT = os.path.abspath(os.path.dirname(__file__))

DIRS_TO_CREATE = [
    os.path.join(ROOT, "archive"),
    os.path.join(ROOT, "src", "cyclesafe"),
    os.path.join(ROOT, "src", "cyclesafe", "rules"),
    os.path.join(ROOT, "src", "cyclesafe", "report"),
    os.path.join(ROOT, "src", "cyclesafe", "privacy"),
    os.path.join(ROOT, "src", "cyclesafe", "map"),
    os.path.join(ROOT, "src", "cyclesafe", "api"),
    os.path.join(ROOT, "notebooks"),
    os.path.join(ROOT, "scripts"),
    os.path.join(ROOT, "data"),
    os.path.join(ROOT, "reports"),
    os.path.join(ROOT, "docs"),
    os.path.join(ROOT, "tests"),
    os.path.join(ROOT, "models"),
]

for d in DIRS_TO_CREATE:
    os.makedirs(d, exist_ok=True)

# 1. Move one-off patch scripts and historic backup to archive/
ARCHIVE_FILES = [
    "cycle_safe_v4_backup.py",
    "cycle_safe (1).ipynb",
    "apply_fixes.py",
    "apply_master_refactor.py",
    "p0_trust_fixes.py",
    "p0_mock.py",
    "fix_result_access.py",
]
for f in ARCHIVE_FILES:
    src = os.path.join(ROOT, f)
    dst = os.path.join(ROOT, "archive", f)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"Moved {f} -> archive/")

# 2. Move documentation files to docs/ and data/
DOCS_FILES = {
    "PRIVACY.md": os.path.join(ROOT, "docs", "PRIVACY.md"),
    "docx_summary.txt": os.path.join(ROOT, "docs", "SPEC_SUMMARY.md"),
    "DOC-20260918-WA0030.docx": os.path.join(ROOT, "docs", "DOC-20260918-WA0030.docx"),
    "DATA_DICTIONARY.md": os.path.join(ROOT, "data", "DATA_DICTIONARY.md"),
}
for src_f, dst_f in DOCS_FILES.items():
    src_p = os.path.join(ROOT, src_f)
    if os.path.exists(src_p):
        shutil.move(src_p, dst_f)
        print(f"Moved {src_f} -> {os.path.relpath(dst_f, ROOT)}")

# 3. Move modules to src/cyclesafe/
MODULE_FILES = {
    "cyclesafe_rules.py": os.path.join(ROOT, "src", "cyclesafe", "rules", "engine.py"),
    "cyclesafe_privacy.py": os.path.join(ROOT, "src", "cyclesafe", "privacy", "engine.py"),
    "cyclesafe_map.py": os.path.join(ROOT, "src", "cyclesafe", "map", "engine.py"),
    "cyclesafe_api.py": os.path.join(ROOT, "src", "cyclesafe", "api", "main.py"),
}
for src_f, dst_f in MODULE_FILES.items():
    src_p = os.path.join(ROOT, src_f)
    if os.path.exists(src_p):
        shutil.copy(src_p, dst_f)
        print(f"Copied {src_f} -> {os.path.relpath(dst_f, ROOT)}")

# 4. Move cycle_safe.ipynb to notebooks/
if os.path.exists(os.path.join(ROOT, "cycle_safe.ipynb")):
    shutil.move(os.path.join(ROOT, "cycle_safe.ipynb"), os.path.join(ROOT, "notebooks", "cycle_safe.ipynb"))
    print("Moved cycle_safe.ipynb -> notebooks/")

# 5. Move convert_py_to_ipynb.py to scripts/
if os.path.exists(os.path.join(ROOT, "convert_py_to_ipynb.py")):
    shutil.move(os.path.join(ROOT, "convert_py_to_ipynb.py"), os.path.join(ROOT, "scripts", "convert_py_to_ipynb.py"))
    print("Moved convert_py_to_ipynb.py -> scripts/")

print("RESTRUCTURE DIRECTORY LAYOUT PREPARATION COMPLETE")
