#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: cloudflare-upsert-dns.sh STACK_NAME}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

: "${CLOUDFLARE_API_TOKEN:?}"
: "${CLOUDFLARE_ZONE_ID:?}"

exec python3 "$script_dir/cloudflare_dns.py" "$stack_name"
