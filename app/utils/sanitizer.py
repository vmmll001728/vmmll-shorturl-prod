"""Input sanitization utilities."""
from __future__ import annotations

import html
import re


def sanitize_html(text: str) -> str:
    """Escape HTML special characters to prevent XSS."""
    return html.escape(text)


def sanitize_filename(name: str) -> str:
    """Remove path traversal and null-byte characters from filenames."""
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    return name.strip()


def sanitize_sql_like(text: str) -> str:
    """Escape SQL LIKE pattern special chars (for safe LIKE queries)."""
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )