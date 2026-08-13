#!/usr/bin/env bash
#
# psql.sh <service-name> [sql]
#
# Opens a psql session against a project's database on the shared RDS.
#
# The platform database is not publicly accessible, which is the correct
# posture but means you cannot psql straight from a laptop. This runs psql as a
# one-shot Fargate task inside the VPC and streams the output back, so you get
# database access without ever exposing the instance or allowlisting an IP.
#
# With no SQL argument it prints the connection details and runs \dt.
#
set -euo pipefail

SERVICE_NAME="${1:-}"
SQL="${2:-\\dt}"
REGION="${AWS_REGION:-us-east-1}"
CLUSTER="${ECS_CLUSTER_NAME:-default}"

if [ -z "$SERVICE_NAME" ]; then
  echo "usage: $0 <service-name> [sql]" >&2
  exit 64
fi

SECRET_ID="${SERVICE_NAME}/database-url"

if ! aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$REGION" >/dev/null 2>&1; then
  echo "error: no secret ${SECRET_ID}. Has this project been deployed?" >&2
  exit 69
fi

VPC_ID="$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=${PLATFORM_VPC_NAME:-platform-vpc}" \
  --query 'Vpcs[0].VpcId' --output text --region "$REGION")"

SUBNETS="$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=tag:Tier,Values=public" \
  --query 'Subnets[].SubnetId' --output text --region "$REGION" | tr '\t' ',')"

SG="$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=tag:Name,Values=${PLATFORM_EGRESS_SG_NAME:-platform-ecs-egress}" \
  --query 'SecurityGroups[0].GroupId' --output text --region "$REGION")"

echo "==> running psql in ${CLUSTER} (vpc ${VPC_ID})"
echo "==> sql: ${SQL}"

# Reuse the project's own db-provisioner task definition family; it already has
# psql and the right network placement. We override the command only.
TASK_DEF="${SERVICE_NAME}-db-provisioner"

OVERRIDES=$(cat <<JSON
{
  "containerOverrides": [{
    "name": "provisioner",
    "command": ["sh","-c","psql \"\$DATABASE_URL\" -c \"${SQL}\""],
    "secrets": [{"name":"DATABASE_URL","valueFrom":"$(aws secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$REGION" --query ARN --output text)"}]
  }]
}
JSON
)

TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --region "$REGION" \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
  --overrides "$OVERRIDES" \
  --query 'tasks[0].taskArn' --output text)"

echo "==> task ${TASK_ARN##*/}, waiting..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION"

echo "==> output:"
aws logs tail "/ecs/${SERVICE_NAME}-db-provisioner" --since 5m --region "$REGION"
