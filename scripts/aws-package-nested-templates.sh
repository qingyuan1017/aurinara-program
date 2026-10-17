#!/usr/bin/env bash
set -euo pipefail

template_file=${1:?missing parent template path}
bucket=${2:?missing S3 template bucket}
prefix=${3:?missing S3 key prefix}
output_file=${4:?missing packaged template path}
region=${AWS_REGION:-us-east-1}
normalized_path=

cleanup() {
  [[ -z "$normalized_path" ]] || rm -f -- "$normalized_path"
}
trap cleanup EXIT

template_dir=$(cd "$(dirname "$template_file")" && pwd)
cp "$template_file" "$output_file"

mapfile -t nested_templates < <(
  sed -n -E "s/^[[:space:]]*TemplateURL:[[:space:]]*['\"]?([^'\"[:space:]]+)['\"]?[[:space:]]*$/\1/p" "$template_file"
)

((${#nested_templates[@]} > 0)) || {
  echo "no nested TemplateURL entries found in $template_file" >&2
  exit 1
}

for nested_template in "${nested_templates[@]}"; do
  source_path="$template_dir/$nested_template"
  [[ -f "$source_path" ]] || {
    echo "nested template does not exist: $source_path" >&2
    exit 1
  }

  key="${prefix%/}/$nested_template"
  normalized_path=$(mktemp)
  aws cloudformation package \
    --template-file "$source_path" \
    --s3-bucket "$bucket" \
    --s3-prefix "${prefix%/}/artifacts/$nested_template" \
    --output-template-file "$normalized_path" >/dev/null
  aws s3 cp "$normalized_path" "s3://$bucket/$key" --only-show-errors
  rm -f -- "$normalized_path"
  normalized_path=
  template_url="https://$bucket.s3.$region.amazonaws.com/$key"
  sed -i -E "s|TemplateURL:[[:space:]]*['\"]?$nested_template['\"]?|TemplateURL: $template_url|" "$output_file"
done

