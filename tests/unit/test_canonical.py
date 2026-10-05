"""Canonical JSON and fingerprint invariants."""

from app.common.canonical import canonical_json, fingerprint


def test_canonical_json_is_key_order_independent_and_utf8() -> None:
    left = {"z": "München", "a": [1, None, True]}
    right = {"a": [1, None, True], "z": "München"}

    assert canonical_json(left) == canonical_json(right)
    assert fingerprint(left) == fingerprint(right)
    assert b"M\xc3\xbcnchen" in canonical_json(left)
