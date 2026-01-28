from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_SCOPES = "tweet.read tweet.write users.read media.write offline.access"


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: list[str]
    base_url: str
    auth_url: str
    token_url: str


def load_settings() -> Settings:
    import os

    load_dotenv()
    client_id = os.getenv("X_CLIENT_ID")
    if not client_id:
        raise ValueError("X_CLIENT_ID is required. Set it in your environment or .env.")
    redirect_uri = os.getenv("X_REDIRECT_URI")
    if not redirect_uri:
        raise ValueError("X_REDIRECT_URI is required. Set it in your environment or .env.")
    scopes_value = os.getenv("X_SCOPES", DEFAULT_SCOPES)
    scopes = [scope for scope in scopes_value.split() if scope]
    return Settings(
        client_id=client_id,
        client_secret=os.getenv("X_CLIENT_SECRET") or None,
        redirect_uri=redirect_uri,
        scopes=scopes,
        base_url=os.getenv("X_API_BASE_URL", "https://api.twitter.com"),
        auth_url=os.getenv("X_AUTH_URL", "https://twitter.com/i/oauth2/authorize"),
        token_url=os.getenv("X_TOKEN_URL", "https://api.twitter.com/2/oauth2/token"),
    )


def data_paths(data_dir: Path) -> dict[str, Path]:
    return {
        "data": data_dir,
        "queue": data_dir / "queue",
        "sent": data_dir / "sent",
        "failed": data_dir / "failed",
        "tokens": data_dir / "tokens.json",
        "log": data_dir / "log.jsonl",
    }
