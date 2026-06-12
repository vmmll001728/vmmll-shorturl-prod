"""Slug generator and validator."""
from __future__ import annotations

import secrets
import string

ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits


def generate_slug(length: int = 6) -> str:
    """Generate a cryptographically random slug of given length."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_valid_alias(alias: str) -> bool:
    """Check if an alias is valid: alphanumeric + dash/underscore only."""
    allowed = set(string.ascii_letters + string.digits + "-_")
    return all(c in allowed for c in alias)