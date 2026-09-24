import pytest
import os
import tempfile
from cyclesafe.privacy.engine import CycleSafePrivacyEngine

@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Give every test its own fresh SQLite database."""
    db_file = str(tmp_path / "test_cyclesafe.db")
    fresh_engine = CycleSafePrivacyEngine(db_path=db_file)
    
    # Monkeypatch the module-level privacy_engine in the API
    import cyclesafe.api.main as api_mod
    monkeypatch.setattr(api_mod, "privacy_engine", fresh_engine)
    
    yield
    
    # Cleanup happens automatically via tmp_path
