#!/bin/bash
# Registers a new revision of a migrate task definition pointing at the
# given image, runs it once, waits for it to stop, and fails loudly if the
# container's exit code is non-zero. Used by .github/workflows/deploy.yml's
# `migrate` job — ECS RunTask overrides can't change a task definition's
# image, so a fresh revision is required before every run (see
# infra/terraform/modules/ecs-migrate-task).
set -euo pipefail

family="$1"       # e.g. exam-migrate
image="$2"        # full ECR image URI:tag
subnets="$3"       # comma-separated private subnet IDs
security_group="$4"

echo "==> Registering a new revision of $family with image $image"
current_def=$(aws ecs describe-task-definition --task-definition "$family" --query 'taskDefinition')
new_def=$(echo "$current_def" | jq --arg IMAGE "$image" '
  .containerDefinitions[0].image = $IMAGE
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
        .compatibilities, .registeredAt, .registeredBy, .deregisteredAt)
')
new_arn=$(aws ecs register-task-definition --cli-input-json "$new_def" \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "==> Registered $new_arn"

echo "==> Running $family"
task_arn=$(aws ecs run-task \
  --cluster "$ECS_CLUSTER_NAME" \
  --task-definition "$new_arn" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)
echo "==> Started $task_arn — waiting for it to stop"

aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER_NAME" --tasks "$task_arn"

exit_code=$(aws ecs describe-tasks --cluster "$ECS_CLUSTER_NAME" --tasks "$task_arn" \
  --query 'tasks[0].containers[0].exitCode' --output text)

if [ "$exit_code" != "0" ]; then
  echo "::error::$family failed (container exit code $exit_code) — see the task's CloudWatch logs (/ecs/$family)"
  exit 1
fi

echo "==> $family completed successfully"
