"""Authentication and token verification for CycleSafe API."""

import os
import hmac
import hashlib
from typing import Optional, Tuple

SECRET_KEY = os.environ.get("CYCLESAFE_SECRET", "cyclesafe-secret-key-2026-privacy-first").encode('utf-8')

def generate_user_token(user_id: str) -> str:
    """Generates an HMAC-SHA256 bearer token for the given user_id."""
    h = hmac.new(SECRET_KEY, user_id.encode('utf-8'), hashlib.sha256)
    return f"cs_{h.hexdigest()[:32]}"

def verify_token(user_id: str, authorization: Optional[str]) -> Tuple[bool, int, str]:
    """
    Verifies Bearer token against target user_id.
    Returns (is_valid, status_code, error_message).
    - 401 if header is missing or token invalid
    - 403 if token belongs to a different user
    """
    if not authorization or not authorization.startswith("Bearer "):
        return False, 401, "Missing or invalid Authorization header. Expected 'Bearer <token>'."

    token = authorization.replace("Bearer ", "").strip()
    expected_token = generate_user_token(user_id)

    if hmac.compare_digest(token, expected_token):
        return True, 200, "OK"

    # Check if token belongs to any valid user by comparing with expected token
    # If token format is valid cs_ prefix but doesn't match expected user_id -> 403
    if token.startswith("cs_"):
        return False, 403, "Forbidden: Authorization token does not match requested user_id."

    return False, 401, "Unauthorized: Invalid token format."
