set -eu

# Launches the one-shot provisioning task and blocks until it finishes.
#
# This only talks to the AWS API, never to the database, so it runs unchanged
# from a laptop, from GitHub Actions, or from a colleague's machine. There is
# no IP allowlist and the RDS instance stays private.

echo "[run-provisioner] launching task in ${CLUSTER}"

TASK_ARN=$(aws ecs run-task \
  --cluster "${CLUSTER}" \
  --task-definition "${TASK_DEFINITION}" \
  --launch-type FARGATE \
  --region "${AWS_REGION}" \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUPS}],assignPublicIp=${ASSIGN_PUBLIC_IP}}" \
  --query 'tasks[0].taskArn' \
  --output text)

if [ -z "${TASK_ARN}" ] || [ "${TASK_ARN}" = "None" ]; then
  echo "[run-provisioner] ERROR: task failed to start" >&2
  exit 1
fi

echo "[run-provisioner] task ${TASK_ARN##*/} started, waiting..."

aws ecs wait tasks-stopped \
  --cluster "${CLUSTER}" \
  --tasks "${TASK_ARN}" \
  --region "${AWS_REGION}"

EXIT_CODE=$(aws ecs describe-tasks \
  --cluster "${CLUSTER}" \
  --tasks "${TASK_ARN}" \
  --region "${AWS_REGION}" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)

STOP_REASON=$(aws ecs describe-tasks \
  --cluster "${CLUSTER}" \
  --tasks "${TASK_ARN}" \
  --region "${AWS_REGION}" \
  --query 'tasks[0].stoppedReason' \
  --output text 2>/dev/null || echo "unknown")

if [ "${EXIT_CODE}" != "0" ]; then
  echo "[run-provisioner] ERROR: provisioner exited ${EXIT_CODE} (${STOP_REASON})" >&2
  echo "[run-provisioner] logs: aws logs tail ${LOG_GROUP} --since 10m" >&2
  exit 1
fi

echo "[run-provisioner] database provisioned successfully"
