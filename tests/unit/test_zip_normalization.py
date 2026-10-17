"""Determinism checks for generated ZIP-based artifacts."""

import io
import zipfile

from app.common.zip_normalization import normalize_zip_bytes


def _archive(*, create_system: int, date_time: tuple[int, int, int, int, int, int]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("payload.txt", date_time=date_time)
        info.create_system = create_system
        archive.writestr(info, b"stable payload")
    return output.getvalue()


def test_normalization_removes_host_and_timestamp_variation() -> None:
    unix = _archive(create_system=3, date_time=(2026, 10, 17, 7, 0, 0))
    windows = _archive(create_system=0, date_time=(2025, 1, 2, 3, 4, 6))

    normalized = normalize_zip_bytes(unix)

    assert normalized == normalize_zip_bytes(windows)
    with zipfile.ZipFile(io.BytesIO(normalized)) as archive:
        info = archive.getinfo("payload.txt")
        assert info.create_system == 0
        assert info.date_time == (2000, 1, 1, 0, 0, 0)
