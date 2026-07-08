# Configuration

This page includes configuration guidelines, not a full configuration tutorial. It starts from a running and configured local Kind cluster, running on a Mac with SPIRE installed. The demo relies on Kubernetes, SPIRE, and PingFederate for the real token-exchange path; it is not a local-only development workflow.

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

The generic deployment template is `deploy/k8s/base.yaml`. It already includes the full ConfigMap key set used by the application and by this guide, but the checked-in values are generic placeholders such as `example.org`, `portal.example.com`, and `replace-with-*`.

For local kind work, edit `deploy/k8s/local.yaml` and keep these values consistent:

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
3. RFC 8693 token exchange where the subject token is a PingFederate-issued OAuth access token.

The token exchange configuration has four major PingFederate components, plus the access token manager instance that issues the exchanged JWTs:

- Token Processor instances validate inbound subject and actor tokens.
- The Token Exchange Processor Policy selects the Token Processors and publishes a small policy contract.
- The Access Token Manager issues exchanged JWT access tokens and selects on resource URIs.
- Access Token Mapping maps the processor policy contract into the access token manager contract.
- OAuth Client configuration enables the Token Exchange grant and binds the client to the processor policy.

PingFederate 13.1 documentation describes OAuth token exchange configuration as processor policies, token generator or access token manager mappings, and OAuth clients. For this demo, use the access token manager path because token exchange issues OAuth access tokens. The relevant Ping docs are:

- [Configuring OAuth token exchange](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_config_oauth_token_exchange.html)
- [Managing token processors](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_managing_token_processors.html)
- [Configuring a JWT Token Processor 2.0 instance](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_configuring_jwt_token_processor_20_instance.html)
- [Defining token exchange processor policies](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_defining_token_exchange_processor_policies.html)
- [Managing access token management instances](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/help_accesstokenmanagementtasklet_accesstokenmanagementstate.html)
- [Managing resource URIs](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/help_beareraccesstokenmgmtplugintasklet_atmselectionsettingsstate.html)
- [Defining the access token attribute contract](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_defining_access_token_attribute_contract.html)
- [Mapping token exchange attributes to access token manager attributes](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_mapp_token_exchang_attribut_to_access_token_manager_attribut.html)
- [Enabling token exchange in OAuth clients](https://docs.pingidentity.com/pingfederate/13.1/administrators_reference_guide/pf_enabl_token_exchang_oauth_client.html)

### Web App OAuth Client

Configure the portal web app in PingFederate the usual OIDC way for a browser-facing application. The detailed web app setup is intentionally separate from this token-exchange guide.

At a high level, the portal web app needs:

- Authorization Code with PKCE.
- Redirect URI matching `OIDC_REDIRECT_URI`, for example `http://localhost:3000/callback` when using port-forwarding.
- Browser origin/CORS matching `ALLOWED_ORIGINS`, for example `http://localhost:3000`.
- Scopes matching `OIDC_SCOPES`.
- Access tokens whose audience matches the portal API expectation, `API_OAUTH_CLIENT_ID`.

The browser redeems the authorization code directly at PingFederate. This token is issued to the web portal and becomes the `subject_token` for the first token exchange. The token that PingFederate issues to the agent becomes the `subject_token` for the second token exchange. Both are PingFederate-issued access tokens, so their issuer, JWKS, and audiences must match the subject Token Processor instance below.

### Token Processor Instances

Create two Token Processor instances: one for inbound PingFederate subject tokens and one for SPIFFE actor tokens. The subject token processor validates OAuth access tokens issued by the POC PingFederate server to the portal and agent audiences. The actor token processor validates the SPIRE JWT-SVID sent by the portal or agent workload.

1. Go to **Authentication > Token Exchange > Token Processors**.
2. Click **Create New Instance**.
3. Create the subject token processor:
   - Choose a stable **Name** and **ID**, for example `poc-pf-access-token-processor`.
   - For **Type**, choose **JWT Token Processor 2.0**.
   - On **Instance Configuration**, add an issuer entry:
     - **Issuer**: the `iss` value in the PingFederate subject tokens. This must match exactly.
     - **JWKS URL**: the JWKS endpoint for that issuer, or paste the issuer JWKS directly if your environment cannot route to the JWKS URL.
     - **Allowed Audiences**: add both subject-token audiences that can arrive at token exchange:
       - `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal`, matching `API_OAUTH_CLIENT_ID`, for the browser token issued to the web portal.
       - `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent`, matching `AGENT_OAUTH_CLIENT_ID`, for the token issued to the agent and later exchanged for the MCP token.
   - Leave the default required-claims settings unless your POC tokens require a different policy. PingFederate defaults include audience and expiration validation for JWT Token Processor 2.0.
   - On the extended contract, include:
     - `subject`: the original user or workload subject.
     - `act`: the existing actor chain claim from the inbound subject token. The browser token normally has no `act`; the agent token should have one from the first token exchange.
   - Save the instance.
4. Click **Create New Instance** again.
5. Create the actor token processor:
   - Choose a stable **Name** and **ID**, for example `spire-jwt-svid-token-processor`.
   - For **Type**, choose **JWT Token Processor 2.0**.
   - On **Instance Configuration**, add an issuer entry:
     - **Issuer**: the issuer used by the SPIRE OIDC Discovery Provider for the `ping.demo` trust domain.
     - **JWKS URL**: the SPIRE OIDC Discovery JWKS endpoint reachable from PingFederate, or paste the SPIRE JWKS directly if your environment cannot route to it.
     - **Allowed Audiences**: `pingfederate-token-exchange`, matching `SPIFFE_JWT_SVID_AUDIENCE`.
   - Keep audience and expiration validation enabled.
   - On the extended contract, keep only the default `subject` attribute for now. The actor token subject is the SPIFFE ID, for example `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal`.
   - Save the instance.

The subject Token Processor validates the incoming PingFederate access token and extracts any previous `act` chain. The actor Token Processor validates the current workload JWT-SVID after the Token Exchange Processor Policy selects both processors.

### Token Exchange Processor Policy

Create one Token Exchange Processor Policy for the POC token exchange path.

1. Go to **Applications > Token Exchange > Processor Policies**.
2. Click **Add Processor Policy**.
3. Enter the **Policy ID** and **Name**.
4. Select **Actor Token Required**, then click **Next**.
5. On **Attribute Contract**, include:
   - `subject`: the end-user or original subject from the inbound subject token.
   - `subject_act`: the previous `act` claim from the inbound subject token.
6. On **Token Processor Mapping**, click **Map New Token Processor**.
7. On **Token Types**:
   - From **Subject Token Processor**, select the JWT Token Processor 2.0 instance created for PingFederate-issued OAuth access tokens.
   - In **Subject Token Type**, enter `urn:ietf:params:oauth:token-type:access_token`.
   - From **Actor Token Processor**, select the JWT Token Processor 2.0 instance created for SPIRE JWT-SVIDs.
   - In **Actor Token Type**, enter `urn:ietf:params:oauth:token-type:jwt`.
8. Skip additional **Attribute Sources & User Lookup** configuration for now.
9. On **Contract Fulfillment**:
   - Map `subject` from the subject token processor `subject`.
   - Map `subject_act` from the subject token processor `act`.
10. Leave issuance criteria and the rest of the wizard at defaults unless your POC needs extra restrictions.
11. Review, finish, and save the policy.

The application sends a SPIFFE JWT-SVID as `actor_token` in the token exchange request. The TEPP validates that current actor token separately. The `tepp.subject_act` value is the previous actor chain from the inbound subject token and is used by the access token mapping to build the next `act` claim.

### Access Token Manager For Token Exchange

Create or update a JWT access token manager for tokens issued by token exchange.

1. Go to **Applications > OAuth > Access Token Management**.
2. Select the access token manager that will issue exchanged tokens, or click **Create New Instance**.
3. On **Resource URI**, add the resource values that the services send in token exchange requests and later expect as token audiences:

   | Exchanged token | Request `resource` value | Matching environment value |
   | --- | --- | --- |
   | Portal-to-agent token | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `AGENT_OAUTH_CLIENT_ID` |
   | Agent-to-MCP token | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp` | `MCP_AUDIENCE` |

   PingFederate uses these resource URIs to select this access token manager when a token exchange request includes the `resource` parameter. The values must match the resource servers' expected `aud` values.
4. On **Access Token Attribute Contract**, include the normal claims your token manager needs, and add:
   - `act`: actor chain claim populated from the token exchange mapping.
5. Ensure the token manager issues JWT access tokens with:
   - `sub` or equivalent subject from the mapped processor policy subject.
   - `aud` matching the requested resource URI, either through the token manager resource/audience settings or the access token mapping used by your ATM.
   - `scope` containing the requested same-or-narrower customer scopes.
   - `act` from the mapping below.
6. Save the access token manager.

### Access Token Mapping

Map the Token Exchange Processor Policy contract into the access token manager that issues exchanged OAuth access tokens.

1. Go to **Applications > OAuth > Access Token Mapping**.
2. In **Context**, select the Token Exchange Processor Policy created above.
3. In **Access Token Manager**, select the access token manager that will issue tokens through token exchange.
4. Click **Add Mapping**.
5. Skip additional **Attribute Sources & User Lookup** configuration for now.
6. On **Contract Fulfillment**, map:
   - The access token manager contract `subject` or `sub` attribute from the processor policy `subject`.
   - The access token manager contract `act` attribute from an **Expression** value using this OGNL script:

     ```text
     #curr = #this.get("context.ClientId") != null ? #this.get("context.ClientId").toString() : "",
     #prev = #this.get("tepp.subject_act"),
     #agentType = #this.get("extproperties.AgentType") != null ? #this.get("extproperties.AgentType").toString() : null,
     #clientType = #this.get("extproperties.ClientType") != null ? #this.get("extproperties.ClientType").toString() : null,
     #out = new java.util.LinkedHashMap(),
     #out.put("sub", #curr),
     (#agentType != null && #agentType.length() > 0) ? #out.put("agent_type", #agentType) : true,
     (#clientType != null && #clientType.length() > 0) ? #out.put("client_type", #clientType) : true,
     (#prev != null && #prev.getObjectValue() != null) ? #out.put("act", #prev.getObjectValue()) : true,
     #out
     ```

     The expression sets the current actor to `context.ClientId`, optionally includes `AgentType` and `ClientType` from client extended properties, and nests the prior SPIFFE actor from `tepp.subject_act` under `act`.
7. Leave issuance criteria and the rest of the wizard at defaults unless your POC needs extra restrictions.
8. Review, finish, and save the mapping.

If the selected access token manager contract requires additional fields such as `iss`, `aud`, or custom claims, map those according to your access token manager configuration. The minimum POC mapping is the processor policy `subject` into the token subject and the `act` expression above into the token actor claim.

### OAuth Client Token Exchange Enablement

Enable Token Exchange on each OAuth client that sends token exchange requests. In this demo, that means the workload token-exchange clients used by the portal and agent.

Configure token exchange clients for the workloads:

| Workload | Client ID | Requested resource | Requested scopes |
| --- | --- | --- | --- |
| Portal | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/portal` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `customer:profile:read customer:payments:read` |
| Agent | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/agent` | `spiffe://ping.demo/ns/spiffe-token-exchange-demo/sa/mcp` | `customer:profile:read customer:payments:read` |

For each client:

1. Go to **Applications > OAuth > Clients**.
2. Open the client from the **Client ID** column.
3. In **Allowed Grant Types**, select **Token Exchange**.
4. In **Token Exchange**, select the Token Exchange Processor Policy created above from the **Processor Policy** list.
5. If your PingFederate client configuration exposes extended properties, set values consumed by the `act` expression:
   - `AgentType`: optional descriptor for workload clients that act as agents.
   - `ClientType`: optional descriptor for client category.
6. Save the client.

The demo supports token-exchange clients with client authentication method `none`. In that mode the services send `client_id` in the form body and do not send an OAuth client secret or Basic authorization header. For a production policy, bind token exchange authorization to workload identity, allowed resource, and allowed scopes rather than relying only on public client IDs.

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
