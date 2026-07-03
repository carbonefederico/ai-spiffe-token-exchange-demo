from __future__ import annotations

import uuid
from typing import Any


def to_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message", "")).strip()
    if not message:
        raise ValueError("message is required")
    conversation_id = payload.get("conversationId") or str(uuid.uuid4())
    return {
        "id": str(uuid.uuid4()),
        "conversationId": conversation_id,
        "text": message,
        "metadata": {"source": "portal"},
    }


def from_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id") or str(uuid.uuid4()),
        "conversationId": payload.get("conversationId") or payload.get("id") or str(uuid.uuid4()),
        "text": str(payload.get("text", "")),
    }


def to_agent_response(task_id: str, conversation_id: str, text: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": task_id,
        "result": {
            "id": task_id,
            "conversationId": conversation_id,
            "message": {
                "role": "agent",
                "parts": [{"type": "text", "text": text}],
            },
            "metadata": {"toolCalls": tool_calls},
        },
    }
