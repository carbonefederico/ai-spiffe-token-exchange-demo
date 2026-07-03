from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException

from config import OidcConfig
from logger import error_summary
from token_history import record_token_event, token_summary

static_demo_token = "telco-demo-static-token"
static_demo_payload = {
    "sub": "static-demo-user",
    "name": "Static Demo User",
    "email": "static.demo@example.com",
    "customer_id": "cust-1001",
    "scope": "openid profile customer:profile:read customer:payments:read",
}

_jwks_cache: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class AuthContext:
    token: str
    payload: dict[str, Any]
    scopes: list[str]
    subject: str
    customer_id: str
    mode: str


async def require_auth(
    authorization: str | None,
    config: OidcConfig,
    component: str,
    tls_verify: bool,
) -> AuthContext:
    try:
        if config.no_security:
            auth = normalize_auth(static_demo_payload, static_demo_token, "no_security")
            record_token_event(component, "api-token-accepted", {
                "mode": auth.mode,
                "subject": auth.subject,
                "scopes": auth.scopes,
                "token": token_summary(auth.token),
            })
            return auth

        token = extract_bearer_token(authorization)
        record_token_event(component, "api-token-received", {"token": token_summary(token)})
        auth = await verify_access_token(token, config, tls_verify)
        record_token_event(component, "api-token-accepted", {
            "mode": auth.mode,
            "subject": auth.subject,
            "customerId": auth.customer_id,
            "scopes": auth.scopes,
            "expectedIssuer": config.issuer,
            "expectedAudience": config.audience,
            "token": token_summary(token),
        })
        return auth
    except Exception as exc:
        record_token_event(component, "api-token-rejected", {
            "expectedIssuer": config.issuer,
            "expectedAudience": config.audience,
            "error": error_summary(exc),
        })
        status = getattr(exc, "status_code", 401)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def extract_bearer_token(header: str | None) -> str:
    if not header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer scheme")
    return token


async def verify_access_token(token: str, config: OidcConfig, tls_verify: bool) -> AuthContext:
    jwks = await _load_jwks(config.jwks_uri, tls_verify)
    header = jwt.get_unverified_header(token)
    key_data = next((key for key in jwks.get("keys", []) if key.get("kid") == header.get("kid")), None)
    if not key_data:
        raise HTTPException(status_code=401, detail="No matching JWK for token")
    key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
    payload = jwt.decode(
        token,
        key=key,
        algorithms=[header.get("alg", "RS256")],
        issuer=config.issuer or None,
        audience=config.audience or None,
        options={"verify_aud": bool(config.audience)},
    )
    return normalize_auth(payload, token, "jwks")


def normalize_auth(payload: dict[str, Any], token: str, mode: str) -> AuthContext:
    scopes = parse_scopes(payload)
    subject = payload.get("sub") or "anonymous"
    customer_id = (
        payload.get("customer_id")
        or payload.get("customerId")
        or payload.get("https://telco.example/customer_id")
        or subject
        or "cust-1001"
    )
    return AuthContext(token=token, payload=payload, scopes=scopes, subject=subject, customer_id=customer_id, mode=mode)


def parse_scopes(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("scope", "scp", "permissions"):
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif isinstance(raw, str):
            values.extend(raw.split())
    return sorted(set(value.strip() for value in values if value.strip()))


def require_scope(auth: AuthContext, required_scope: str) -> None:
    if required_scope not in auth.scopes:
        raise HTTPException(status_code=403, detail=f"Missing required scope: {required_scope}")


async def _load_jwks(jwks_uri: str, tls_verify: bool) -> dict[str, Any]:
    if not jwks_uri:
        raise HTTPException(status_code=500, detail="OIDC discovery metadata must provide jwks_uri")
    if jwks_uri not in _jwks_cache:
        async with httpx.AsyncClient(verify=tls_verify, timeout=10) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            _jwks_cache[jwks_uri] = response.json()
    return _jwks_cache[jwks_uri]


async def fastapi_auth_dependency(
    authorization: str | None = Header(default=None),
) -> str | None:
    return authorization
