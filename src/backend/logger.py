from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from typing import Any


def log_event(component: str, event: str, details: dict[str, Any] | None = None) -> None:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    details = details or {}
    fields = []
    multiline = []
    for key, value in details.items():
        if value in (None, ""):
            continue
        rendered = _format_value(value)
        entry = f"{key}={rendered}"
        if "\n" in entry:
            multiline.append(entry)
        else:
            fields.append(entry)
    first = f"[{timestamp}] [{component}] {event}"
    if fields:
        first = f"{first} {' '.join(fields)}"
    print("\n".join([first, *multiline]), flush=True)


def error_summary(error: BaseException) -> dict[str, Any]:
    summary = {
        "name": error.__class__.__name__,
        "message": str(error),
        "code": getattr(error, "code", None),
        "status": getattr(error, "status_code", None),
    }
    upstream_status = getattr(error, "upstream_status_code", None)
    if upstream_status is not None:
        summary["upstreamStatus"] = upstream_status
    upstream_url = getattr(error, "url", None)
    if upstream_url:
        summary["url"] = upstream_url
    upstream_body = getattr(error, "body", None)
    if upstream_body:
        summary["body"] = upstream_body
    nested = getattr(error, "exceptions", None)
    if nested:
        summary["exceptions"] = [error_summary(item) for item in nested]
    summary["traceback"] = "".join(traceback.format_exception(error.__class__, error, error.__traceback__))
    return summary


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return "\n" + json.dumps(value, indent=2, default=str)
    return str(value).replace(" ", "_")
