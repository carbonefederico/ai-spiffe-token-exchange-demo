from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware

from auth import normalize_auth, require_scope, static_demo_payload, static_demo_token, verify_access_token
from config import ServiceConfig, load_oidc_config, service_config
from logger import error_summary, log_event
from scopes import mcp_payments_scope, mcp_profile_scope
from token_history import record_token_event, token_history, token_summary
from .mock_data import customer_profile_for, payment_summary_for

service = service_config()
auth_config = None


class DemoTokenVerifier:
    def __init__(self, config: ServiceConfig):
        self.config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            record_token_event("mcp-auth", "api-token-received", {"token": token_summary(token)})
            if auth_config and auth_config.no_security:
                auth = normalize_auth(static_demo_payload, token or static_demo_token, "no_security")
            else:
                auth = await verify_access_token(token, auth_config, self.config.tls_verify)
            record_token_event("mcp-auth", "api-token-accepted", {
                "mode": auth.mode,
                "subject": auth.subject,
                "customerId": auth.customer_id,
                "scopes": auth.scopes,
                "expectedIssuer": auth_config.issuer,
                "expectedAudience": auth_config.audience,
                "token": token_summary(token),
            })
            return AccessToken(
                token=token,
                client_id=auth.payload.get("client_id") or auth.payload.get("azp") or "telco-demo",
                scopes=auth.scopes,
                expires_at=auth.payload.get("exp"),
                subject=auth.subject,
                claims={**auth.payload, "customer_id": auth.customer_id},
            )
        except Exception as exc:
            record_token_event("mcp-auth", "api-token-rejected", {
                "expectedIssuer": getattr(auth_config, "issuer", ""),
                "expectedAudience": getattr(auth_config, "audience", ""),
                "error": error_summary(exc),
            })
            return None


def create_mcp_server() -> FastMCP:
    verifier = DemoTokenVerifier(service)
    mcp = FastMCP(
        "telco-demo-mcp-server",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=auth_config.issuer if auth_config and auth_config.issuer.startswith("http") else "http://mcp.local",
            resource_server_url="http://mcp:3002/mcp",
        ),
        host=service.host,
        port=service.mcp_port,
        streamable_http_path="/mcp",
        stateless_http=False,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=service.mcp_allowed_hosts,
            allowed_origins=service.allowed_origins,
        ),
    )

    @mcp.tool()
    def get_customer_profile(customerId: str | None = None) -> dict[str, Any]:
        auth = _auth_from_context()
        _authorize_tool("get_customer_profile", mcp_profile_scope, auth, customerId)
        resolved_customer_id = customerId or auth["customer_id"]
        result = customer_profile_for(resolved_customer_id)
        _log_tool_response("get_customer_profile", auth, resolved_customer_id, result)
        return result

    @mcp.tool()
    def get_payment_summary(customerId: str | None = None) -> dict[str, Any]:
        auth = _auth_from_context()
        _authorize_tool("get_payment_summary", mcp_payments_scope, auth, customerId)
        resolved_customer_id = customerId or auth["customer_id"]
        result = payment_summary_for(resolved_customer_id)
        _log_tool_response("get_payment_summary", auth, resolved_customer_id, result)
        return result

    return mcp


def create_app(mcp: FastMCP) -> FastAPI:
    app = FastAPI(lifespan=lambda app: mcp.session_manager.run())
    app.add_middleware(CORSMiddleware, allow_origins=service.allowed_origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_log(request, call_next):
        try:
            response = await call_next(request)
            if request.url.path != "/health":
                log_event("mcp-http", "request", {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "sessionId": request.headers.get("mcp-session-id"),
                })
            return response
        except Exception as exc:
            record_token_event("mcp-http", "request-failed", {
                "method": request.method,
                "path": request.url.path,
                "sessionId": request.headers.get("mcp-session-id"),
                "error": error_summary(exc),
            })
            raise

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "mcp-server"}

    @app.get("/debug/token-history")
    async def debug_token_history():
        return {"events": token_history()}

    app.mount("/", mcp.streamable_http_app())
    return app


def _auth_from_context() -> dict[str, Any]:
    token = get_access_token()
    if not token:
        raise RuntimeError("Missing MCP auth context")
    claims = token.claims or {}
    return {
        "token": token.token,
        "scopes": token.scopes,
        "subject": token.subject or claims.get("sub") or "anonymous",
        "customer_id": claims.get("customer_id") or claims.get("customerId") or token.subject or "cust-1001",
        "claims": claims,
    }


def _authorize_tool(tool: str, required_scope: str, auth: dict[str, Any], customer_id: str | None) -> None:
    resolved_customer_id = customer_id or auth["customer_id"]
    record_token_event("mcp-tool", "tool-call-received", {
        "tool": tool,
        "subject": auth["subject"],
        "customerId": resolved_customer_id,
        "requiredScope": required_scope,
        "scopes": auth["scopes"],
        "token": token_summary(auth["token"]),
        "claims": auth["claims"],
    })
    try:
        auth_context = type("AuthContext", (), {"scopes": auth["scopes"]})()
        require_scope(auth_context, required_scope)
    except Exception as exc:
        record_token_event("mcp-tool", "tool-call-rejected", {
            "tool": tool,
            "subject": auth["subject"],
            "customerId": resolved_customer_id,
            "requiredScope": required_scope,
            "scopes": auth["scopes"],
            "error": error_summary(exc),
        })
        raise
    record_token_event("mcp-tool", "tool-call-authorized", {
        "tool": tool,
        "subject": auth["subject"],
        "customerId": resolved_customer_id,
        "requiredScope": required_scope,
        "scopes": auth["scopes"],
        "token": token_summary(auth["token"]),
        "claims": auth["claims"],
    })


def _log_tool_response(tool: str, auth: dict[str, Any], customer_id: str, result: dict[str, Any]) -> None:
    record_token_event("mcp-tool", "tool-call-response", {
        "tool": tool,
        "subject": auth["subject"],
        "customerId": customer_id,
        "scopes": auth["scopes"],
        "token": token_summary(auth["token"]),
        "response": result,
    })


async def main() -> None:
    global auth_config
    auth_config = await load_oidc_config(service, service.mcp_audience)
    app = create_app(create_mcp_server())
    config = uvicorn.Config(app, host=service.host, port=service.mcp_port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
