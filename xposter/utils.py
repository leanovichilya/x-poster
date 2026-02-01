from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import re


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("publish_at is empty")
    value = value.strip()
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    match = re.match(r"^(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})$", value)
    if match:
        parts = {key: int(val) for key, val in match.groupdict().items()}
        return datetime(parts["year"], parts["month"], parts["day"], tzinfo=local_tz)
    match = re.match(r"^(?P<hour>\d{2}):(?P<minute>\d{2})$", value)
    if match:
        parts = {key: int(val) for key, val in match.groupdict().items()}
        now = datetime.now().astimezone()
        return datetime(now.year, now.month, now.day, parts["hour"], parts["minute"], tzinfo=now.tzinfo)
    match = re.match(
        r"^(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})[ T](?P<hour>\d{2}):(?P<minute>\d{2})$",
        value,
    )
    if match:
        parts = {key: int(val) for key, val in match.groupdict().items()}
        return datetime(
            parts["year"],
            parts["month"],
            parts["day"],
            parts["hour"],
            parts["minute"],
            tzinfo=local_tz,
        )
    match = re.match(
        r"^(?P<hour>\d{2}):(?P<minute>\d{2})[ T](?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})$",
        value,
    )
    if match:
        parts = {key: int(val) for key, val in match.groupdict().items()}
        return datetime(
            parts["year"],
            parts["month"],
            parts["day"],
            parts["hour"],
            parts["minute"],
            tzinfo=local_tz,
        )
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def resolve_data_dir(cli_value: Path | None) -> Path:
    if cli_value is not None:
        return cli_value
    env_value = _get_env("XP_DATA_DIR")
    if env_value:
        return Path(env_value)
    return Path.cwd() / "data"


def _get_env(name: str) -> str | None:
    import os

    return os.getenv(name)


def read_json(path: Path) -> Any:
    import json

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def append_jsonl(path: Path, payload: Any) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_code_from_input(user_input: str) -> str:
    user_input = user_input.strip()
    if not user_input:
        raise ValueError("Empty input for authorization code.")
    if "code=" in user_input and "://" in user_input:
        parsed = urlparse(user_input)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        if not code:
            raise ValueError("No code found in URL.")
        return code
    return user_input


@dataclass(frozen=True)
class FileCheck:
    path: Path
    ok: bool
    error: str | None = None
