from __future__ import annotations

from typing import Any

import pytest

from scripts.cloudflare_dns import CloudflareDnsError, configure_dns


def _outputs(_: str, key: str) -> str:
    return {
        "ApplicationUrl": "https://staging.example.com",
        "CloudFrontDistributionDomainName": "d123example.cloudfront.net",
    }[key]


def test_configure_dns_creates_dns_only_cname() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def requester(
        method: str, url: str, _: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        calls.append((method, url, payload))
        if method == "GET":
            return {"success": True, "result": []}
        return {"success": True, "result": {"proxied": False}}

    message = configure_dns(
        "aurinara-staging",
        "zone-id",
        "secret-token",
        output_reader=_outputs,
        requester=requester,
    )

    assert message.endswith("created")
    assert calls[1][0] == "POST"
    assert calls[1][2] == {
        "type": "CNAME",
        "name": "staging.example.com",
        "content": "d123example.cloudfront.net",
        "ttl": 1,
        "proxied": False,
        "comment": "Managed by Aurinara stack aurinara-staging",
    }


def test_configure_dns_updates_existing_cname() -> None:
    calls: list[tuple[str, str]] = []

    def requester(
        method: str, url: str, _: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        calls.append((method, url))
        if method == "GET":
            return {"success": True, "result": [{"id": "record-id"}]}
        assert payload is not None and payload["proxied"] is False
        return {"success": True, "result": {"proxied": False}}

    message = configure_dns(
        "aurinara-staging",
        "zone-id",
        "secret-token",
        output_reader=_outputs,
        requester=requester,
    )

    assert message.endswith("updated")
    assert calls[1] == (
        "PUT",
        "https://api.cloudflare.com/client/v4/zones/zone-id/dns_records/record-id",
    )


def test_configure_dns_rejects_non_cloudfront_target() -> None:
    def invalid_outputs(_: str, key: str) -> str:
        if key == "ApplicationUrl":
            return "https://staging.example.com"
        return "untrusted.example.net"

    with pytest.raises(CloudflareDnsError, match="DistributionDomainName is invalid"):
        configure_dns(
            "aurinara-staging",
            "zone-id",
            "secret-token",
            output_reader=invalid_outputs,
        )


def test_configure_dns_rejects_proxied_result() -> None:
    def requester(
        method: str, url: str, _: str, payload: dict[str, Any] | None
    ) -> dict[str, Any]:
        del url, payload
        if method == "GET":
            return {"success": True, "result": []}
        return {"success": True, "result": {"proxied": True}}

    with pytest.raises(CloudflareDnsError, match="DNS-only CNAME"):
        configure_dns(
            "aurinara-staging",
            "zone-id",
            "secret-token",
            output_reader=_outputs,
            requester=requester,
        )
