#!/usr/bin/env bash
set -euo pipefail

LOCAL_MANIFEST="${LOCAL_MANIFEST:-deploy/k8s/local.yaml}"
NAMESPACE="${NAMESPACE:-spiffe-token-exchange-demo}"

if [[ ! -f "${LOCAL_MANIFEST}" ]]; then
  echo "Local manifest not found: ${LOCAL_MANIFEST}"
  echo "Create it with:"
  echo "  cp deploy/k8s/base.yaml ${LOCAL_MANIFEST}"
  exit 1
fi

echo "Applying ${LOCAL_MANIFEST}..."
kubectl apply -f "${LOCAL_MANIFEST}"

echo
echo "Restarting deployments in namespace '${NAMESPACE}'..."
kubectl rollout restart deployment/portal deployment/agent deployment/mcp -n "${NAMESPACE}"

echo
kubectl rollout status deployment/portal -n "${NAMESPACE}"
kubectl rollout status deployment/agent -n "${NAMESPACE}"
kubectl rollout status deployment/mcp -n "${NAMESPACE}"

echo
echo "Deploy complete."
