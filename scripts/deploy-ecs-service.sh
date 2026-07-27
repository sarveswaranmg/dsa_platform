#!/bin/bash
# Registers a new task definition revision pointing at the given image and
# rolls the ECS service to it, waiting for the deployment to stabilize.
# Used by .github/workflows/deploy.yml's `deploy-services` job.
set -euo pipefail

service="$1"  # gateway, exam, or question — matches the task def family
image="$2"    # full ECR image URI:tag
cluster="$3"

echo "==> Registering a new revision of $service with image $image"
current_def=$(aws ecs describe-task-definition --task-definition "$service" --query 'taskDefinition')
new_def=$(echo "$current_def" | jq --arg IMAGE "$image" '
  .containerDefinitions[0].image = $IMAGE
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
        .compatibilities, .registeredAt, .registeredBy, .deregisteredAt)
')
new_arn=$(aws ecs register-task-definition --cli-input-json "$new_def" \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "==> Registered $new_arn"

echo "==> Updating service $service"
aws ecs update-service \
  --cluster "$cluster" \
  --service "$service" \
  --task-definition "$new_arn" \
  --force-new-deployment \
  > /dev/null

echo "==> Waiting for $service to stabilize"
aws ecs wait services-stable --cluster "$cluster" --services "$service"

echo "==> $service is stable on $new_arn"
