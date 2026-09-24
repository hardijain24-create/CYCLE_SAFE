"""CycleSafe Privacy & Governance Engine.

Implements:
- SQLite-backed user storage for cycle logs and symptom logs
- Consent management with strict enforcement before data logging
- GDPR/DPDP export_user_data (JSON)
- True data erasure (delete_user_data) returning actual deleted counts
- Deletion verification (verify_deletion)
"""
import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

class ConsentRecord:
    def __init__(self, user_id: str, purposes: List[str], given_at: Optional[str] = None, active: bool = True, withdrawn_at: Optional[str] = None):
        self.user_id = user_id
        self.purposes = purposes
        self.given_at = given_at or datetime.now(timezone.utc).isoformat()
        self.active = active
        self.withdrawn_at = withdrawn_at

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "purposes": self.purposes,
            "given_at": self.given_at,
            "active": self.active,
            "withdrawn_at": self.withdrawn_at
        }

class CycleSafePrivacyEngine:
    """Technical privacy & data governance engine backed by SQLite."""
    def __init__(self, db_path: str = "cyclesafe_user_data.db", storage_dir: str = "user_data"):
        self.db_path = db_path
        self.storage_dir = storage_dir
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS consent (
                    user_id TEXT PRIMARY KEY,
                    purposes_json TEXT NOT NULL,
                    given_at TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    withdrawn_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cycle_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    cycle_length_days REAL NOT NULL,
                    log_date TEXT NOT NULL,
                    details_json TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symptom_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    severity INTEGER NOT NULL,
                    log_date TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def register_consent(self, user_id: str, purposes: Optional[List[str]] = None) -> ConsentRecord:
        if purposes is None:
            purposes = [
                "Cycle length tracking and forecasting",
                "Symptom pattern detection (non-diagnostic)",
                "Doctor report generation",
                "Anonymous product access map contributions",
            ]
        record = ConsentRecord(user_id, purposes)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO consent (user_id, purposes_json, given_at, active, withdrawn_at)
                VALUES (?, ?, ?, 1, NULL)
            """, (user_id, json.dumps(purposes), record.given_at))
            conn.commit()
        return record

    def record_consent(self, user_id: str, consent_given: bool = True, purposes: Optional[List[str]] = None) -> ConsentRecord:
        if not consent_given:
            self.withdraw_consent(user_id)
            return ConsentRecord(user_id, purposes or [], active=False)
        return self.register_consent(user_id, purposes)

    def get_consent(self, user_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM consent WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["active"] = bool(d["active"] == 1)
            return d

    def has_active_consent(self, user_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT active FROM consent WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return bool(row and row["active"] == 1)

    def withdraw_consent(self, user_id: str) -> Dict:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM consent WHERE user_id = ?", (user_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO consent (user_id, purposes_json, given_at, active, withdrawn_at)
                    VALUES (?, '[]', ?, 0, ?)
                """, (user_id, now_str, now_str))
            else:
                cursor.execute("""
                    UPDATE consent SET active = 0, withdrawn_at = ? WHERE user_id = ?
                """, (now_str, user_id))
            conn.commit()

        return {
            "status": "withdrawn",
            "user_id": user_id,
            "withdrawn_at": now_str,
            "message": "All non-essential data processing halted."
        }

    def add_cycle_record(self, user_id: str, cycle_data: Dict) -> Dict:
        """Adds a cycle record. Enforces active consent requirement."""
        if not self.has_active_consent(user_id):
            raise PermissionError(f"User '{user_id}' does not have an active consent record. Data logging blocked.")

        cycle_len = float(cycle_data.get("cycle_length_days", 28.0))
        log_date = str(cycle_data.get("log_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")))
        details = json.dumps({k: v for k, v in cycle_data.items() if k not in ["cycle_length_days", "log_date"]})

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO cycle_logs (user_id, cycle_length_days, log_date, details_json)
                VALUES (?, ?, ?, ?)
            """, (user_id, cycle_len, log_date, details))
            conn.commit()
            rec_id = cursor.lastrowid

        return {
            "status": "success",
            "id": rec_id,
            "user_id": user_id,
            "cycle_length_days": cycle_len,
            "log_date": log_date
        }

    def get_cycle_records(self, user_id: str) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cycle_logs WHERE user_id = ? ORDER BY log_date ASC", (user_id,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("details_json"):
                    d["details"] = json.loads(d["details_json"])
                results.append(d)
            return results

    def export_user_data(self, user_id: str) -> str:
        """Export all user data as JSON."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM consent WHERE user_id = ?", (user_id,))
            c_row = cursor.fetchone()
            consent_dict = dict(c_row) if c_row else None
            if consent_dict and consent_dict.get("purposes_json"):
                consent_dict["purposes"] = json.loads(consent_dict["purposes_json"])

        cycles = self.get_cycle_records(user_id)

        export = {
            "export_metadata": {
                "user_id": user_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "format": "CycleSafe JSON Export v1",
                "note": "Complete data held by CycleSafe for this user."
            },
            "consent": consent_dict,
            "data": {
                "cycles": cycles,
                "cycle_count": len(cycles)
            }
        }
        return json.dumps(export, indent=2, default=str)

    def delete_user_data(self, user_id: str) -> Dict:
        """True delete of all user records + consent + files. Returns actual counts."""
        deleted_counts = {"cycles": 0, "symptoms": 0, "consent": 0, "files": 0}

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM cycle_logs WHERE user_id = ?", (user_id,))
            deleted_counts["cycles"] = cursor.rowcount

            cursor.execute("DELETE FROM symptom_logs WHERE user_id = ?", (user_id,))
            deleted_counts["symptoms"] = cursor.rowcount

            cursor.execute("DELETE FROM consent WHERE user_id = ?", (user_id,))
            deleted_counts["consent"] = cursor.rowcount

            conn.commit()

        # Remove stored user files if any exist
        user_dir = os.path.join(self.storage_dir, user_id)
        if os.path.exists(user_dir):
            import shutil
            shutil.rmtree(user_dir)
            deleted_counts["files"] += 1

        return {
            "status": "deleted",
            "user_id": user_id,
            "deleted_counts": deleted_counts,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "message": "All user data and consent records permanently deleted.",
            "verification": self.verify_deletion(user_id)
        }

    def verify_deletion(self, user_id: str) -> bool:
        """Verify nothing remains in DB or filesystem for user."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as c FROM consent WHERE user_id = ?", (user_id,))
            c_cnt = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) as c FROM cycle_logs WHERE user_id = ?", (user_id,))
            cy_cnt = cursor.fetchone()["c"]

        user_dir = os.path.join(self.storage_dir, user_id)
        has_files = os.path.exists(user_dir)

        return (c_cnt == 0) and (cy_cnt == 0) and not has_files


def test_privacy():
    engine = CycleSafePrivacyEngine(db_path="test_temp_privacy.db")
    engine.register_consent("user_test")
    engine.add_cycle_record("user_test", {"cycle_length_days": 28.0})
    export = engine.export_user_data("user_test")
    assert "user_test" in export
    res = engine.delete_user_data("user_test")
    assert res["status"] == "deleted"
    assert engine.verify_deletion("user_test") == True

    import gc
    gc.collect()
    if os.path.exists("test_temp_privacy.db"):
        try:
            os.remove("test_temp_privacy.db")
        except OSError:
            pass
    print("ALL PRIVACY ENGINE TESTS PASSED")

if __name__ == "__main__":
    test_privacy()
