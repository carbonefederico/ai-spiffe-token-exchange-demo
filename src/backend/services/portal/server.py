from __future__ import annotations

import json
from pathlib import Path

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from auth import require_auth, static_demo_token
from config import OidcConfig, load_oidc_config, service_config
from http_client import post_json
from logger import error_summary, log_event
from protocol import to_agent_task
from spiffe_exchange import (
    build_token_exchange_body,
    get_actor_token,
    token_exchange_request_summary,
    token_exchange_response_summary,
)
from token_history import record_token_event, token_history, token_summary

service = service_config()
auth_config: OidcConfig | None = None
public_dir = Path(__file__).resolve().parents[3] / "frontend"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=service.allowed_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_log(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        log_event("portal-api", "request", {"method": request.method, "path": request.url.path, "status": response.status_code})
    return response


async def current_auth(authorization: str | None = Header(default=None)):
    return await require_auth(authorization, auth_config, "portal-api", service.tls_verify)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "portal"}


@app.get("/config.js")
async def config_js():
    payload = {
        "issuer": auth_config.issuer,
        "clientId": auth_config.client_id,
        "authorizationEndpoint": auth_config.authorization_endpoint,
        "tokenEndpoint": auth_config.token_endpoint,
        "redirectUri": auth_config.redirect_uri,
        "scopes": auth_config.scopes,
        "noSecurity": service.no_security,
    }
    return Response(f"window.TELCO_CONFIG = {json.dumps(payload)};", media_type="application/javascript")


@app.post("/api/dev-token")
async def dev_token():
    if not service.no_security:
        raise HTTPException(status_code=404, detail="not_found")
    log_event("portal-api", "static-login", {"subject": "static-demo-user", "mode": "no_security"})
    return {"access_token": static_demo_token, "token_type": "Bearer", "expires_in": 86400}


@app.get("/api/me")
async def me(auth=Depends(current_auth)):
    return {
        "subject": auth.subject,
        "customerId": auth.customer_id,
        "scopes": auth.scopes,
        "claims": {
            "name": auth.payload.get("name"),
            "givenName": auth.payload.get("given_name"),
            "familyName": auth.payload.get("family_name"),
            "email": auth.payload.get("email"),
            "username": auth.payload.get("preferred_username") or auth.payload.get("username"),
        },
        "accessTokenClaims": auth.payload,
        "idTokenClaims": None,
    }


@app.post("/api/chat")
async def chat(payload: dict, auth=Depends(current_auth)):
    try:
        task = to_agent_task(payload)
        log_event("portal-api", "chat-forward", {
            "taskId": task["id"],
            "conversationId": task["conversationId"],
            "subject": auth.subject,
            "messageLength": len(payload.get("message", "")),
            "tokenExchangeScope": service.agent_token_exchange_scope,
            "incomingPayload": payload,
            "agentPayload": task,
        })
        agent_token = await exchange_token_for_agent(auth.token)
        agent_response = await post_json(
            f"{service.agent_url}/a2a/message",
            task,
            token=agent_token,
            verify=service.tls_verify,
            component="portal-agent",
            operation="call-agent",
        )
        result = agent_response["result"]
        tool_calls = result.get("metadata", {}).get("toolCalls") or []
        log_event("portal-api", "chat-response", {
            "taskId": task["id"],
            "toolCalls": [f"{call['tool']}:{'ok' if call.get('ok') else 'error'}" for call in tool_calls],
        })
        return {
            "conversationId": result.get("conversationId") or task["conversationId"],
            "message": "\n".join(part.get("text", "") for part in result.get("message", {}).get("parts", [])),
            "toolCalls": tool_calls,
        }
    except Exception as exc:
        log_event("portal-api", "unhandled-error", {"error": error_summary(exc)})
        raise HTTPException(status_code=getattr(exc, "status_code", 500), detail=str(exc)) from exc


@app.get("/api/token-history")
async def api_token_history(_auth=Depends(current_auth)):
    agent_history, mcp_history = await _fetch_histories()
    events = [*token_history(), *agent_history, *mcp_history]
    events.sort(key=lambda event: event.get("timestamp", ""))
    return {"events": events}


async def exchange_token_for_agent(access_token: str) -> str:
    if auth_config.no_security:
        return access_token or static_demo_token
    if not service.agent_token_exchange_scope:
        raise RuntimeError("AGENT_TOKEN_EXCHANGE_SCOPE is required before calling the agent")
    if not service.api_oauth_client_id:
        raise RuntimeError("API_OAUTH_CLIENT_ID is required for agent token exchange")
    if not service.agent_oauth_client_id:
        raise RuntimeError("AGENT_OAUTH_CLIENT_ID is required as the agent token exchange resource")

    actor_token = get_actor_token(service, service.api_oauth_client_id)
    actor_summary = token_summary(actor_token)
    record_token_event("portal-api", "agent-token-exchange-start", {
        "endpoint": auth_config.token_endpoint,
        "method": "POST",
        "scope": service.agent_token_exchange_scope,
        "resource": service.agent_oauth_client_id,
        "clientId": service.api_oauth_client_id,
        "request": token_exchange_request_summary(
            scope=service.agent_token_exchange_scope,
            resource=service.agent_oauth_client_id,
            client_id=service.api_oauth_client_id,
        ),
        "subjectToken": token_summary(access_token),
        "actorToken": actor_summary,
    })
    body = build_token_exchange_body(
        subject_token=access_token,
        actor_token=actor_token,
        scope=service.agent_token_exchange_scope,
        resource=service.agent_oauth_client_id,
        client_id=service.api_oauth_client_id,
    )
    headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    try:
        async with httpx.AsyncClient(verify=service.tls_verify, timeout=20) as client:
            response = await client.post(auth_config.token_endpoint, content=body, headers=headers)
    except Exception as exc:
        record_token_event("portal-api", "agent-token-exchange-failed", {
            "endpoint": auth_config.token_endpoint,
            "subjectToken": token_summary(access_token),
            "actorToken": actor_summary,
            "error": error_summary(exc),
        })
        raise
    exchanged = _response_json_or_text(response)
    if response.status_code >= 400 or not exchanged.get("access_token"):
        response_summary = {
            "status": response.status_code,
            "body": exchanged if exchanged else response.text,
            "headers": {
                "content-type": response.headers.get("content-type"),
                "www-authenticate": response.headers.get("www-authenticate"),
            },
        }
        record_token_event("portal-api", "agent-token-exchange-failed", {
            "endpoint": auth_config.token_endpoint,
            "status": response.status_code,
            "error": exchanged.get("error"),
            "errorDescription": exchanged.get("error_description"),
            "request": token_exchange_request_summary(
                scope=service.agent_token_exchange_scope,
                resource=service.agent_oauth_client_id,
                client_id=service.api_oauth_client_id,
            ),
            "response": response_summary,
            "subjectToken": token_summary(access_token),
            "actorToken": actor_summary,
        })
        message = exchanged.get("error_description") or exchanged.get("error") or f"Token exchange failed with HTTP {response.status_code}"
        raise RuntimeError(f"{message} status={response.status_code} client_id={service.api_oauth_client_id}")
    record_token_event("portal-api", "agent-token-exchange-success", {
        "endpoint": auth_config.token_endpoint,
        "method": "POST",
        "status": response.status_code,
        "tokenType": exchanged.get("token_type"),
        "expiresIn": exchanged.get("expires_in"),
        "scope": exchanged.get("scope"),
        "resource": service.agent_oauth_client_id,
        "response": token_exchange_response_summary(exchanged),
        "subjectToken": token_summary(access_token),
        "actorToken": actor_summary,
        "issuedToken": token_summary(exchanged["access_token"]),
    })
    return exchanged["access_token"]


def _response_json_or_text(response: httpx.Response) -> dict:
    if not response.text:
        return {}
    try:
        body = response.json()
        return body if isinstance(body, dict) else {"raw": body}
    except Exception:
        return {"raw": response.text}


async def _fetch_histories() -> tuple[list[dict], list[dict]]:
    async def fetch(url: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(verify=service.tls_verify, timeout=2) as client:
                response = await client.get(url)
            if response.status_code >= 400:
                return []
            body = response.json()
            return body.get("events", []) if isinstance(body.get("events"), list) else []
        except Exception as exc:
            record_token_event("portal-api", "token-history-fetch-failed", {"url": url, "error": error_summary(exc)})
            return []

    return (
        await fetch(f"{service.agent_url}/debug/token-history"),
        await fetch(str(httpx.URL(service.mcp_url).copy_with(path="/debug/token-history"))),
    )


@app.get("/{path:path}")
async def frontend(path: str):
    target = public_dir / path
    if path and target.is_file():
        return FileResponse(target)
    return FileResponse(public_dir / "index.html")


async def main() -> None:
    global auth_config
    auth_config = await load_oidc_config(service, service.api_oauth_client_id)
    app.mount("/assets", StaticFiles(directory=public_dir / "assets"), name="assets")
    config = uvicorn.Config(app, host=service.host, port=service.portal_port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
