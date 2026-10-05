"""Verification primitives for reviewed repository-pinned provider assets."""

from pathlib import Path, PurePosixPath

from app.common.canonical import sha256_hex


def verify_repository_asset(
    repository_root: Path,
    relative_path: str,
    expected_sha256: str | None = None,
    *,
    allowed_root: str,
) -> tuple[Path, str]:
    """Resolve and checksum a safe asset below one approved repository directory."""

    logical_path = PurePosixPath(relative_path)
    if logical_path.is_absolute() or ".." in logical_path.parts or "\\" in relative_path:
        raise ValueError(f"unsafe repository asset path: {relative_path}")
    root = repository_root.resolve()
    boundary = (root / allowed_root).resolve()
    path = (root / Path(*logical_path.parts)).resolve()
    try:
        path.relative_to(boundary)
    except ValueError as error:
        raise ValueError(
            f"repository asset must be below {allowed_root}/: {relative_path}"
        ) from error
    if not path.is_file():
        raise ValueError(f"repository asset is unavailable: {relative_path}")
    actual_sha256 = sha256_hex(path.read_bytes())
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError(f"repository asset checksum mismatch: {relative_path}")
    return path, actual_sha256
