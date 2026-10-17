#!/bin/sh
set -eu

language="$1"
shift
workspace="${AURINARA_WORKSPACE:-/workspace}"
result_dir="$workspace/.runner"
mkdir -p "$result_dir"
chmod 700 "$result_dir"
cd "$workspace"

set +e
if [ "$language" = "python" ]; then
  python -I "$@" >"$result_dir/stdout" 2>"$result_dir/stderr"
  exit_code=$?
elif [ "$language" = "r" ]; then
  Rscript --vanilla "$@" >"$result_dir/stdout" 2>"$result_dir/stderr"
  exit_code=$?
else
  printf '%s\n' "unsupported runner language" >"$result_dir/stderr"
  exit_code=64
fi
set -e
printf '%s\n' "$exit_code" >"$result_dir/exit-code"
exit "$exit_code"
