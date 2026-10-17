"""Create or update an Aurinara Cloudflare DNS-only CloudFront CNAME."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable
from typing import Any
from urllib import error, parse, request


class CloudflareDnsError(RuntimeError):
    """Raised when stack outputs or Cloudflare DNS state are invalid."""


Response = dict[str, Any]
StackOutputReader = Callable[[str, str], str]
Requester = Callable[[str, str, str, Response | None], Response]


def read_stack_output(stack_name: str, output_key: str) -> str:
    """Read one non-empty output from an environment CloudFormation stack."""
    completed = subprocess.run(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--query",
            f"Stacks[0].Outputs[?OutputKey=='{output_key}'].OutputValue",
            "--output",
            "text",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value or value == "None":
        raise CloudflareDnsError(f"Stack output {output_key} is missing")
    return value


def cloudflare_request(
    method: str,
    url: str,
    api_token: str,
    payload: Response | None = None,
) -> Response:
    """Call the Cloudflare v4 API without logging the bearer token."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    api_request = request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:  # noqa: S310
            result = json.load(response)
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise CloudflareDnsError(
            f"Cloudflare API returned HTTP {exc.code}: {response_body}"
        ) from exc
    except error.URLError as exc:
        raise CloudflareDnsError(f"Cloudflare API request failed: {exc.reason}") from exc

    if not isinstance(result, dict) or result.get("success") is not True:
        details = result.get("errors") if isinstance(result, dict) else "invalid JSON object"
        raise CloudflareDnsError(f"Cloudflare rejected the DNS operation: {details}")
    return result


def configure_dns(
    stack_name: str,
    zone_id: str,
    api_token: str,
    *,
    output_reader: StackOutputReader = read_stack_output,
    requester: Requester = cloudflare_request,
) -> str:
    """Upsert the application hostname as a non-proxied CloudFront CNAME."""
    application_url = output_reader(stack_name, "ApplicationUrl")
    parsed_url = parse.urlparse(application_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise CloudflareDnsError("Stack output ApplicationUrl is not an HTTPS URL")
    record_name = parsed_url.hostname

    target = output_reader(stack_name, "CloudFrontDistributionDomainName").rstrip(".")
    if re.fullmatch(r"[a-z0-9-]+\.cloudfront\.net", target) is None:
        raise CloudflareDnsError(
            "Stack output CloudFrontDistributionDomainName is invalid"
        )

    api_base = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    query = parse.urlencode({"type": "CNAME", "name": record_name})
    listed = requester("GET", f"{api_base}?{query}", api_token, None)
    records = listed.get("result")
    if not isinstance(records, list):
        raise CloudflareDnsError("Cloudflare DNS lookup returned an invalid result")
    if len(records) > 1:
        raise CloudflareDnsError(
            f"Cloudflare returned multiple CNAME records for {record_name}"
        )

    payload: Response = {
        "type": "CNAME",
        "name": record_name,
        "content": target,
        "ttl": 1,
        "proxied": False,
        "comment": f"Managed by Aurinara stack {stack_name}",
    }
    if records:
        record_id = records[0].get("id") if isinstance(records[0], dict) else None
        if not isinstance(record_id, str) or not record_id:
            raise CloudflareDnsError("Existing Cloudflare CNAME has no record ID")
        applied = requester("PUT", f"{api_base}/{record_id}", api_token, payload)
        operation = "updated"
    else:
        applied = requester("POST", api_base, api_token, payload)
        operation = "created"

    applied_record = applied.get("result")
    if not isinstance(applied_record, dict) or applied_record.get("proxied") is not False:
        raise CloudflareDnsError("Cloudflare did not apply a DNS-only CNAME")
    return f"Cloudflare DNS-only CNAME {record_name} -> {target} {operation}"


def main() -> None:
    """Run the Cloudflare DNS reconciliation command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stack_name")
    args = parser.parse_args()
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not zone_id or not api_token:
        raise CloudflareDnsError(
            "CLOUDFLARE_ZONE_ID and CLOUDFLARE_API_TOKEN are required"
        )
    print(configure_dns(args.stack_name, zone_id, api_token))


if __name__ == "__main__":
    main()
