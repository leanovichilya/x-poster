from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MAX_TWEET_LENGTH = 280
MAX_IMAGES = 4
VALID_SLOTS = {"morning", "day", "night"}


@dataclass
class PostJob:
    folder: Path
    text: str
    publish_at: str
    labels: list[str]
    images: list[Path]
    date_str: str
    slot: str
    scheduled_dt: datetime

    def validate(self) -> list[str]:
        errors = []
        if len(self.text) > MAX_TWEET_LENGTH:
            errors.append(f"text exceeds {MAX_TWEET_LENGTH} characters")
        if not self.labels:
            errors.append("labels array is empty, first label must be slot (morning/day/night)")
        elif self.labels[0] not in VALID_SLOTS:
            errors.append(f"first label must be one of {VALID_SLOTS}, got '{self.labels[0]}'")
        if len(self.images) > MAX_IMAGES:
            errors.append(f"more than {MAX_IMAGES} images found")
        return errors


@dataclass
class Config:
    timezone: str
    default_times: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Config:
        import json
        if not path.exists():
            return cls(timezone="local", default_times={"morning": "09:00", "day": "13:00", "night": "22:30"})
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            timezone=data.get("timezone", "local"),
            default_times=data.get("default_times", {"morning": "09:00", "day": "13:00", "night": "22:30"})
        )

    def get_time_for_slot(self, slot: str) -> str:
        return self.default_times.get(slot, "12:00")


@dataclass
class LogEntry:
    timestamp: str
    status: str
    slot: str
    scheduled_datetime: str
    actual_send_time: str
    source_path: str
    destination_path: str
    labels: list[str]
    error: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "slot": self.slot,
            "scheduled_datetime": self.scheduled_datetime,
            "actual_send_time": self.actual_send_time,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "labels": self.labels,
            "error": self.error
        }
