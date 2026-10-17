#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: aws-run-migration.sh STACK_NAME}

output() {
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

cluster=$(output ClusterName)
task_definition=$(output MigrationTaskDefinitionArn)
subnets=$(output AppSubnetIds)
security_group=$(output WorkerSecurityGroupId)

task_arn=$(aws ecs run-task \
  --cluster "$cluster" \
  --task-definition "$task_definition" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' \
  --output text)

if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "Migration task did not start" >&2
  exit 1
fi

aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"
exit_code=$(aws ecs describe-tasks \
  --cluster "$cluster" \
  --tasks "$task_arn" \
  --query 'tasks[0].containers[?name==`migration`].exitCode | [0]' \
  --output text)

if [[ "$exit_code" != "0" ]]; then
  reason=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task_arn" --query 'tasks[0].stoppedReason' --output text)
  echo "Migration task failed with exit code ${exit_code}: ${reason}" >&2
  exit 1
fi
