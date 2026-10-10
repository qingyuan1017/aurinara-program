"""Deterministic package assembly and archive-path safety tests."""

import hashlib
import io
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app.packaging.paths import normalized_archive_path
from app.packaging.service import ResolvedPackage, ResolvedPackageFile, build_package


class MemoryStorage:
    local_fallback_enabled = False

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def put_file(self, object_key: str, path: Path, media_type: str) -> None:
        del media_type
        self.objects[object_key] = path.read_bytes()

    @contextmanager
    def open(self, object_key: str) -> Iterator[io.BytesIO]:
        yield io.BytesIO(self.objects[object_key])

    def exists(self, object_key: str) -> bool:
        return object_key in self.objects

    def check(self) -> None:
        return None


def test_deterministic_package_checksums_verify_independently() -> None:
    source = b"USUBJID,SAFFL\n01,Y\n"
    digest = hashlib.sha256(source).hexdigest()
    resolved = ResolvedPackage(
        fingerprint="f" * 64,
        public_manifest={"schema_version": "1.0.0", "entries": []},
        files=(
            ResolvedPackageFile(
                artifact_id=uuid4(),
                archive_path="adam/adam_dataset_csv/ADSL.csv",
                object_key="source",
                expected_sha256=digest,
                size=len(source),
                media_type="text/csv",
                module_key="adam",
                artifact_type="adam_dataset_csv",
            ),
        ),
    )
    storage = MemoryStorage({"source": source})
    first = build_package(resolved, storage)
    second = build_package(resolved, storage)

    assert first.zip_bytes == second.zip_bytes
    with zipfile.ZipFile(io.BytesIO(first.zip_bytes)) as archive:
        checksums = archive.read("checksums.sha256").decode("utf-8").splitlines()
        for entry in checksums:
            expected, path = entry.split("  ", 1)
            assert hashlib.sha256(archive.read(path)).hexdigest() == expected


@pytest.mark.parametrize(
    "value",
    ("../escape.txt", "/absolute.txt", "folder\\file.txt", "CON.txt", "has space.txt"),
)
def test_archive_path_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalized_archive_path(value)


def test_archive_collision_key_is_unicode_and_case_normalized() -> None:
    first, first_key = normalized_archive_path("reports/Caf\N{LATIN SMALL LETTER E WITH ACUTE}.pdf")
    second, second_key = normalized_archive_path("REPORTS/Cafe\N{COMBINING ACUTE ACCENT}.PDF")
    assert first != second
    assert first_key == second_key
