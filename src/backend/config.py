import os
from dataclasses import dataclass

import httpx


PORTAL_PORT = 3000
AGENT_PORT = 3001
MCP_PORT = 3002


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    portal_port: int
    agent_port: int
    mcp_port: int
    no_security: bool
    allowed_origins: list[str]
    agent_url: str
    mcp_url: str
    mcp_allowed_hosts: list[str]
    oidc_discovery_uri: str
    oidc_client_id: str
    oidc_redirect_uri: str
    oidc_scopes: list[str]
    mcp_audience: str
    api_oauth_client_id: str
    agent_oauth_client_id: str
    agent_token_exchange_scope: str
    mcp_token_exchange_scope: str
    spiffe_endpoint_socket: str
    spiffe_jwt_svid_audience: str
    spiffe_jwt_svid: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    tls_verify: bool


@dataclass(frozen=True)
class OidcConfig:
    no_security: bool
    issuer: str
    jwks_uri: str
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    audience: str


def service_config() -> ServiceConfig:
    return ServiceConfig(
        host="0.0.0.0",
        portal_port=PORTAL_PORT,
        agent_port=AGENT_PORT,
        mcp_port=MCP_PORT,
        no_security=_truthy(os.getenv("NO_SECURITY")),
        allowed_origins=_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")),
        agent_url=os.getenv("AGENT_URL", f"http://localhost:{AGENT_PORT}"),
        mcp_url=os.getenv("MCP_URL", f"http://localhost:{MCP_PORT}/mcp"),
        mcp_allowed_hosts=_csv(os.getenv("MCP_ALLOWED_HOSTS", "mcp:*,localhost:*,127.0.0.1:*")),
        oidc_discovery_uri=os.getenv("OIDC_DISCOVERY_URI", ""),
        oidc_client_id=os.getenv("OIDC_CLIENT_ID", ""),
        oidc_redirect_uri=os.getenv("OIDC_REDIRECT_URI", "http://localhost:3000/callback"),
        oidc_scopes=_csv(os.getenv("OIDC_SCOPES", "openid profile")),
        mcp_audience=os.getenv("MCP_AUDIENCE", ""),
        api_oauth_client_id=os.getenv("API_OAUTH_CLIENT_ID", ""),
        agent_oauth_client_id=os.getenv("AGENT_OAUTH_CLIENT_ID", ""),
        agent_token_exchange_scope=os.getenv("AGENT_TOKEN_EXCHANGE_SCOPE", ""),
        mcp_token_exchange_scope=os.getenv("MCP_TOKEN_EXCHANGE_SCOPE", ""),
        spiffe_endpoint_socket=os.getenv("SPIFFE_ENDPOINT_SOCKET", ""),
        spiffe_jwt_svid_audience=os.getenv("SPIFFE_JWT_SVID_AUDIENCE", ""),
        spiffe_jwt_svid=os.getenv("SPIFFE_JWT_SVID", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        tls_verify=os.getenv("NODE_TLS_REJECT_UNAUTHORIZED", "1") != "0",
    )


async def load_oidc_config(config: ServiceConfig, expected_audience: str) -> OidcConfig:
    if config.no_security:
        return OidcConfig(
            no_security=True,
            issuer="static-demo-issuer",
            jwks_uri="",
            authorization_endpoint="",
            token_endpoint="",
            client_id=config.oidc_client_id or "static-demo-client",
            redirect_uri=config.oidc_redirect_uri,
            scopes=config.oidc_scopes,
            audience=expected_audience,
        )

    if not config.oidc_discovery_uri:
        raise RuntimeError("OIDC_DISCOVERY_URI is required unless NO_SECURITY=true")

    async with httpx.AsyncClient(verify=config.tls_verify, timeout=10) as client:
        response = await client.get(config.oidc_discovery_uri)
        response.raise_for_status()
        metadata = response.json()

    return OidcConfig(
        no_security=False,
        issuer=metadata.get("issuer", ""),
        jwks_uri=metadata.get("jwks_uri", ""),
        authorization_endpoint=metadata.get("authorization_endpoint", ""),
        token_endpoint=metadata.get("token_endpoint", ""),
        client_id=config.oidc_client_id,
        redirect_uri=config.oidc_redirect_uri,
        scopes=config.oidc_scopes,
        audience=expected_audience,
    )


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.replace(",", " ").split() if part.strip()]


def _truthy(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}
