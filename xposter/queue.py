from __future__ import annotations

import json
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .config import data_paths
from .models import PostJob
from .utils import FileCheck, now_utc, read_json, write_json


mimetypes.add_type("image/webp", ".webp")

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class JobFile:
    path: Path
    job: PostJob | None
    error: str | None


def init_storage(data_dir: Path) -> None:
    paths = data_paths(data_dir)
    for key in ("queue", "sent", "failed"):
        paths[key].mkdir(parents=True, exist_ok=True)
    if not paths["tokens"].exists():
        write_json(paths["tokens"], {})
    if not paths["log"].exists():
        paths["log"].touch()


def list_queue_files(queue_dir: Path) -> list[Path]:
    if not queue_dir.exists():
        return []
    files = sorted(queue_dir.glob("*.json"))
    return [path for path in files if not path.name.endswith(".result.json")]


def scan_queue(queue_dir: Path) -> list[JobFile]:
    jobs: list[JobFile] = []
    for path in list_queue_files(queue_dir):
        try:
            payload = read_json(path)
            job = PostJob.model_validate(payload)
            jobs.append(JobFile(path=path, job=job, error=None))
        except Exception as exc:  # noqa: BLE001 - we want to capture parsing errors
            jobs.append(JobFile(path=path, job=None, error=str(exc)))
    return jobs


def is_ready(job: PostJob, now: datetime | None = None) -> bool:
    now = now or now_utc()
    if job.publish_at is None:
        return True
    return job.publish_at <= now


def resolve_image_path(path: Path, base_dir: Path) -> Path:
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def check_image_file(path: Path) -> FileCheck:
    if not path.exists():
        return FileCheck(path=path, ok=False, error="file not found")
    if not path.is_file():
        return FileCheck(path=path, ok=False, error="not a file")
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        return FileCheck(path=path, ok=False, error=f"file size {size} exceeds {MAX_IMAGE_BYTES} bytes")
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type not in ALLOWED_MEDIA_TYPES:
        return FileCheck(path=path, ok=False, error=f"unsupported media type {media_type}")
    return FileCheck(path=path, ok=True)


def validate_job_assets(job: PostJob, base_dir: Path) -> list[str]:
    errors: list[str] = []
    for image_path in job.image_paths:
        resolved = resolve_image_path(image_path, base_dir)
        check = check_image_file(resolved)
        if not check.ok:
            errors.append(f"{image_path}: {check.error}")
    return errors


def sort_ready_jobs(jobs: Iterable[JobFile]) -> list[JobFile]:
    now = now_utc()
    ready: list[JobFile] = []
    for item in jobs:
        if item.job and is_ready(item.job):
            ready.append(item)
    def sort_key(item: JobFile) -> tuple[datetime, str]:
        publish_at = item.job.publish_at or now
        return (publish_at, item.path.name)
    return sorted(ready, key=sort_key)


def move_with_result(src: Path, dest_dir: Path, result: dict) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / src.name
    shutil.move(str(src), str(dest_path))
    result_path = dest_path.with_suffix(".result.json")
    with result_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return dest_path
