from __future__ import annotations

import json
from typing import Any

import httpx

from config import ServiceConfig


def tools_for_question(message: str) -> list[str]:
    lowered = message.lower()
    tools: list[str] = []
    if any(word in lowered for word in ["plan", "usage", "device", "profile", "fiber", "mobile"]):
        tools.append("get_customer_profile")
    if any(word in lowered for word in ["bill", "payment", "invoice", "due", "balance", "autopay"]):
        tools.append("get_payment_summary")
    if not tools:
        tools.append("get_customer_profile")
    return tools


def mock_answer(message: str, tool_calls: list[dict[str, Any]]) -> str:
    errors = [call for call in tool_calls if call.get("error") or (isinstance(call.get("data"), dict) and call["data"].get("error"))]
    if errors:
        return "\n".join(f"{call['tool']} failed: {_tool_error_message(call)}" for call in errors)

    profile = next((call.get("data") for call in tool_calls if call["tool"] == "get_customer_profile"), None)
    payment = next((call.get("data") for call in tool_calls if call["tool"] == "get_payment_summary"), None)
    if payment:
        return (
            f"Your current balance is {payment['currency']} {payment['balance']:.2f}, "
            f"due on {payment['dueDate']}. Autopay is {'enabled' if payment['autopay'] else 'disabled'}."
        )
    if profile:
        usage = profile.get("usage", {})
        plan = profile.get("plan") or "an unknown plan"
        mobile_usage = usage.get("mobileDataGb", "unknown")
        fiber_usage = usage.get("homeFiberGb", "unknown")
        return (
            f"You are on {plan}. Mobile usage is {mobile_usage} GB "
            f"and home fiber usage is {fiber_usage} GB this cycle."
        )
    return "I can help with your plan, usage, devices, bill, and payments."


def _tool_error_message(call: dict[str, Any]) -> str:
    if call.get("error"):
        error = call["error"]
        return error.get("message") if isinstance(error, dict) else str(error)
    data = call.get("data")
    if isinstance(data, dict) and data.get("error"):
        return f"{data['error']} for customer {data.get('customerId', 'unknown')}"
    return "unknown error"


async def openai_answer(config: ServiceConfig, message: str, tool_calls: list[dict[str, Any]]) -> str:
    context = json.dumps(tool_calls, indent=2, default=str)
    payload = {
        "model": config.openai_model,
        "messages": [
            {"role": "system", "content": "You are a concise telco support assistant. Use the tool data provided."},
            {"role": "user", "content": f"Question: {message}\n\nTool data:\n{context}"},
        ],
    }
    async with httpx.AsyncClient(verify=config.tls_verify, timeout=30) as client:
        response = await client.post(
            f"{config.openai_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers={"authorization": f"Bearer {config.openai_api_key}"},
        )
        response.raise_for_status()
        body = response.json()
    return body["choices"][0]["message"]["content"]
