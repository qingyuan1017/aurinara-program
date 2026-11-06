"""Register exact immutable CDISC Library selections in provider catalogs."""

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.artifacts.storage import ObjectStorage
from app.common.asset_content import publish_verified_asset
from app.common.canonical import canonical_json, sha256_hex
from app.standards.library_selection import (
    CdiscLibrarySelectionManifest,
    CdiscLibrarySelectionResource,
    FetchedCdiscLibrarySelection,
)
from app.standards.models import StandardAsset, StandardProduct, StandardVersion
from app.terminology.models import (
    TerminologyAsset,
    TerminologyCodelist,
    TerminologyRelease,
    TerminologyTerm,
)

REGISTRY_NAMESPACE = UUID("bf6e4349-23b8-431e-991c-24cd51233d8f")
VERSIONED_STANDARD = re.compile(
    r"^/mdr/(?P<family>cdash|cdashig|sdtm|sdtmig|sendig|adam)/(?P<version>[^/]+)"
)
MEASURE_STANDARD = re.compile(r"^/mdr/qrs/(?P<measure>[^/]+)/(?P<version>[^/]+)")
INTEGRATED_STANDARD = re.compile(r"^/mdr/integrated/(?P<product>[^/]+)/(?P<version>[^/]+)")
TERMINOLOGY_PACKAGE = re.compile(r"^/mdr/ct/packages/(?P<package>[^/]+)")
PACKAGE_DATE = re.compile(r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$")


def _identifier(value: str, *, max_length: int = 64) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    if not normalized:
        normalized = "CDISC"
    if len(normalized) > max_length:
        digest = sha256_hex(value.encode("utf-8"))[:12].upper()
        normalized = f"{normalized[: max_length - 13]}_{digest}"
    return normalized


def _bounded(value: str, *, max_length: int = 64) -> str:
    if len(value) <= max_length:
        return value
    digest = sha256_hex(value.encode("utf-8"))[:12]
    return f"{value[: max_length - 13]}-{digest}"


def _publication_date(value: str) -> date | None:
    match = PACKAGE_DATE.search(value)
    return date.fromisoformat(match.group("date")) if match else None


def _modules(product: str) -> list[str]:
    return {
        "SDTM": ["sdtm"],
        "SDTMIG": ["sdtm"],
        "SENDIG": ["raw", "sdtm"],
        "ADAM": ["adam", "tlf"],
        "CDASH": ["raw", "documents"],
        "CDASHIG": ["raw", "documents"],
    }.get(product, ["raw", "documents", "sdtm", "adam", "tlf"])


def _purposes(product: str) -> list[str]:
    purposes = ["reference_metadata"]
    if product == "SDTMIG":
        purposes.append("sdtm_ig")
    return purposes


def _standard_group(
    resource: CdiscLibrarySelectionResource, overall: str
) -> tuple[str, str, str, str, str, str]:
    match = VERSIONED_STANDARD.match(resource.canonical_href)
    if match:
        family = match.group("family").upper()
        version = _bounded(match.group("version"))
        product_type = "implementation_guide" if family.endswith("IG") else "model"
        scope = "nonclinical" if family == "SENDIG" else "clinical"
        return family, family, family, product_type, scope, version
    measure = MEASURE_STANDARD.match(resource.canonical_href)
    if measure:
        code = _identifier(f"QRS_{measure.group('measure')}")
        return (
            code,
            f"QRS {measure.group('measure')}",
            "Measures",
            "measure",
            "clinical",
            _bounded(measure.group("version")),
        )
    integrated = INTEGRATED_STANDARD.match(resource.canonical_href)
    if integrated:
        code = _identifier(f"INTEGRATED_{integrated.group('product')}")
        return (
            code,
            f"Integrated {integrated.group('product').upper()}",
            "Integrated",
            "implementation_guide",
            "clinical",
            _bounded(integrated.group("version")),
        )
    return (
        "CDISC_LIBRARY_CATALOG",
        "CDISC Library Catalog",
        "Library",
        "foundational",
        "cross_domain",
        _bounded(overall),
    )


def _terminology_group(
    resource: CdiscLibrarySelectionResource, overall: str
) -> tuple[str, str, str]:
    match = TERMINOLOGY_PACKAGE.match(resource.canonical_href)
    if not match:
        return "CDISC_CT_CATALOG", "ALL", _bounded(overall)
    package = match.group("package")
    prefix = re.split(r"-[0-9]{4}-[0-9]{2}-[0-9]{2}$", package, maxsplit=1)[0]
    product = _identifier(prefix.removesuffix("ct"))
    return _identifier(f"{product}_CT"), product, _bounded(package)


def _group_checksum(resources: list[CdiscLibrarySelectionResource]) -> str:
    return sha256_hex(
        canonical_json(
            [
                {"href": item.canonical_href, "sha256": item.sha256}
                for item in sorted(resources, key=lambda value: value.canonical_href)
            ]
        )
    )


def _resource_content(
    resource: CdiscLibrarySelectionResource,
    repository_root: Path,
    local_files: dict[str, Path] | None = None,
) -> dict[str, object]:
    path = (
        local_files[resource.canonical_href]
        if local_files is not None
        else repository_root / resource.asset_path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"selected resource is not an object: {resource.canonical_href}")
    return payload


def _codelist_payloads(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return codelists from either package or individual-codelist responses."""

    embedded = payload.get("codelists")
    if isinstance(embedded, list):
        return [item for item in embedded if isinstance(item, dict)]
    if all(isinstance(payload.get(field), str) for field in ("conceptId", "name")):
        return [payload]
    return []


def _register_standard_group(
    session: Session,
    *,
    identity: tuple[str, str, str, str, str, str],
    resources: list[CdiscLibrarySelectionResource],
    provenance: dict[str, object],
) -> None:
    code, name, family, product_type, scope, version = identity
    product_id = uuid5(REGISTRY_NAMESPACE, f"standard-product:{code}")
    version_id = uuid5(REGISTRY_NAMESPACE, f"standard-version:{code}:{version}")
    checksum = _group_checksum(resources)
    product = session.get(StandardProduct, product_id)
    if product is None:
        product = StandardProduct(
            id=product_id,
            code=code,
            name=name,
            provider="CDISC",
            family=family,
            product_type=product_type,
            scope=scope,
        )
        session.add(product)
    existing = session.get(StandardVersion, version_id)
    if existing is not None:
        if existing.checksum != checksum:
            raise ValueError(f"published standard changed for {code} {version}")
        return
    release = StandardVersion(
        id=version_id,
        product_id=product_id,
        version=version,
        publication_date=_publication_date(version),
        library_href=min(resources, key=lambda item: len(item.canonical_href)).canonical_href,
        content_schema_version="1.0.0",
        lifecycle="active",
        checksum=checksum,
        asset_path=min(resources, key=lambda item: len(item.canonical_href)).asset_path,
        provenance=provenance,
        applicable_modules=_modules(code),
        purposes=_purposes(code),
        compatibility={"resource_count": len(resources)},
    )
    session.add(release)
    session.flush()
    session.add_all(
        [
            StandardAsset(
                id=item.id,
                version_id=release.id,
                role=_identifier(item.resource_type or "library_resource").lower(),
                media_type=item.media_type,
                asset_path=item.asset_path,
                checksum=item.sha256,
                required=True,
                canonical_href=item.canonical_href,
                title=item.title or None,
                resource_type=item.resource_type or None,
                content_schema_version="1.0.0",
            )
            for item in resources
        ]
    )


def _register_terminology_group(
    session: Session,
    *,
    identity: tuple[str, str, str],
    resources: list[CdiscLibrarySelectionResource],
    repository_root: Path,
    provenance: dict[str, object] | None = None,
    local_files: dict[str, Path] | None = None,
) -> None:
    code, product, version = identity
    release_id = uuid5(REGISTRY_NAMESPACE, f"terminology-release:{code}:{version}")
    checksum = _group_checksum(resources)
    existing = session.get(TerminologyRelease, release_id)
    if existing is not None:
        if existing.checksum != checksum:
            raise ValueError(f"published terminology changed for {code} {version}")
        return
    root_resource = min(resources, key=lambda item: len(item.canonical_href))
    release = TerminologyRelease(
        id=release_id,
        code=code,
        version=version,
        provider="CDISC",
        product=product,
        publication_date=_publication_date(version),
        library_href=root_resource.canonical_href,
        content_schema_version="1.0.0",
        lifecycle="active",
        checksum=checksum,
        asset_path=root_resource.asset_path,
        applicable_modules=_modules(product),
        provenance=provenance
        or {"source": "CDISC Library", "resource_count": len(resources)},
    )
    session.add(release)
    session.flush()
    session.add_all(
        [
            TerminologyAsset(
                id=item.id,
                release_id=release.id,
                role=_identifier(item.resource_type or "library_resource").lower(),
                media_type=item.media_type,
                asset_path=item.asset_path,
                checksum=item.sha256,
                canonical_href=item.canonical_href,
                title=item.title or None,
                resource_type=item.resource_type or None,
                content_schema_version="1.0.0",
            )
            for item in resources
        ]
    )
    seen_codelists: set[str] = set()
    codelist_rows: list[dict[str, object]] = []
    term_rows: list[dict[str, object]] = []
    for resource in resources:
        resource_payload = _resource_content(resource, repository_root, local_files)
        for payload in _codelist_payloads(resource_payload):
            concept_id = payload.get("conceptId")
            submission_value = payload.get("submissionValue")
            name = payload.get("name")
            if not all(isinstance(item, str) for item in (concept_id, submission_value, name)):
                continue
            concept_id = str(concept_id)
            if concept_id in seen_codelists:
                continue
            seen_codelists.add(concept_id)
            codelist_id = uuid5(
                REGISTRY_NAMESPACE, f"terminology-codelist:{release.id}:{concept_id}"
            )
            extensible_value = payload.get("extensible")
            codelist_synonyms = payload.get("synonyms", [])
            codelist_rows.append(
                {
                    "id": codelist_id,
                    "release_id": release.id,
                    "code": concept_id,
                    "concept_id": concept_id,
                    "name": str(name),
                    "submission_value": str(submission_value),
                    "definition": (
                        payload.get("definition")
                        if isinstance(payload.get("definition"), str)
                        else None
                    ),
                    "preferred_term": (
                        payload.get("preferredTerm")
                        if isinstance(payload.get("preferredTerm"), str)
                        else None
                    ),
                    "synonyms": (
                        [item for item in codelist_synonyms if isinstance(item, str)]
                        if isinstance(codelist_synonyms, list)
                        else []
                    ),
                    "extensible": extensible_value is True
                    or str(extensible_value).lower() == "true",
                }
            )
            terms = payload.get("terms", [])
            if not isinstance(terms, list):
                continue
            for term in terms:
                if not isinstance(term, dict):
                    continue
                term_concept_id = term.get("conceptId")
                term_submission_value = term.get("submissionValue")
                if not isinstance(term_concept_id, str) or not isinstance(
                    term_submission_value, str
                ):
                    continue
                preferred_term = term.get("preferredTerm")
                term_synonyms = term.get("synonyms", [])
                term_rows.append(
                    {
                        "id": uuid5(
                            REGISTRY_NAMESPACE,
                            f"terminology-term:{codelist_id}:{term_concept_id}",
                        ),
                        "codelist_id": codelist_id,
                        "code": term_concept_id,
                        "concept_id": term_concept_id,
                        "submission_value": term_submission_value,
                        "decode": (
                            preferred_term
                            if isinstance(preferred_term, str)
                            else term_submission_value
                        ),
                        "definition": (
                            term.get("definition")
                            if isinstance(term.get("definition"), str)
                            else None
                        ),
                        "preferred_term": (
                            preferred_term if isinstance(preferred_term, str) else None
                        ),
                        "synonyms": (
                            [item for item in term_synonyms if isinstance(item, str)]
                            if isinstance(term_synonyms, list)
                            else []
                        ),
                        "status": "active",
                    }
                )
    if codelist_rows:
        session.execute(insert(TerminologyCodelist), codelist_rows)
    batch_size = 5_000
    for offset in range(0, len(term_rows), batch_size):
        session.execute(insert(TerminologyTerm), term_rows[offset : offset + batch_size])


def publish_library_selection(
    storage: ObjectStorage, selection: FetchedCdiscLibrarySelection
) -> None:
    """Publish fetched resources before any registry transaction is opened."""

    for resource in selection.manifest.resources:
        publish_verified_asset(
            storage,
            selection.local_files[resource.canonical_href],
            resource.sha256,
            resource.media_type,
        )


def register_library_selection_rows(
    session: Session,
    selection: CdiscLibrarySelectionManifest,
    local_files: dict[str, Path],
    repository_root: Path,
) -> None:
    """Register one on-demand release after its resources have been published."""

    if selection.resource_count != len(selection.resources) or not selection.resources:
        raise ValueError("CDISC Library selection inventory is incomplete")
    if selection.selected_href not in {
        resource.canonical_href for resource in selection.resources
    }:
        raise ValueError("CDISC Library selection does not contain its selected root")
    hrefs = [resource.canonical_href for resource in selection.resources]
    if len(hrefs) != len(set(hrefs)):
        raise ValueError("CDISC Library selection contains duplicate canonical hrefs")
    if set(hrefs) != set(local_files):
        raise ValueError("CDISC Library selection staging files do not match its inventory")

    overall = selection.library_updated["overall"]
    provenance: dict[str, object] = {
        "source": "CDISC Library",
        "acquisition_mode": "on_demand_selection",
        "library_base_url": selection.library_base_url,
        "selected_href": selection.selected_href,
        "library_updated": selection.library_updated,
        "captured_at": selection.captured_at.isoformat(),
        "resource_count": selection.resource_count,
    }
    categories = {resource.category for resource in selection.resources}
    if len(categories) != 1:
        raise ValueError("one CDISC Library selection cannot mix standards and terminology")
    if categories == {"terminology"}:
        groups: defaultdict[tuple[str, str, str], list[CdiscLibrarySelectionResource]] = (
            defaultdict(list)
        )
        for resource in selection.resources:
            groups[_terminology_group(resource, overall)].append(resource)
        if len(groups) != 1:
            raise ValueError("selected terminology graph resolved to more than one release")
        identity, resources = next(iter(groups.items()))
        if identity[0] == "CDISC_CT_CATALOG":
            raise ValueError("selected href is not a supported terminology package release")
        _register_terminology_group(
            session,
            identity=identity,
            resources=resources,
            repository_root=repository_root,
            provenance=provenance,
            local_files=local_files,
        )
        return

    standard_groups: defaultdict[
        tuple[str, str, str, str, str, str], list[CdiscLibrarySelectionResource]
    ] = defaultdict(list)
    for resource in selection.resources:
        standard_groups[_standard_group(resource, overall)].append(resource)
    if len(standard_groups) != 1:
        raise ValueError("selected standard graph resolved to more than one release")
    standard_identity, standard_resources = next(iter(standard_groups.items()))
    if standard_identity[0] == "CDISC_LIBRARY_CATALOG":
        raise ValueError("selected href is not a supported standard product release")
    _register_standard_group(
        session,
        identity=standard_identity,
        resources=standard_resources,
        provenance=provenance,
    )
