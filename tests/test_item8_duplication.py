import pytest
import os

def test_item8_no_root_duplicate_files():
    root_duplicates = ["cyclesafe_api.py", "cyclesafe_map.py", "cyclesafe_privacy.py", "cyclesafe_rules.py"]
    for fname in root_duplicates:
        assert not os.path.exists(fname), f"Duplicate root file {fname} must be deleted! Keep only src/cyclesafe/*"
