"""Complete CDISC Library snapshot behavior without network access."""

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from app.cdisc_library_registry import _purposes, _register_terminology_group
from app.integration.cdisc_library import CdiscLibraryResource
from app.standards.library_snapshot import (
    CdiscLibrarySnapshotManifest,
    CdiscLibrarySnapshotResource,
    create_library_snapshot,
)


class FakeLibraryReader:
    """Small cyclic HAL graph covering standard and terminology resources."""

    def __init__(self) -> None:
        self.resources = {
            "/mdr/lastupdated": {
                "overall": "2099-01-01",
                "terminology": "2099-01-01",
            },
            "/mdr/products": {
                "_links": {
                    "self": {"href": "/mdr/products"},
                    "sdtm": {
                        "href": "/mdr/sdtm/sdtm-test-1",
                        "title": "Synthetic SDTM",
                        "type": "Standard",
                    },
                }
            },
            "/mdr/sdtm/sdtm-test-1": {
                "_links": {"self": {"href": "/mdr/sdtm/sdtm-test-1"}},
                "name": "Synthetic SDTM",
            },
            "/mdr/ct/packages": {
                "_links": {
                    "packages": [
                        {
                            "href": "/mdr/ct/packages/synct-2099-01-01",
                            "title": "Synthetic CT",
                            "type": "Terminology",
                        }
                    ]
                }
            },
            "/mdr/ct/packages/synct-2099-01-01": {
                "_links": {
                    "self": {"href": "/mdr/ct/packages/synct-2099-01-01"},
                    "codelists": {"href": "/mdr/ct/packages/synct-2099-01-01/codelists/C900001"},
                }
            },
            "/mdr/ct/packages/synct-2099-01-01/codelists/C900001": {
                "conceptId": "C900001",
                "name": "Synthetic Codelist",
                "submissionValue": "SYN",
                "extensible": "true",
                "terms": [
                    {
                        "conceptId": "C900002",
                        "submissionValue": "VALUE",
                        "preferredTerm": "Synthetic Value",
                    }
                ],
                "_links": {"self": {"href": "/mdr/ct/packages/synct-2099-01-01/codelists/C900001"}},
            },
        }

    def canonical_href(self, href: str) -> str:
        if not href.startswith("/mdr/"):
            raise ValueError("outside MDR")
        return href

    def get(self, href: str) -> CdiscLibraryResource:
        content = self.resources[href]
        return CdiscLibraryResource(
            href=href,
            title="",
            resource_type="",
            content=content,
        )


def test_snapshot_crawls_and_checksums_complete_graph(tmp_path: Path) -> None:
    manifest_path = create_library_snapshot(
        reader=FakeLibraryReader(),
        repository_root=tmp_path,
        library_base_url="https://library.cdisc.org/api",
        max_resources=20,
    )
    manifest = CdiscLibrarySnapshotManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert manifest.resource_count == 6
    assert len({item.canonical_href for item in manifest.resources}) == 6
    assert {item.category for item in manifest.resources} == {"standard", "terminology"}
    for resource in manifest.resources:
        assert (tmp_path / resource.asset_path).is_file()


def test_sdtmig_snapshots_are_selectable_for_the_sdtm_ig_purpose() -> None:
    assert _purposes("SDTMIG") == ["reference_metadata", "sdtm_ig"]
    assert _purposes("SDTM") == ["reference_metadata"]


def test_registration_normalizes_embedded_package_codelists(tmp_path: Path) -> None:
    asset = tmp_path / "terminology" / "package.json"
    asset.parent.mkdir()
    asset.write_text(
        json.dumps(
            {
                "codelists": [
                    {
                        "conceptId": "C900001",
                        "name": "Synthetic Codelist",
                        "submissionValue": "SYN",
                        "extensible": "true",
                        "terms": [
                            {
                                "conceptId": "C900002",
                                "submissionValue": "VALUE",
                                "preferredTerm": "Synthetic Value",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    resource = CdiscLibrarySnapshotResource(
        id=uuid4(),
        category="terminology",
        canonical_href="/mdr/ct/packages/synct-2099-01-01",
        title="Synthetic CT",
        resource_type="Terminology",
        asset_path=asset.relative_to(tmp_path).as_posix(),
        sha256="0" * 64,
    )
    session = MagicMock(spec=Session)
    session.get.return_value = None

    _register_terminology_group(
        session,
        identity=("SYN_CT", "SYN", "synct-2099-01-01"),
        resources=[resource],
        repository_root=tmp_path,
    )

    codelist_rows = session.execute.call_args_list[0].args[1]
    term_rows = session.execute.call_args_list[1].args[1]
    assert codelist_rows[0]["concept_id"] == "C900001"
    assert codelist_rows[0]["extensible"] is True
    assert term_rows[0]["concept_id"] == "C900002"
    assert term_rows[0]["decode"] == "Synthetic Value"
