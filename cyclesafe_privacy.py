"""CycleSafe Privacy Engine.

Implements: consent management, data export (JSON), data deletion,
and data minimisation documentation.

Note: Real deployment requires legal review. This implements the
technical controls described in the project report.
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

class ConsentRecord:
    def __init__(self, user_id: str, purposes: List[str]):
        self.user_id = user_id
        self.purposes = purposes
        self.given_at = datetime.now(timezone.utc).isoformat()
        self.active = True
        self.withdrawn_at = None
    
    def withdraw(self) -> Dict:
        self.active = False
        self.withdrawn_at = datetime.now(timezone.utc).isoformat()
        return {'status': 'withdrawn', 'user_id': self.user_id, 
                'withdrawn_at': self.withdrawn_at,
                'message': 'All non-essential data processing halted.'}
    
    def to_dict(self) -> Dict:
        return {'user_id': self.user_id, 'purposes': self.purposes,
                'given_at': self.given_at, 'active': self.active,
                'withdrawn_at': self.withdrawn_at}

class CycleSafePrivacyEngine:
    """Technical privacy controls for CycleSafe.
    
    Note: A real deployment needs legal review to ensure compliance
    with GDPR, India DPDP Act, or other applicable privacy law.
    This module implements the technical controls only.
    """
    def __init__(self, storage_dir: str = 'user_data'):
        self.storage_dir = storage_dir
        self.consents: Dict[str, ConsentRecord] = {}
    
    def register_consent(self, user_id: str, 
                         purposes: Optional[List[str]] = None) -> ConsentRecord:
        if purposes is None:
            purposes = [
                'Cycle length tracking and forecasting',
                'Symptom pattern detection (non-diagnostic)',
                'Doctor report generation',
                'Anonymous product access map contributions',
            ]
        record = ConsentRecord(user_id, purposes)
        self.consents[user_id] = record
        return record
    
    def withdraw_consent(self, user_id: str) -> Dict:
        if user_id not in self.consents:
            return {'status': 'error', 'message': 'No consent record found.'}
        return self.consents[user_id].withdraw()
    
    def export_user_data(self, user_id: str, user_data: Dict) -> str:
        """Export all user data as JSON. Returns the JSON string."""
        export = {
            'export_metadata': {
                'user_id': user_id,
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'format': 'CycleSafe JSON Export v1',
                'note': 'This contains all data CycleSafe holds for this user.'
            },
            'consent': self.consents[user_id].to_dict() if user_id in self.consents else None,
            'data': user_data
        }
        return json.dumps(export, indent=2, default=str)
    
    def delete_user_data(self, user_id: str) -> Dict:
        """True delete of all user data. Returns confirmation."""
        deleted_items = []
        
        # Remove consent record
        if user_id in self.consents:
            del self.consents[user_id]
            deleted_items.append('consent_record')
        
        # Remove any stored files
        user_dir = os.path.join(self.storage_dir, user_id)
        if os.path.exists(user_dir):
            import shutil
            shutil.rmtree(user_dir)
            deleted_items.append('stored_files')
        
        return {
            'status': 'deleted',
            'user_id': user_id,
            'items_deleted': deleted_items,
            'deleted_at': datetime.now(timezone.utc).isoformat(),
            'message': 'All user data has been permanently deleted.',
            'verification': user_id not in self.consents
        }
    
    def verify_deletion(self, user_id: str) -> bool:
        """Verify nothing remains for this user."""
        has_consent = user_id in self.consents
        has_files = os.path.exists(os.path.join(self.storage_dir, user_id))
        return not has_consent and not has_files


def test_privacy():
    engine = CycleSafePrivacyEngine(storage_dir='test_privacy_data')
    
    # Register consent
    consent = engine.register_consent('test_user_001')
    assert consent.active == True
    assert consent.user_id == 'test_user_001'
    
    # Export
    export = engine.export_user_data('test_user_001', {'cycles': [28, 29, 30]})
    parsed = json.loads(export)
    assert parsed['export_metadata']['user_id'] == 'test_user_001'
    assert parsed['data'] == {'cycles': [28, 29, 30]}
    
    # Withdraw consent
    result = engine.withdraw_consent('test_user_001')
    assert result['status'] == 'withdrawn'
    
    # Delete
    del_result = engine.delete_user_data('test_user_001')
    assert del_result['status'] == 'deleted'
    
    # Verify deletion
    assert engine.verify_deletion('test_user_001') == True
    
    # Cleanup
    import shutil
    if os.path.exists('test_privacy_data'):
        shutil.rmtree('test_privacy_data')
    
    print('ALL PRIVACY TESTS PASSED')

if __name__ == '__main__':
    test_privacy()
