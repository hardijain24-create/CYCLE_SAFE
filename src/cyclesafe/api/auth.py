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
