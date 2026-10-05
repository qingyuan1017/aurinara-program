"""Deterministic JSON and fingerprint primitives."""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Serialize JSON-compatible data deterministically as UTF-8 bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def fingerprint(value: Any) -> str:
    """Fingerprint a JSON-compatible value using its canonical form."""

    return sha256_hex(canonical_json(value))
