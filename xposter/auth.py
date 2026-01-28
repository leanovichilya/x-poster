from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .utils import extract_code_from_input, read_json, write_json


TOKEN_EXPIRY_SKEW = timedelta(seconds=60)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce_pair() -> tuple[str, str]:
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def build_auth_url(settings: Settings, code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": " ".join(settings.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.auth_url}?{urlencode(params)}"


def exchange_code_for_tokens(
    settings: Settings,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "code_verifier": code_verifier,
    }
    auth = None
    if settings.client_secret:
        auth = (settings.client_id, settings.client_secret)
    with httpx.Client(timeout=30) as client:
        response = client.post(settings.token_url, data=data, auth=auth)
    response.raise_for_status()
    return response.json()


def refresh_tokens(settings: Settings, refresh_token: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "refresh_token": refresh_token,
    }
    auth = None
    if settings.client_secret:
        auth = (settings.client_id, settings.client_secret)
    with httpx.Client(timeout=30) as client:
        response = client.post(settings.token_url, data=data, auth=auth)
    response.raise_for_status()
    return response.json()


def save_tokens(tokens_path: Path, token_data: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    tokens = dict(existing or {})
    tokens.update(token_data)
    expires_in = tokens.get("expires_in")
    if expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        tokens["expires_at"] = expires_at.isoformat()
    write_json(tokens_path, tokens)
    return tokens


def load_tokens(tokens_path: Path) -> dict[str, Any] | None:
    if not tokens_path.exists():
        return None
    try:
        payload = read_json(tokens_path)
        return payload if payload else None
    except Exception:
        return None


def tokens_expired(tokens: dict[str, Any]) -> bool:
    expires_at = tokens.get("expires_at")
    if not expires_at:
        return False
    try:
        value = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    return value <= datetime.now(timezone.utc) + TOKEN_EXPIRY_SKEW


def ensure_access_token(settings: Settings, tokens_path: Path) -> str:
    tokens = load_tokens(tokens_path)
    if not tokens:
        raise RuntimeError("No tokens found. Run `xposter auth login` first.")
    if tokens_expired(tokens):
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Token expired and no refresh_token found. Run `xposter auth login` again.")
        refreshed = refresh_tokens(settings, refresh_token)
        tokens = save_tokens(tokens_path, refreshed, existing=tokens)
    access_token = tokens.get("access_token")
    if not access_token:
        raise RuntimeError("Access token missing. Run `xposter auth login` again.")
    return access_token


def login_flow(settings: Settings, tokens_path: Path) -> dict[str, Any]:
    code_verifier, code_challenge = generate_pkce_pair()
    state = _base64url(os.urandom(16))
    auth_url = build_auth_url(settings, code_challenge, state)
    print("Open this URL to authorize:")
    print(auth_url)
    print("After approval, paste the authorization code or full redirect URL here.")
    user_input = input("code> ").strip()
    code = extract_code_from_input(user_input)
    token_data = exchange_code_for_tokens(settings, code, code_verifier)
    return save_tokens(tokens_path, token_data)
