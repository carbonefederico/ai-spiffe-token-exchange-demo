from __future__ import annotations

import time
from typing import Any

import httpx

from token_history import record_token_event, token_summary


class UpstreamHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, url: str, body: dict):
        super().__init__(message)
        self.status_code = 502
        self.upstream_status_code = status_code
        self.url = url
        self.body = body


async def post_json(
    url: str,
    payload: dict,
    token: str | None = None,
    verify: bool = True,
    *,
    component: str = "http-client",
    operation: str = "post-json",
) -> dict:
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    record_token_event(component, f"{operation}-request", {
        "method": "POST",
        "url": url,
        "headers": _summarize_headers(headers),
        "token": token_summary(token),
        "payload": payload,
    })
    async with httpx.AsyncClient(verify=verify, timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
    duration_ms = round((time.perf_counter() - started) * 1000)
    body = _response_body(response)
    record_token_event(component, f"{operation}-response", {
        "method": "POST",
        "url": url,
        "status": response.status_code,
        "durationMs": duration_ms,
        "headers": {
            "content-type": response.headers.get("content-type"),
            "www-authenticate": response.headers.get("www-authenticate"),
        },
        "body": body,
    })
    if response.status_code >= 400:
        detail = body.get("detail") or body.get("message") or body.get("error") or response.text
        raise UpstreamHttpError(
            f"Upstream POST {url} failed with HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
            url=url,
            body=body,
        )
    return response.json()


def _summarize_headers(headers: dict[str, str]) -> dict[str, Any]:
    return {
        key: ("Bearer <redacted>" if key.lower() == "authorization" else value)
        for key, value in headers.items()
    }


def _response_body(response: httpx.Response) -> dict[str, Any]:
    if not response.text:
        return {}
    try:
        body = response.json()
        return _sanitize_value(body if isinstance(body, dict) else {"raw": body})
    except Exception:
        return {"raw": response.text}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"access_token", "id_token"}:
                sanitized[key] = token_summary(str(item))
            elif lowered in {"refresh_token", "authorization"}:
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value
