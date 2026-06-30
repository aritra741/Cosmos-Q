#!/usr/bin/env bash
# Push COSMOS-Q image to Alibaba Cloud Container Registry (ACR).
#
# Usage:
#   export ACR_NAMESPACE=your-namespace
#   export ACR_REGION=cn-hangzhou        # default
#   export ACR_USERNAME=your-username
#   export ACR_PASSWORD=your-password
#   bash scripts/acr_push.sh [tag]
#
# The image will be tagged as:
#   registry.<region>.aliyuncs.com/<namespace>/cosmos-q:<tag>

set -euo pipefail

REGION="${ACR_REGION:-cn-hangzhou}"
NAMESPACE="${ACR_NAMESPACE:?Set ACR_NAMESPACE}"
TAG="${1:-latest}"
REGISTRY="registry.${REGION}.aliyuncs.com"
IMAGE="${REGISTRY}/${NAMESPACE}/cosmos-q:${TAG}"

echo "→ Logging in to ACR (${REGISTRY})..."
echo "${ACR_PASSWORD:?Set ACR_PASSWORD}" \
  | docker login --username "${ACR_USERNAME:?Set ACR_USERNAME}" \
      --password-stdin "${REGISTRY}"

echo "→ Building image: ${IMAGE}"
docker build -t "${IMAGE}" .

echo "→ Pushing to ACR..."
docker push "${IMAGE}"

echo "✓ Image pushed: ${IMAGE}"
echo ""
echo "Deploy on ECS:"
echo "  docker pull ${IMAGE}"
echo "  docker run -d -p 8765:8765 \\"
echo "    -e COSMOS_QWEN_API_KEY=<key> \\"
echo "    -e COSMOS_PG_DSN=<dsn> \\"
echo "    ${IMAGE}"
