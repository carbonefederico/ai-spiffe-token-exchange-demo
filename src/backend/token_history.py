from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from logger import error_summary, log_event

_history: list[dict[str, Any]] = []
_max_events = 200


def record_token_event(component: str, event: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = {
        "id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "component": component,
        "event": event,
        **(details or {}),
    }
    _history.append(entry)
    del _history[:-_max_events]
    log_event(component, event, details or {})
    return entry


def token_history() -> list[dict[str, Any]]:
    return list(_history)


def token_summary(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) < 2:
        return {"decodeError": "Token is not a JWT"}
    try:
        return {
            "header": _decode_part(parts[0]),
            "claims": _decode_part(parts[1]),
        }
    except Exception as exc:  # noqa: BLE001 - summary only
        return {"decodeError": str(exc)}


def _decode_part(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())


__all__ = ["error_summary", "record_token_event", "token_history", "token_summary"]
