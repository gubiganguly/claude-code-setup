#!/usr/bin/env bash
#
# bootstrap-image.sh <service-name> [region]
#
# Creates the ECR repository and pushes one throwaway image to it.
#
# WHY THIS EXISTS
# An ECS Express service cannot be created without an image already present in
# its repository, but the repository is created by the same Terraform stack as
# the service. v1 broke that loop with `terraform apply -target=...` twice,
# which HashiCorp documents as an exceptional recovery tool rather than a
# workflow. This script breaks it properly: one command before the apply, then
# a single unqualified `terraform apply` for everything.
#
# The image pushed here is never served. Terraform creates the service pointing
# at it, and the first CI run replaces it with the real build.
#
set -euo pipefail

SERVICE_NAME="${1:-}"
REGION="${2:-${AWS_REGION:-us-east-1}}"

if [ -z "$SERVICE_NAME" ]; then
  echo "usage: $0 <service-name> [region]" >&2
  exit 64
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required and not on PATH" >&2
  exit 69
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: docker daemon is not running" >&2
  exit 69
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPO_URI="${REGISTRY}/${SERVICE_NAME}"
TAG="bootstrap"

echo "==> account ${ACCOUNT_ID}, region ${REGION}"

# Terraform will adopt this repo on the next apply; creating it here first is
# harmless and idempotent.
if aws ecr describe-repositories --repository-names "$SERVICE_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "==> ECR repository ${SERVICE_NAME} already exists"
else
  echo "==> creating ECR repository ${SERVICE_NAME}"
  aws ecr create-repository \
    --repository-name "$SERVICE_NAME" \
    --region "$REGION" \
    --image-scanning-configuration scanOnPush=true \
    >/dev/null
fi

if aws ecr describe-images --repository-name "$SERVICE_NAME" --image-ids imageTag="$TAG" \
     --region "$REGION" >/dev/null 2>&1; then
  echo "==> bootstrap image already present, nothing to do"
  echo "${REPO_URI}:${TAG}"
  exit 0
fi

echo "==> authenticating to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# A minimal image that stays alive and answers any path with 200. It never
# serves traffic, but a container that exits immediately can make the first
# service creation look like a crash loop while you are watching.
cat > "$WORKDIR/Dockerfile" <<'DOCKERFILE'
FROM public.ecr.aws/docker/library/busybox:stable
RUN mkdir -p /www && printf 'bootstrap placeholder\n' > /www/index.html
EXPOSE 3000
CMD ["httpd", "-f", "-p", "3000", "-h", "/www"]
DOCKERFILE

echo "==> building and pushing ${REPO_URI}:${TAG} (linux/amd64)"
# amd64 is mandatory: Fargate is x86_64, and an arm64 image from an Apple
# Silicon machine fails at runtime with "exec format error".
docker buildx build \
  --platform linux/amd64 \
  -t "${REPO_URI}:${TAG}" \
  --push \
  "$WORKDIR"

echo "==> done"
echo "${REPO_URI}:${TAG}"
