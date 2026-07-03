#!/usr/bin/env bash
set -euo pipefail

IMAGE_PREFIX="${IMAGE_PREFIX:-spiffe-token-exchange-demo}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
KIND_CLUSTER="${KIND_CLUSTER:-kind}"

services=(
  "portal"
  "agent"
  "mcp"
)

targets=(
  "portal"
  "agent"
  "mcp"
)

echo "Building Docker images:"
echo "  ${IMAGE_PREFIX}/portal:${IMAGE_TAG}"
echo "  ${IMAGE_PREFIX}/agent:${IMAGE_TAG}"
echo "  ${IMAGE_PREFIX}/mcp:${IMAGE_TAG}"
echo

for i in "${!services[@]}"; do
  service="${services[$i]}"
  target="${targets[$i]}"
  image="${IMAGE_PREFIX}/${service}:${IMAGE_TAG}"
  docker build --target "${target}" -t "${image}" .
done

echo
echo "Loading images into kind cluster '${KIND_CLUSTER}'..."
for service in "${services[@]}"; do
  image="${IMAGE_PREFIX}/${service}:${IMAGE_TAG}"
  kind load docker-image "${image}" --name "${KIND_CLUSTER}"
done

echo
echo "Build and kind image load complete."
