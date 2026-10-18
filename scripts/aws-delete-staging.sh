#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: aws-delete-staging.sh aurinara-staging}
[[ "$stack_name" == aurinara-staging ]] || {
  echo "Refusing to delete unexpected stack: $stack_name" >&2
  exit 1
}

environment=$(aws cloudformation describe-stacks --stack-name "$stack_name" \
  --query "Stacks[0].Parameters[?ParameterKey=='Environment'].ParameterValue" --output text)
[[ "$environment" == staging ]] || {
  echo "Refusing to delete a non-staging stack" >&2
  exit 1
}

aws cloudformation update-termination-protection --no-enable-termination-protection --stack-name "$stack_name"
aws cloudformation delete-stack --stack-name "$stack_name"
aws cloudformation wait stack-delete-complete --stack-name "$stack_name"
