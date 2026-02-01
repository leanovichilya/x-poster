from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .utils import parse_iso_datetime


MAX_TWEET_LENGTH = 280
MIN_IMAGES = 1
MAX_IMAGES = 4


class PostJob(BaseModel):
    id: str
    publish_at: datetime | None = None
    text: str = ""
    image_paths: list[Path] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    @field_validator("publish_at", mode="before")
    @classmethod
    def _parse_publish_at(cls, value: Any) -> Any:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return parse_iso_datetime(value)
        return value

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if len(value) > MAX_TWEET_LENGTH:
            raise ValueError(f"text length exceeds {MAX_TWEET_LENGTH} characters")
        return value

    @field_validator("image_paths")
    @classmethod
    def _validate_images(cls, value: list[Path]) -> list[Path]:
        count = len(value)
        if count > MAX_IMAGES:
            raise ValueError(f"image_paths must contain at most {MAX_IMAGES} items")
        return value

    def validate_image_count(self) -> None:
        count = len(self.image_paths)
        if count < MIN_IMAGES or count > MAX_IMAGES:
            raise ValueError(f"image_paths must contain {MIN_IMAGES}-{MAX_IMAGES} items, got {count}")
