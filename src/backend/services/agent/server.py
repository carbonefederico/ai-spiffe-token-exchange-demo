from __future__ import annotations

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from auth import require_auth, static_demo_token
from config import OidcConfig, load_oidc_config, service_config
from logger import error_summary, log_event
from protocol import from_agent_task, to_agent_response
from spiffe_exchange import (
    build_token_exchange_body,
    get_actor_token,
    token_exchange_request_summary,
    token_exchange_response_summary,
)
from token_history import record_token_event, token_history, token_summary
from .llm import mock_answer, openai_answer, tools_for_question
from .mcp_client import call_mcp_tools

service = service_config()
auth_config: OidcConfig | None = None
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=service.allowed_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_log(request, call_next):
    response = await call_next(request)
    if request.url.path != "/health":
        log_event("agent-api", "request", {"method": request.method, "path": request.url.path, "status": response.status_code})
    return response


async def current_auth(authorization: str | None = Header(default=None)):
    return await require_auth(authorization, auth_config, "agent-api", service.tls_verify)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent"}


@app.get("/debug/token-history")
async def debug_token_history():
    return {"events": token_history()}


@app.post("/a2a/message")
async def a2a_message(payload: dict, auth=Depends(current_auth)):
    try:
        task = from_agent_task(payload)
        tools = tools_for_question(task["text"])
        log_event("agent", "request-received", {
            "taskId": task["id"],
            "conversationId": task["conversationId"],
            "subject": auth.subject,
            "llmProvider": "openai" if service.openai_api_key else "mock",
            "tools": tools,
            "messageLength": len(task["text"]),
            "incomingPayload": payload,
            "normalizedTask": task,
        })
        mcp_token = await exchange_token_for_mcp(auth.token or static_demo_token) if tools else static_demo_token
        tool_calls = await call_mcp_tools(tools, mcp_token)
        text = await openai_answer(service, task["text"], tool_calls) if service.openai_api_key else mock_answer(task["text"], tool_calls)
        log_event("agent", "response-created", {
            "taskId": task["id"],
            "toolCalls": [f"{call['tool']}:{'error' if call.get('error') else 'ok'}" for call in tool_calls],
            "toolCallResults": tool_calls,
        })
        response_payload = to_agent_response(
            task["id"],
            task["conversationId"],
            text,
            [{"tool": call["tool"], "ok": not bool(call.get("error")), "error": call.get("error", {}).get("message")} for call in tool_calls],
        )
        log_event("agent", "response-payload", {
            "taskId": task["id"],
            "payload": response_payload,
        })
        return response_payload
    except Exception as exc:
        log_event("agent-api", "unhandled-error", {"error": error_summary(exc)})
        raise HTTPException(status_code=getattr(exc, "status_code", 500), detail=str(exc)) from exc


async def exchange_token_for_mcp(access_token: str) -> str:
    if auth_config.no_security:
        return access_token or static_demo_token
    if not service.agent_oauth_client_id:
        raise RuntimeError("AGENT_OAUTH_CLIENT_ID is required for MCP token exchange")
    if not service.mcp_token_exchange_scope:
        raise RuntimeError("MCP_TOKEN_EXCHANGE_SCOPE is required for MCP token exchange")

    actor_token = get_actor_token(service, service.agent_oauth_client_id)
    actor_summary = token_summary(actor_token)
    record_token_event("agent-mcp", "mcp-token-exchange-start", {
        "endpoint": auth_config.token_endpoint,
        "method": "POST",
        "scope": service.mcp_token_exchange_scope,
        "resource": service.mcp_audience,
        "clientId": service.agent_oauth_client_id,
        "request": token_exchange_request_summary(
            scope=service.mcp_token_exchange_scope,
            resource=service.mcp_audience,
            client_id=service.agent_oauth_client_id,
        ),
        "subjectToken": token_summary(access_token),
        "actorToken": actor_summary,
    })
    body = build_token_exchange_body(
        subject_token=access_token,
        actor_token=actor_token,
        scope=service.mcp_token_exchange_scope,
        resource=service.mcp_audience,
        client_id=service.agent_oauth_client_id,
    )
    headers = {"accept": "application/json", "content-type": "application/x-www-form-urlencoded"}
    try:
        async with httpx.AsyncClient(verify=service.tls_verify, timeout=20) as client:
            response = await client.post(auth_config.token_endpoint, content=body, headers=headers)
    except Exception as exc:
        record_token_event("agent-mcp", "mcp-token-exchange-failed", {
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
        record_token_event("agent-mcp", "mcp-token-exchange-failed", {
            "endpoint": auth_config.token_endpoint,
            "status": response.status_code,
            "error": exchanged.get("error"),
            "errorDescription": exchanged.get("error_description"),
            "request": token_exchange_request_summary(
                scope=service.mcp_token_exchange_scope,
                resource=service.mcp_audience,
                client_id=service.agent_oauth_client_id,
            ),
            "response": response_summary,
            "subjectToken": token_summary(access_token),
            "actorToken": actor_summary,
        })
        message = exchanged.get("error_description") or exchanged.get("error") or f"MCP token exchange failed with HTTP {response.status_code}"
        raise RuntimeError(f"{message} status={response.status_code} client_id={service.agent_oauth_client_id}")
    record_token_event("agent-mcp", "mcp-token-exchange-success", {
        "endpoint": auth_config.token_endpoint,
        "method": "POST",
        "status": response.status_code,
        "tokenType": exchanged.get("token_type"),
        "expiresIn": exchanged.get("expires_in"),
        "scope": exchanged.get("scope"),
        "resource": service.mcp_audience,
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


async def main() -> None:
    global auth_config
    auth_config = await load_oidc_config(service, service.agent_oauth_client_id)
    log_event("agent-api", "startup", {"llmProvider": "openai" if service.openai_api_key else "mock"})
    config = uvicorn.Config(app, host=service.host, port=service.agent_port, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
