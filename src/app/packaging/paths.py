"""Submission archive path normalization and collision controls."""

import unicodedata
from pathlib import PurePosixPath

_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def normalized_archive_path(value: str) -> tuple[str, str]:
    """Return the NFC path and its case-insensitive collision key."""

    normalized = unicodedata.normalize("NFC", value)
    path = PurePosixPath(normalized)
    parts = path.parts
    if (
        not normalized
        or normalized.startswith(("/", "\\"))
        or "\\" in normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("archive path must be relative and traversal-free")
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        safe_characters = all(
            character.isalnum() or character in {".", "_", "-"} for character in part
        )
        if stem in _WINDOWS_RESERVED or not safe_characters:
            raise ValueError("archive path contains an unsafe or reserved segment")
    return normalized, normalized.casefold()
