# Configuration

This page includes configuration guidelines, not a full configuration tutorial. It starts from a running and configured local kind cluster, with SPIRE installed. The demo relies on Kubernetes, SPIRE, and PingFederate for the real token-exchange path; it is not a local-only development workflow.

## Starting Assumptions

- A kind cluster exists and `kubectl` is already pointed at it.
- SPIRE is installed in the cluster with the SPIFFE CSI driver available as `csi.spiffe.io`.
- The SPIRE controller manager accepts `ClusterSPIFFEID` resources with class name `spire-spire`.
- PingFederate is reachable from the kind cluster.
- Docker, kind, kubectl, and Python 3.12 or newer are available on the workstation.

The default local examples use:

```text
KIND_CLUSTER=kind
NAMESPACE=spiffe-token-exchange-demo
SPIFFE_TRUST_DOMAIN=ping.demo
SPIFFE_ENDPOINT_SOCKET=/spiffe-workload-api/spire-agent.sock
SPIFFE_JWT_SVID_AUDIENCE=pingfederate-token-exchange
PORTAL_ORIGIN=http://localhost:3000
PORTAL_REDIRECT_URI=http://localhost:3000/callback
PINGFEDERATE_DISCOVERY_URI=https://host.docker.internal:9031/.well-known/openid-configuration
```

Use `host.docker.internal` when PingFederate runs on the Mac host and the workloads run inside kind. Use the in-cluster or routable PingFederate URL when PingFederate runs elsewhere.

## Local kind Routing

The kind demo does not install or assume an ingress controller. The Kubernetes services are plain ClusterIP services, so external routes are intentionally configured manually:

- Browser to portal: use `kubectl port-forward service/portal 3000:3000 -n spiffe-token-exchange-demo`, then open `http://localhost:3000`.
- Workloads to PingFederate on the Mac host: use `https://host.docker.internal:9031` in `OIDC_DISCOVERY_URI`, or another address that resolves from inside kind pods.
- Browser to PingFederate: the authorization endpoint advertised by PingFederate must resolve from the Mac browser. If PingFederate advertises a custom host such as `pf.local`, add the matching entry to the Mac hosts file or use a DNS name that already resolves.
- PingFederate to SPIRE OIDC Discovery JWKS: PingFederate must be able to reach and trust the JWKS endpoint you configure for JWT-SVID validation. In this demo that route is outside the Kubernetes manifest. You can use a manually routable OIDC discovery URL, a hosts-file entry, a static JWKS configured in PingFederate, or a separately managed ingress/load balancer if your environment provides one.

Do not add an Ingress resource to this demo unless you also install and document the ingress controller. The default local access path is port-forward plus explicit host/DNS routing for PingFederate and SPIRE OIDC discovery.

## Repository Setup

Install the Python backend dependencies from the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create the ignored local manifest from the generic template:

```bash
cp deploy/k8s/base.yaml deploy/k8s/local.yaml
```

Edit `deploy/k8s/local.yaml` for the local cluster, PingFederate issuer, browser client, trust domain, image names, and portal origin. The local manifest is ignored by git so machine-specific values stay out of source control.

## Kubernetes Manifest Values

The generic deployment template is `deploy/k8s/base.yaml`. For local kind work, edit `deploy/k8s/local.yaml` and keep these values consistent:

| ConfigMap key | Local kind value | Purpose |
| --- | --- | --- |
| `AGENT_URL` | `http://agent:3001` | Portal-to-agent service URL inside Kubernetes. |
| `MCP_URL` | `http://mcp:3002/mcp` | Agent-to-MCP service URL inside Kubernetes. |
| `MCP_ALLOWED_HOSTS` | `mcp:* localhost:* 127.0.0.1:*` | Host headers accepted by the MCP SDK DNS rebinding protection. Include the Kubernetes service host used by `MCP_URL`. |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Portal API CORS allowlist for the browser origin used through port-forwarding. |
| `OIDC_DISCOVERY_URI` | `https://host.docker.internal:9031/.well-known/openid-configuration` | PingFederate discovery endpoint as seen from pods. |
| `OIDC_CLIENT_ID` | browser SPA client ID | Public browser login client used by the SPA. |
| `OIDC_REDIRECT_URI` | `http://localhost:3000/callback` | Redirect URI registered on the browser SPA client. |
| `OIDC_SCOPES` | `openid profile portal-api:chat customer:profile:read customer:payments:read` | Scopes requested by browser login. The initial user token carries the customer permissions so PingFederate can enforce same-or-narrower token exchange. |
| `MCP_AUDIENCE` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp` | MCP resource value sent to PingFederate during token exchange and expected in the issued MCP token `aud` claim. |
| `API_OAUTH_CLIENT_ID` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal` | Token-exchange client ID used by the portal workload. The portal API also expects browser tokens to use this value as their `aud` claim. |
| `AGENT_OAUTH_CLIENT_ID` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | Token-exchange client ID used by the agent workload. The portal also uses this as the token exchange resource for the agent, and the agent expects issued tokens to use this value as their `aud` claim. |
| `AGENT_TOKEN_EXCHANGE_SCOPE` | `customer:profile:read customer:payments:read` | Scopes requested by the portal for the agent token. |
| `MCP_TOKEN_EXCHANGE_SCOPE` | `customer:profile:read customer:payments:read` | Same customer scopes requested by the agent for the MCP token. |
| `SPIFFE_TRUST_DOMAIN` | `ping.demo` | SPIFFE trust domain used by SPIRE and PingFederate policy. |
| `SPIFFE_ENDPOINT_SOCKET` | `/spiffe-workload-api/spire-agent.sock` | Mounted SPIFFE Workload API socket path. |
| `SPIFFE_JWT_SVID_AUDIENCE` | `pingfederate-token-exchange` | JWT-SVID audience PingFederate expects when validating actor tokens. |
| `NODE_TLS_REJECT_UNAUTHORIZED` | `1` | Keep TLS verification enabled. The name is retained for manifest compatibility; Python services treat `0` as `verify=False`. Use trusted CA injection instead of disabling TLS verification. |

If PingFederate uses a local or self-signed TLS certificate, the Python containers must trust that CA. Keep the PingFederate issuer in discovery metadata identical to the issuer claim in tokens the services validate.

## SPIRE Configuration

The manifest creates `ClusterSPIFFEID` resources for the portal, agent, and MCP pods. With trust domain `ping.demo`, the expected workload IDs are:

```text
spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal
spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent
spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp
```

Confirm your SPIRE installation matches the manifest assumptions:

```bash
kubectl get csidriver csi.spiffe.io
kubectl get crd clusterspiffeids.spire.spiffe.io
kubectl get pods -A | grep -i spire
```

After deployment, confirm the demo `ClusterSPIFFEID` resources exist:

```bash
kubectl get clusterspiffeid
```

The portal and agent need JWT-SVIDs because they call PingFederate token exchange. The MCP workload has a SPIFFE identity for completeness and future expansion, but it does not call token exchange in the current flow.

## PingFederate Configuration

PingFederate must provide three things for this demo:

1. Browser Authorization Code + PKCE login for the SPA.
2. JWT access tokens with audiences and scopes that match the services.
3. RFC 8693 token exchange where the subject token is an OAuth access token and the actor token is a SPIRE JWT-SVID.

### Browser SPA Client

Create a public browser client for the portal UI:

- Client authentication: `none`.
- Grant type: Authorization Code.
- PKCE: required.
- Redirect URI: `http://localhost:3000/callback` for port-forwarded local kind access.
- Allowed origins or CORS: include `http://localhost:3000`.
- Scopes: `openid`, `profile`, `portal-api:chat`, `customer:profile:read`, and `customer:payments:read`.
- Token audience for portal API: `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal`.

The browser redeems the authorization code directly at PingFederate. PingFederate must allow browser CORS to its token endpoint from the portal origin.

### Token Exchange Clients

Configure token exchange clients for the workloads:

| Workload | Client ID | Allowed actor SPIFFE ID | Requested audience | Requested scopes |
| --- | --- | --- | --- | --- |
| Portal | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `customer:profile:read customer:payments:read` |
| Agent | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp` | `customer:profile:read customer:payments:read` |

The demo supports token-exchange clients with client authentication method `none`. In that mode the services send `client_id` in the form body and do not send an OAuth client secret or Basic authorization header. The authorization decision must come from validating the `actor_token` JWT-SVID and binding its SPIFFE ID to the allowed client ID, requested audience, and requested scopes.

### SPIRE JWT-SVID Trust

Configure PingFederate to validate SPIRE JWT-SVIDs used as token-exchange `actor_token` values:

- Trust the SPIRE JWT issuer for the `ping.demo` trust domain.
- Validate the JWT-SVID signature using the SPIRE JWKS for that trust domain.
- Require the JWT-SVID audience to match `SPIFFE_JWT_SVID_AUDIENCE`, for example `pingfederate-token-exchange`.
- Map the JWT-SVID subject to the SPIFFE ID.
- Authorize only the portal and agent SPIFFE IDs for token exchange.

The token exchange request shape is:

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token=<incoming PingFederate OAuth access token>
subject_token_type=urn:ietf:params:oauth:token-type:access_token
actor_token=<caller workload JWT-SVID>
actor_token_type=urn:ietf:params:oauth:token-type:jwt
scope=<target API scopes>
resource=<target API resource>
client_id=<workload token-exchange client ID>
```

### Access Token Expectations

PingFederate-issued access tokens must line up with service validation:

| Token | Issued to | Audience | Required scopes |
| --- | --- | --- | --- |
| Browser user token | Portal API | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal` | `portal-api:chat`, `customer:profile:read`, and `customer:payments:read` |
| Agent invocation token | Agent | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `customer:profile:read` and/or `customer:payments:read` |
| MCP token | MCP server | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp` | `customer:profile:read` and/or `customer:payments:read` |

## Build And Deploy

Build images and load them into kind:

```bash
./scripts/build-images.sh
```

Deploy the current manifest and restart the three workloads:

```bash
./scripts/deploy.sh
```

Build, load, deploy, and wait for rollout in one command:

```bash
./scripts/build-and-deploy.sh
```

The scripts use these environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMAGE_PREFIX` | `spiffe-token-exchange-demo` | Docker image repository prefix used for all three services. |
| `IMAGE_TAG` | `latest` | Docker image tag. |
| `KIND_CLUSTER` | `kind` | kind cluster name used by `kind load docker-image` in `build-images.sh`. |
| `LOCAL_MANIFEST` | `deploy/k8s/local.yaml` | Manifest applied by `deploy.sh`. |
| `NAMESPACE` | `spiffe-token-exchange-demo` | Namespace used for rollout restart/status in `deploy.sh`. |

Equivalent manual commands:

```bash
docker build --target portal -t spiffe-token-exchange-demo/portal:latest .
docker build --target agent -t spiffe-token-exchange-demo/agent:latest .
docker build --target mcp -t spiffe-token-exchange-demo/mcp:latest .

kind load docker-image spiffe-token-exchange-demo/portal:latest --name kind
kind load docker-image spiffe-token-exchange-demo/agent:latest --name kind
kind load docker-image spiffe-token-exchange-demo/mcp:latest --name kind

kubectl apply -f deploy/k8s/local.yaml
kubectl rollout restart deployment/portal deployment/agent deployment/mcp -n spiffe-token-exchange-demo
kubectl rollout status deployment/portal -n spiffe-token-exchange-demo
kubectl rollout status deployment/agent -n spiffe-token-exchange-demo
kubectl rollout status deployment/mcp -n spiffe-token-exchange-demo
```

If you change `IMAGE_PREFIX` or `IMAGE_TAG`, update the container image fields in `deploy/k8s/local.yaml` to match before applying the manifest.

## Access The Portal

Wait for the deployments and port-forward the portal service:

```bash
kubectl -n spiffe-token-exchange-demo rollout status deployment/portal
kubectl -n spiffe-token-exchange-demo rollout status deployment/agent
kubectl -n spiffe-token-exchange-demo rollout status deployment/mcp
kubectl -n spiffe-token-exchange-demo port-forward service/portal 3000:3000
```

Open `http://localhost:3000`. The portal should redirect to PingFederate for login, receive the browser access token, and call the portal API. Chat prompts then exercise the portal-to-agent and agent-to-MCP token exchanges.

## Useful Checks

Check pods and service endpoints:

```bash
kubectl -n spiffe-token-exchange-demo get pods
kubectl -n spiffe-token-exchange-demo get svc
kubectl -n spiffe-token-exchange-demo describe pod -l app.kubernetes.io/name=portal
```

Check logs:

```bash
kubectl -n spiffe-token-exchange-demo logs deployment/portal
kubectl -n spiffe-token-exchange-demo logs deployment/agent
kubectl -n spiffe-token-exchange-demo logs deployment/mcp
```

Common configuration failures:

- `OIDC_DISCOVERY_URI is required`: the ConfigMap does not include a PingFederate discovery URI.
- `OIDC_CLIENT_ID is required`: the browser SPA client ID is missing.
- `SPIFFE_ENDPOINT_SOCKET and SPIFFE_JWT_SVID_AUDIENCE are required`: the token-exchange workload cannot fetch an actor token.
- Token audience errors: PingFederate token audiences do not match `API_OAUTH_CLIENT_ID`, `AGENT_OAUTH_CLIENT_ID`, or `MCP_AUDIENCE`.
- Token scope errors: PingFederate did not issue the scope required by the receiving service or MCP tool.
- TLS discovery failures: the pod does not trust the CA used by PingFederate.

## Validation

Run repository checks from the workstation:

```bash
PYTHONPATH=src/backend .venv/bin/python -m compileall -q src/backend
```

Run cluster checks after deployment:

```bash
kubectl -n spiffe-token-exchange-demo get pods
kubectl -n spiffe-token-exchange-demo rollout status deployment/portal
kubectl -n spiffe-token-exchange-demo rollout status deployment/agent
kubectl -n spiffe-token-exchange-demo rollout status deployment/mcp
```
