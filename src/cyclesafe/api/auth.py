"""Authentication and token verification for CycleSafe API.

Note: Token generation and verification are now handled directly in main.py
using random tokens with SHA-256 hashing. This module is kept for reference
but the primary auth flow is in cyclesafe.api.main.
"""

import hashlib
import secrets
from typing import Optional


def hash_token(token: str) -> str:
    """One-way SHA-256 hash of a bearer token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_random_token() -> str:
    """Generate a cryptographically random bearer token (64-char hex)."""
    return secrets.token_hex(32)


def hash_password(password: str) -> str:
    """Store passwords as salt$pbkdf2-sha256 hex. Never store plaintext."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"{salt}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a hash_password() string."""
    if not stored or "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return secrets.compare_digest(derived.hex(), expected)
