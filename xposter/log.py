from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import append_jsonl, now_utc


def log_event(log_path: Path, event: str, level: str = "info", **fields: Any) -> None:
    payload = {
        "ts": now_utc().isoformat(),
        "level": level,
        "event": event,
        **fields,
    }
    append_jsonl(log_path, payload)
