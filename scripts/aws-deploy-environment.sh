#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: aws-deploy-environment.sh STACK_NAME ENVIRONMENT VPC_CIDR DB_CLASS}
environment=${2:?missing environment}
vpc_cidr=${3:?missing VPC CIDR}
database_class=${4:?missing database class}
platform_authorization_mode=${PLATFORM_AUTHORIZATION_MODE:-shadow}

: "${APPLICATION_IMAGE:?}"
: "${PYTHON_RUNNER_IMAGE:?}"
: "${R_RUNNER_IMAGE:?}"
: "${BASE_DOMAIN:?}"
: "${HOSTED_ZONE_ID:?}"
: "${CERTIFICATE_ARN:?}"
: "${COGNITO_DOMAIN_PREFIX:?}"
: "${SES_SOURCE_ARN:?}"
: "${COGNITO_FROM_ADDRESS:?}"
: "${PLATFORM_PRIVATELINK_SERVICE_NAME:?}"
: "${PLATFORM_PRIVATE_URL:?}"
: "${PLATFORM_PUBLIC_URL:?}"
: "${PLATFORM_PUBLISHER_PRINCIPAL_ARN:?}"
: "${ALARM_EMAIL:?}"
: "${CLOUDFORMATION_EXECUTION_ROLE_ARN:?}"

current_image=$APPLICATION_IMAGE
activate_services=false
if aws cloudformation describe-stacks --stack-name "$stack_name" >/dev/null 2>&1; then
  current_image=$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Parameters[?ParameterKey=='ApplicationImage'].ParameterValue" \
    --output text)
  activate_services=true
fi

deploy() {
  local service_image=$1
  local migration_image=$2
  local active=$3
  aws cloudformation deploy \
    --stack-name "$stack_name" \
    --template-file packaged.yaml \
    --capabilities CAPABILITY_NAMED_IAM \
    --role-arn "$CLOUDFORMATION_EXECUTION_ROLE_ARN" \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
      Environment="$environment" \
      VpcCidr="$vpc_cidr" \
      BaseDomain="$BASE_DOMAIN" \
      HostedZoneId="$HOSTED_ZONE_ID" \
      CertificateArn="$CERTIFICATE_ARN" \
      CognitoDomainPrefix="$COGNITO_DOMAIN_PREFIX" \
      SesSourceArn="$SES_SOURCE_ARN" \
      CognitoFromAddress="$COGNITO_FROM_ADDRESS" \
      ApplicationImage="$service_image" \
      MigrationApplicationImage="$migration_image" \
      ActivateServices="$active" \
      PythonRunnerImage="$PYTHON_RUNNER_IMAGE" \
      RRunnerImage="$R_RUNNER_IMAGE" \
      PlatformPrivateLinkServiceName="$PLATFORM_PRIVATELINK_SERVICE_NAME" \
      PlatformPrivateUrl="$PLATFORM_PRIVATE_URL" \
      PlatformAuthorizationMode="$platform_authorization_mode" \
      PlatformPublicUrl="$PLATFORM_PUBLIC_URL" \
      PlatformPublisherPrincipalArn="$PLATFORM_PUBLISHER_PRINCIPAL_ARN" \
      AlarmEmail="$ALARM_EMAIL" \
      DatabaseInstanceClass="$database_class"
}

# Phase one registers the new migration task while existing services retain their
# old digest. A first deployment creates services at desired count zero.
deploy "$current_image" "$APPLICATION_IMAGE" "$activate_services"
bash scripts/aws-run-migration.sh "$stack_name"

# Only a successful migration allows the service task definitions to receive the
# new application digest.
deploy "$APPLICATION_IMAGE" "$APPLICATION_IMAGE" true

drift_id=$(aws cloudformation detect-stack-drift --stack-name "$stack_name" --query StackDriftDetectionId --output text)
aws cloudformation wait stack-drift-detection-complete --stack-drift-detection-id "$drift_id"
drift_status=$(aws cloudformation describe-stack-drift-detection-status \
  --stack-drift-detection-id "$drift_id" \
  --query StackDriftStatus \
  --output text)
if [[ "$drift_status" != "IN_SYNC" ]]; then
  echo "Stack drift status is ${drift_status}" >&2
  exit 1
fi
