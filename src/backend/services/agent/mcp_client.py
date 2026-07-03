from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config import service_config
from logger import error_summary
from scopes import mcp_tool_scopes
from token_history import record_token_event, token_summary


async def call_mcp_tools(tool_names: list[str], token: str) -> list[dict[str, Any]]:
    if not tool_names:
        return []

    service = service_config()
    headers = {"authorization": f"Bearer {token}"}
    results: list[dict[str, Any]] = []

    record_token_event("agent-mcp", "connect-start", {
        "url": service.mcp_url,
        "tools": tool_names,
        "token": token_summary(token),
    })
    try:
        async with httpx.AsyncClient(headers=headers, verify=service.tls_verify, timeout=20) as client:
            async with streamable_http_client(service.mcp_url, http_client=client) as (read, write, _session_id):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
                    await session.initialize()
                    record_token_event("agent-mcp", "connect-success", {
                        "url": service.mcp_url,
                        "tools": tool_names,
                        "token": token_summary(token),
                    })
                    for tool in tool_names:
                        results.append(await _call_tool(session, service.mcp_url, tool, token))
    except Exception as exc:
        error = error_summary(exc)
        record_token_event("agent-mcp", "connect-failed", {
            "url": service.mcp_url,
            "tools": tool_names,
            "token": token_summary(token),
            "error": error,
        })
        return [
            {
                "tool": tool,
                "error": error,
                "requiredScope": mcp_tool_scopes.get(tool),
            }
            for tool in tool_names
        ]

    return results


async def _call_tool(session: ClientSession, url: str, tool: str, token: str) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    try:
        record_token_event("agent-mcp", "tool-call-start", {
            "url": url,
            "tool": tool,
            "arguments": arguments,
            "requiredScope": mcp_tool_scopes.get(tool),
            "token": token_summary(token),
        })
        result = await session.call_tool(tool, arguments=arguments)
        data = _parse_tool_content(result)
        record_token_event("agent-mcp", "tool-call-success", {
            "url": url,
            "tool": tool,
            "arguments": arguments,
            "requiredScope": mcp_tool_scopes.get(tool),
            "token": token_summary(token),
            "data": data,
            "raw": result.model_dump(mode="json"),
        })
        return {"tool": tool, "data": data, "raw": result.model_dump(mode="json")}
    except Exception as exc:
        error = error_summary(exc)
        record_token_event("agent-mcp", "tool-call-failed", {
            "url": url,
            "tool": tool,
            "arguments": arguments,
            "requiredScope": mcp_tool_scopes.get(tool),
            "token": token_summary(token),
            "error": error,
        })
        return {
            "tool": tool,
            "error": error,
            "requiredScope": mcp_tool_scopes.get(tool),
        }


def _parse_tool_content(result) -> Any:
    if getattr(result, "isError", False):
        text = result.content[0].text if result.content else "MCP tool error"
        raise RuntimeError(text)
    if not result.content:
        return {}
    text = getattr(result.content[0], "text", "{}")
    return json.loads(text)
