from __future__ import annotations

from urllib.parse import urlencode

from spiffe import WorkloadApiClient
from spiffe.spiffe_id.spiffe_id import SpiffeId

from config import ServiceConfig
from logger import error_summary
from token_history import record_token_event, token_summary

subject_token_type = "urn:ietf:params:oauth:token-type:access_token"
actor_token_type = "urn:ietf:params:oauth:token-type:jwt"
token_exchange_grant_type = "urn:ietf:params:oauth:grant-type:token-exchange"
static_demo_actor_token = "telco-demo-static-jwt-svid"


def get_actor_token(config: ServiceConfig, spiffe_id: str | None = None) -> str:
    if config.no_security:
        return static_demo_actor_token
    if config.spiffe_jwt_svid.strip():
        return config.spiffe_jwt_svid.strip()
    if not config.spiffe_endpoint_socket or not config.spiffe_jwt_svid_audience:
        raise RuntimeError("SPIFFE_ENDPOINT_SOCKET and SPIFFE_JWT_SVID_AUDIENCE are required")

    socket_path = _normalize_socket(config.spiffe_endpoint_socket)
    record_token_event("spiffe-workload-api", "jwt-svid-fetch-start", {
        "socketPath": socket_path,
        "audience": config.spiffe_jwt_svid_audience,
        "requestedSpiffeId": spiffe_id,
    })
    try:
        with WorkloadApiClient(socket_path=socket_path, default_timeout=5.0) as client:
            subject = SpiffeId(spiffe_id) if spiffe_id else None
            svid = client.fetch_jwt_svid(audience={config.spiffe_jwt_svid_audience}, subject=subject, timeout=5.0)
    except Exception as exc:
        record_token_event("spiffe-workload-api", "jwt-svid-fetch-failed", {
            "socketPath": socket_path,
            "audience": config.spiffe_jwt_svid_audience,
            "requestedSpiffeId": spiffe_id,
            "error": error_summary(exc),
        })
        raise

    record_token_event("spiffe-workload-api", "jwt-svid-fetched", {
        "socketPath": socket_path,
        "audience": config.spiffe_jwt_svid_audience,
        "requestedSpiffeId": spiffe_id,
        "returnedSpiffeId": str(svid.spiffe_id),
        "token": token_summary(svid.token),
    })
    return svid.token


def build_token_exchange_body(
    subject_token: str,
    actor_token: str,
    scope: str,
    resource: str = "",
    client_id: str = "",
) -> str:
    body = {
        "grant_type": token_exchange_grant_type,
        "subject_token": subject_token,
        "subject_token_type": subject_token_type,
        "actor_token": actor_token,
        "actor_token_type": actor_token_type,
        "scope": scope,
    }
    if resource:
        body["resource"] = resource
    if client_id:
        body["client_id"] = client_id
    return urlencode(body)


def token_exchange_request_summary(
    *,
    scope: str,
    resource: str = "",
    client_id: str = "",
    client_auth_method: str = "none",
) -> dict:
    return {
        "grant_type": token_exchange_grant_type,
        "subject_token_type": subject_token_type,
        "actor_token_type": actor_token_type,
        "scope": scope,
        "resource": resource,
        "client_id": client_id,
        "client_auth_method": client_auth_method,
        "authorization_header": "not sent",
    }


def token_exchange_response_summary(body: dict) -> dict:
    summary = dict(body)
    access_token = summary.pop("access_token", None)
    refresh_token = summary.pop("refresh_token", None)
    id_token = summary.pop("id_token", None)
    if access_token:
        summary["accessToken"] = token_summary(access_token)
    if refresh_token:
        summary["refreshToken"] = "<redacted>"
    if id_token:
        summary["idToken"] = token_summary(id_token)
    return summary


def _normalize_socket(value: str) -> str:
    if value.startswith("unix:"):
        return value
    return f"unix:{value}"
