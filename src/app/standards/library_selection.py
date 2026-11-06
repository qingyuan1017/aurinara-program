"""Deterministic acquisition of immutable CDISC Library resource graphs."""

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.common.canonical import canonical_json, sha256_hex
from app.integration.cdisc_library import CdiscLibraryReader, iter_link_references

SELECTION_NAMESPACE = UUID("8f18be76-2c67-4f54-88d8-32b090f90a45")


class CdiscLibrarySelectionResource(BaseModel):
    """One immutable JSON representation in an imported Library selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    category: Literal["standard", "terminology"]
    canonical_href: str
    title: str
    resource_type: str
    asset_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["application/json"] = "application/json"


class CdiscLibrarySelectionManifest(BaseModel):
    """Inventory for one exact product or terminology release fetched on demand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    provider: Literal["CDISC"]
    library_base_url: str
    selected_href: str
    library_updated: dict[str, str]
    captured_at: datetime
    resource_count: int
    resources: tuple[CdiscLibrarySelectionResource, ...]


@dataclass(frozen=True, slots=True)
class FetchedCdiscLibrarySelection:
    """A verified selection inventory plus ephemeral files ready for publication."""

    manifest: CdiscLibrarySelectionManifest
    local_files: dict[str, Path]


def _category(href: str) -> Literal["standard", "terminology"]:
    return "terminology" if href.startswith(("/mdr/ct/", "/mdr/root/ct/")) else "standard"


def _validate_selection_root(href: str) -> None:
    """Reject mutable aliases and catalog resources that do not identify a release."""

    if href.startswith("/mdr/root/"):
        raise ValueError("mutable CDISC Library root aliases cannot be imported")
    catalog_roots = (
        "/mdr/products",
        "/mdr/search",
        "/mdr/lastupdated",
        "/mdr/about",
        "/mdr/maintenance",
    )
    if href == "/mdr/ct/packages" or any(
        href == catalog or href.startswith(f"{catalog}/") for catalog in catalog_roots
    ):
        raise ValueError("select an exact CDISC product or terminology release, not a catalog")
    segments = [segment for segment in href.split("/") if segment]
    if len(segments) < 3 or segments[0] != "mdr":
        raise ValueError("selected CDISC Library href does not identify a concrete release")


def fetch_library_selection(
    *,
    reader: CdiscLibraryReader,
    staging_root: Path,
    library_base_url: str,
    selected_href: str,
    max_resources: int,
    parallel_requests: int = 8,
    progress: Callable[[int, str], None] | None = None,
) -> FetchedCdiscLibrarySelection:
    """Fetch only one concrete release graph into ephemeral staging files.

    Linked resources are followed only when they are the selected root or descendants
    of that root. Parent catalogs, related releases, and mutable ``/mdr/root`` aliases
    are never pulled into the selection.
    """

    if max_resources < 1:
        raise ValueError("max_resources must be positive")
    if not 1 <= parallel_requests <= 32:
        raise ValueError("parallel_requests must be between 1 and 32")
    root_href = reader.canonical_href(selected_href)
    _validate_selection_root(root_href)
    staging_root.mkdir(parents=True, exist_ok=False)

    last_updated_resource = reader.get("/mdr/lastupdated")
    library_updated = {
        key: value
        for key, value in last_updated_resource.content.items()
        if key != "_links" and isinstance(value, str)
    }
    if "overall" not in library_updated:
        raise ValueError("CDISC Library last-updated resource has no overall version")

    queued: deque[tuple[str, str, str]] = deque([(root_href, "", "")])
    queued_hrefs = {root_href}
    visited: set[str] = set()
    resources: list[CdiscLibrarySelectionResource] = []
    local_files: dict[str, Path] = {}
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
                    f"CDISC Library selection exceeded the {max_resources} resource limit"
                )
            futures = [executor.submit(reader.get, href) for href, _title, _type in batch]
            for (requested_href, queued_title, queued_type), future in zip(
                batch, futures, strict=True
            ):
                resource = future.result()
                if resource.href != requested_href:
                    raise ValueError("CDISC Library returned a different canonical resource")
                visited.add(resource.href)
                content_bytes = canonical_json(resource.content)
                checksum = sha256_hex(content_bytes)
                local_path = staging_root / f"{checksum}.json"
                if not local_path.exists():
                    local_path.write_bytes(content_bytes)
                local_files[resource.href] = local_path
                resources.append(
                    CdiscLibrarySelectionResource(
                        id=uuid5(
                            SELECTION_NAMESPACE,
                            f"selection:{root_href}:{resource.href}:{checksum}",
                        ),
                        category=_category(root_href),
                        canonical_href=resource.href,
                        title=resource.title or queued_title,
                        resource_type=resource.resource_type or queued_type,
                        asset_path=f"external/cdisc-library/{checksum}.json",
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
                    if canonical_href != root_href and not canonical_href.startswith(
                        f"{root_href}/"
                    ):
                        continue
                    if canonical_href not in visited and canonical_href not in queued_hrefs:
                        queued.append((canonical_href, title, resource_type))
                        queued_hrefs.add(canonical_href)
                if progress is not None:
                    progress(len(visited), resource.href)

    ordered_resources = tuple(sorted(resources, key=lambda item: item.canonical_href))
    return FetchedCdiscLibrarySelection(
        manifest=CdiscLibrarySelectionManifest(
            schema_version="1.0.0",
            provider="CDISC",
            library_base_url=library_base_url.rstrip("/"),
            selected_href=root_href,
            library_updated=library_updated,
            captured_at=datetime.now(UTC),
            resource_count=len(ordered_resources),
            resources=ordered_resources,
        ),
        local_files=local_files,
    )
