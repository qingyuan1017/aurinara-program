"""Deterministic on-disk snapshots of the complete CDISC Library catalog graph."""

import shutil
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.common.canonical import canonical_json, sha256_hex
from app.integration.cdisc_library import CdiscLibraryReader, iter_link_references

SNAPSHOT_NAMESPACE = UUID("8f18be76-2c67-4f54-88d8-32b090f90a45")


class CdiscLibrarySnapshotResource(BaseModel):
    """One immutable JSON representation in a complete Library snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    category: Literal["standard", "terminology"]
    canonical_href: str
    title: str
    resource_type: str
    asset_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["application/json"] = "application/json"


class CdiscLibrarySnapshotManifest(BaseModel):
    """Versioned inventory proving completeness and integrity of one crawl."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    provider: Literal["CDISC"]
    library_base_url: str
    library_updated: dict[str, str]
    captured_at: datetime
    resource_count: int
    resources: tuple[CdiscLibrarySnapshotResource, ...]


def _safe_snapshot_key(overall: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in ".-_" else "-" for character in overall
    )
    normalized = normalized.strip(".-_")
    if not normalized or len(normalized) > 80:
        return sha256_hex(overall.encode("utf-8"))[:24]
    return normalized


def _category(href: str) -> Literal["standard", "terminology"]:
    return "terminology" if href.startswith(("/mdr/ct/", "/mdr/root/ct/")) else "standard"


def create_library_snapshot(
    *,
    reader: CdiscLibraryReader,
    repository_root: Path,
    library_base_url: str,
    max_resources: int,
    parallel_requests: int = 8,
    progress: Callable[[int, str], None] | None = None,
) -> Path:
    """Crawl all linked MDR resources and publish one reviewed-file snapshot."""

    if max_resources < 1:
        raise ValueError("max_resources must be positive")
    if not 1 <= parallel_requests <= 32:
        raise ValueError("parallel_requests must be between 1 and 32")
    last_updated_resource = reader.get("/mdr/lastupdated")
    library_updated = {
        key: value
        for key, value in last_updated_resource.content.items()
        if key != "_links" and isinstance(value, str)
    }
    overall = library_updated.get("overall")
    if overall is None:
        raise ValueError("CDISC Library last-updated resource has no overall version")
    snapshot_key = _safe_snapshot_key(overall)
    schemas_root = (repository_root / "schemas" / "cdisc-library").resolve()
    terminology_root = (repository_root / "terminology" / "cdisc-library").resolve()
    schemas_root.mkdir(parents=True, exist_ok=True)
    terminology_root.mkdir(parents=True, exist_ok=True)
    standard_final = schemas_root / snapshot_key
    terminology_final = terminology_root / snapshot_key
    if standard_final.exists() or terminology_final.exists():
        raise ValueError(f"CDISC Library snapshot already exists: {snapshot_key}")
    operation_id = uuid4().hex
    standard_stage = schemas_root / f".staging-{operation_id}"
    terminology_stage = terminology_root / f".staging-{operation_id}"
    standard_stage.mkdir()
    terminology_stage.mkdir()

    queued: deque[tuple[str, str, str]] = deque(
        [
            ("/mdr/products", "CDISC Library Products", "Product Catalog"),
            ("/mdr/ct/packages", "CDISC Controlled Terminology Packages", "Terminology Catalog"),
            ("/mdr/lastupdated", "CDISC Library Last Updated", "Library Status"),
        ]
    )
    queued_hrefs = {item[0] for item in queued}
    visited: set[str] = set()
    resources: list[CdiscLibrarySnapshotResource] = []
    try:
        with ThreadPoolExecutor(max_workers=parallel_requests) as executor:
            while queued:
                batch: list[tuple[str, str, str]] = []
                while queued and len(batch) < parallel_requests:
                    entry = queued.popleft()
                    if entry[0] not in visited:
                        batch.append(entry)
                if not batch:
                    continue
                if len(visited) + len(batch) > max_resources:
                    raise ValueError(
                        f"CDISC Library snapshot exceeded the {max_resources} resource limit"
                    )
                futures = [
                    None if href == "/mdr/lastupdated" else executor.submit(reader.get, href)
                    for href, _title, _type in batch
                ]
                for (_href, queued_title, queued_type), future in zip(batch, futures, strict=True):
                    resource = last_updated_resource if future is None else future.result()
                    visited.add(resource.href)
                    category = _category(resource.href)
                    content_bytes = canonical_json(resource.content)
                    checksum = sha256_hex(content_bytes)
                    stage_root = terminology_stage if category == "terminology" else standard_stage
                    final_root = terminology_final if category == "terminology" else standard_final
                    filename = f"{sha256_hex(resource.href.encode('utf-8'))}.json"
                    stage_path = stage_root / "resources" / filename
                    stage_path.parent.mkdir(parents=True, exist_ok=True)
                    stage_path.write_bytes(content_bytes)
                    final_path = final_root / "resources" / filename
                    resources.append(
                        CdiscLibrarySnapshotResource(
                            id=uuid5(SNAPSHOT_NAMESPACE, f"{overall}:{resource.href}"),
                            category=category,
                            canonical_href=resource.href,
                            title=resource.title or queued_title,
                            resource_type=resource.resource_type or queued_type,
                            asset_path=final_path.relative_to(repository_root.resolve()).as_posix(),
                            sha256=checksum,
                        )
                    )
                    for linked_href, title, resource_type in iter_link_references(resource.content):
                        try:
                            canonical_href = reader.canonical_href(linked_href)
                        except ValueError:
                            continue
                        if canonical_href.startswith("/mdr/root/"):
                            continue
                        if canonical_href not in visited and canonical_href not in queued_hrefs:
                            queued.append((canonical_href, title, resource_type))
                            queued_hrefs.add(canonical_href)
                    if progress is not None:
                        progress(len(visited), resource.href)

        ordered_resources = tuple(sorted(resources, key=lambda item: item.canonical_href))
        manifest = CdiscLibrarySnapshotManifest(
            schema_version="1.0.0",
            provider="CDISC",
            library_base_url=library_base_url.rstrip("/"),
            library_updated=library_updated,
            captured_at=datetime.now(UTC),
            resource_count=len(ordered_resources),
            resources=ordered_resources,
        )
        (standard_stage / "snapshot-manifest.json").write_bytes(
            canonical_json(manifest.model_dump(mode="json"))
        )
        terminology_stage.rename(terminology_final)
        standard_stage.rename(standard_final)
        return standard_final / "snapshot-manifest.json"
    except BaseException:
        for path in (standard_stage, terminology_stage, standard_final, terminology_final):
            if path.exists():
                shutil.rmtree(path)
        raise
