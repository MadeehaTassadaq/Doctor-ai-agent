"""Cursor-based pagination helpers.

This module provides encode/decode functions for cursor-based pagination.
The cursor format determines how pagination state is serialized between
the API and the client, and how the repository resumes queries.
"""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode


def encode_cursor(last_id: str, last_sort_value: str | None = None) -> str:
    """Encode pagination cursor from the last item's ID and sort value.

    Returns a URL-safe base64-encoded JSON string (no padding).
    """
    cursor_data = {"last_id": last_id}
    if last_sort_value is not None:
        cursor_data["last_sort_value"] = last_sort_value
    encoded = urlsafe_b64encode(json.dumps(cursor_data).encode()).decode().rstrip("=")
    return encoded


def decode_cursor(cursor: str) -> dict:
    """Decode a pagination cursor into its component values.

    Handles URL-safe base64 with stripped or present padding.
    Returns an empty dict on malformed input.
    """
    try:
        # urlsafe_b64decode requires padding; add it back if stripped
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = urlsafe_b64decode(padded.encode()).decode()
        return json.loads(decoded)
    except (json.JSONDecodeError, Exception):
        return {}
