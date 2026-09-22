"""Payload redaction before raw upstream captures are persisted."""

from __future__ import annotations

import re
from typing import Any, Mapping


REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(r"(?:authorization|api[_-]?key|token|secret|password|cookie|session)", re.IGNORECASE)


def redact_sensitive_payload(value: Any) -> Any:
    """Recursively remove credential-like fields while preserving useful payload shape."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if SENSITIVE_KEY.search(str(key)) else redact_sensitive_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_payload(item) for item in value]
    return value
