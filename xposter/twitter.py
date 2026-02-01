from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx

mimetypes.add_type("image/webp", ".webp")

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


class XApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class XClient:
    def __init__(self, base_url: str, access_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "xposter/0.1.0",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            raise XApiError(
                f"API error {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        return response.json()

    def upload_media(self, image_path: Path, media_type: str) -> dict[str, Any]:
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise XApiError(f"Unsupported media_type {media_type}")
        url = f"{self.base_url}/2/media/upload"
        with image_path.open("rb") as f:
            files = {"media": (image_path.name, f, media_type)}
            data = {"media_category": "tweet_image", "media_type": media_type}
            with httpx.Client(timeout=60) as client:
                response = client.post(url, headers=self._headers(), files=files, data=data)
        return self._handle_response(response)

    def create_tweet(self, text: str, media_ids: list[str] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/2/tweets"
        payload: dict[str, Any] = {}
        if text.strip():
            payload["text"] = text
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        if not payload:
            raise XApiError("Tweet must include text or media")
        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=self._headers(), json=payload)
        return self._handle_response(response)
