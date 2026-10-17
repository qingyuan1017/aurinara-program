#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: aws-deploy-environment.sh STACK_NAME ENVIRONMENT VPC_CIDR DB_CLASS}
environment=${2:?missing environment}
vpc_cidr=${3:?missing VPC CIDR}
database_class=${4:?missing database class}
platform_authorization_mode=${PLATFORM_AUTHORIZATION_MODE:-shadow}
dns_provider=${DNS_PROVIDER:-cloudflare}
hosted_zone_id=${HOSTED_ZONE_ID:-}
alarm_email=${ALARM_EMAIL:-}

: "${APPLICATION_IMAGE:?}"
: "${PYTHON_RUNNER_IMAGE:?}"
: "${R_RUNNER_IMAGE:?}"
: "${BASE_DOMAIN:?}"
: "${CERTIFICATE_ARN:?}"
: "${PLATFORM_STACK_NAME:?}"
: "${CLOUDFORMATION_EXECUTION_ROLE_ARN:?}"

case "$dns_provider" in
  cloudflare) ;;
  route53)
    if [[ -z "$hosted_zone_id" ]]; then
      echo "HOSTED_ZONE_ID is required when DNS_PROVIDER=route53" >&2
      exit 1
    fi
    ;;
  *)
    echo "DNS_PROVIDER must be cloudflare or route53" >&2
    exit 1
    ;;
esac

platform_output() {
  aws cloudformation describe-stacks --stack-name "$PLATFORM_STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
platform_privatelink_service_name=$(platform_output PlatformPrivateLinkServiceName)
vpc_id=$(platform_output VpcId)
vpc_cidr=$(platform_output VpcCidr)
app_subnet_ids=$(platform_output AppSubnetIds)
runner_subnet_ids=$(platform_output RunnerSubnetIds)
data_subnet_ids=$(platform_output DataSubnetIds)
platform_private_url=$(platform_output PlatformPrivateUrl)
platform_public_url=$(platform_output PlatformUrl)
platform_event_bus_name=$(platform_output EventBusName)
shared_identity_key_arn=$(platform_output SharedIdentityKeyArn)
user_pool_id=$(platform_output UserPoolId)
spa_client_id=$(platform_output AurinaraSpaClientId)
jwt_issuer=$(platform_output JwtIssuer)
jwt_jwks_url=$(platform_output JwtJwksUrl)
service_client_id=$(platform_output AurinaraServiceClientId)
service_client_secret_arn=$(platform_output AurinaraServiceClientSecretArn)
service_token_url=$(platform_output TokenUrl)
oidc_end_session_url=$(platform_output LogoutUrl)

current_image=$APPLICATION_IMAGE
activate_services=false
if aws cloudformation describe-stacks --stack-name "$stack_name" >/dev/null 2>&1; then
  current_image=$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Parameters[?ParameterKey=='ApplicationImage'].ParameterValue" \
    --output text)
  activate_services=$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Parameters[?ParameterKey=='ActivateServices'].ParameterValue" \
    --output text)
  [[ "$activate_services" == true ]] || activate_services=false
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
      VpcId="$vpc_id" \
      AppSubnetIds="$app_subnet_ids" \
      RunnerSubnetIds="$runner_subnet_ids" \
      DataSubnetIds="$data_subnet_ids" \
      BaseDomain="$BASE_DOMAIN" \
      DnsProvider="$dns_provider" \
      HostedZoneId="$hosted_zone_id" \
      CertificateArn="$CERTIFICATE_ARN" \
      ApplicationImage="$service_image" \
      MigrationApplicationImage="$migration_image" \
      ActivateServices="$active" \
      PythonRunnerImage="$PYTHON_RUNNER_IMAGE" \
      RRunnerImage="$R_RUNNER_IMAGE" \
      PlatformPrivateLinkServiceName="$platform_privatelink_service_name" \
      PlatformPrivateUrl="$platform_private_url" \
      PlatformAuthorizationMode="$platform_authorization_mode" \
      PlatformPublicUrl="$platform_public_url" \
      PlatformEventBusName="$platform_event_bus_name" \
      SharedIdentityKeyArn="$shared_identity_key_arn" \
      UserPoolId="$user_pool_id" \
      SpaClientId="$spa_client_id" \
      JwtIssuer="$jwt_issuer" \
      JwtJwksUrl="$jwt_jwks_url" \
      ServiceClientId="$service_client_id" \
      ServiceClientSecretArn="$service_client_secret_arn" \
      ServiceTokenUrl="$service_token_url" \
      OidcEndSessionUrl="$oidc_end_session_url" \
      AlarmEmail="$alarm_email" \
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
