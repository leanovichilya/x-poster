from __future__ import annotations

import asyncio
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

from .config import data_paths, load_settings
from .auth import ensure_access_token
from .log import log_event
from .models import PostJob
from .queue import (
    delete_job_files,
    discover_images,
    init_storage,
    move_with_result,
    resolve_image_path,
    validate_job_assets,
)
from .twitter import XApiError, XClient
from .utils import now_utc, read_json, write_json


mimetypes.add_type("image/webp", ".webp")


class ScheduleEntry:
    def __init__(self, path: str, publish_at: datetime):
        self.path = path
        self.publish_at = publish_at

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "publish_at": self.publish_at.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleEntry:
        from .utils import parse_iso_datetime
        return cls(data["path"], parse_iso_datetime(data["publish_at"]))


def load_schedule(schedule_path: Path) -> list[ScheduleEntry]:
    if not schedule_path.exists():
        return []
    try:
        data = read_json(schedule_path)
        return [ScheduleEntry.from_dict(item) for item in data]
    except Exception:
        return []


def save_schedule(schedule_path: Path, entries: list[ScheduleEntry]) -> None:
    entries.sort(key=lambda e: e.publish_at)
    write_json(schedule_path, [e.to_dict() for e in entries])


def add_to_schedule(schedule_path: Path, job_path: Path, publish_at: datetime) -> None:
    entries = load_schedule(schedule_path)
    entries = [e for e in entries if e.path != str(job_path)]
    entries.append(ScheduleEntry(str(job_path), publish_at))
    save_schedule(schedule_path, entries)


def remove_from_schedule(schedule_path: Path, job_path: Path) -> None:
    entries = load_schedule(schedule_path)
    entries = [e for e in entries if e.path != str(job_path)]
    save_schedule(schedule_path, entries)


def next_scheduled_time(schedule_path: Path) -> datetime | None:
    entries = load_schedule(schedule_path)
    if not entries:
        return None
    return entries[0].publish_at


def pop_ready_jobs(schedule_path: Path) -> list[Path]:
    entries = load_schedule(schedule_path)
    now = now_utc()
    ready = [Path(e.path) for e in entries if e.publish_at <= now]
    remaining = [e for e in entries if e.publish_at > now]
    save_schedule(schedule_path, remaining)
    return ready


def parse_job_file(path: Path, img_dir: Path) -> tuple[PostJob | None, str | None]:
    try:
        payload = read_json(path)
        job = PostJob.model_validate(payload)
        if not job.image_paths:
            discovered = discover_images(path, img_dir)
            job = job.model_copy(update={"image_paths": discovered})
        job.validate_image_count()
        return job, None
    except Exception as exc:
        return None, str(exc)


def post_job(job: PostJob, job_path: Path, paths: dict[str, Path], base_dir: Path) -> bool:
    asset_errors = validate_job_assets(job, base_dir)
    if asset_errors:
        result = {
            "status": "error",
            "error": {"message": "asset validation failed", "details": asset_errors},
            "ts": now_utc().isoformat(),
        }
        move_with_result(job_path, paths["failed"], result)
        log_event(paths["log"], "job_invalid_assets", level="error", job_id=job.id, errors=asset_errors)
        return False

    settings = load_settings()
    access_token = ensure_access_token(settings, paths["tokens"])
    client = XClient(settings.base_url, access_token)

    uploads: list[dict[str, Any]] = []
    media_ids: list[str] = []
    try:
        for image_path in job.image_paths:
            resolved = resolve_image_path(image_path, base_dir)
            media_type, _ = mimetypes.guess_type(resolved.name)
            if not media_type:
                raise XApiError(f"Unable to determine media type for {resolved.name}")
            upload_response = client.upload_media(resolved, media_type)
            uploads.append(upload_response)
            media_id = (
                upload_response.get("media_id")
                or upload_response.get("media_id_string")
                or upload_response.get("data", {}).get("id")
            )
            if not media_id:
                raise XApiError("Upload response missing media_id", payload=upload_response)
            media_ids.append(str(media_id))

        tweet_response = client.create_tweet(job.text, media_ids)
        result = {
            "status": "success",
            "job_id": job.id,
            "uploads": uploads,
            "tweet": tweet_response,
            "ts": now_utc().isoformat(),
        }
        move_with_result(job_path, paths["sent"], result)
        log_event(paths["log"], "job_sent", job_id=job.id, media_count=len(media_ids))
        # Delete original files after successful send
        delete_job_files(job_path, paths["img"])
        return True
    except XApiError as exc:
        result = {
            "status": "error",
            "job_id": job.id,
            "error": {"message": str(exc), "status_code": exc.status_code, "payload": exc.payload},
            "ts": now_utc().isoformat(),
        }
        move_with_result(job_path, paths["failed"], result)
        log_event(paths["log"], "job_failed", level="error", job_id=job.id, status_code=exc.status_code)
        return False


async def process_new_file(path: Path, paths: dict[str, Path], base_dir: Path) -> None:
    if not path.exists() or not path.suffix == ".json":
        return
    if path.name.endswith(".result.json"):
        return

    job, error = parse_job_file(path, paths["img"])
    if error:
        result = {
            "status": "error",
            "error": {"message": error},
            "ts": now_utc().isoformat(),
        }
        move_with_result(path, paths["failed"], result)
        log_event(paths["log"], "job_invalid", level="error", job_file=str(path), error=error)
        print(f"[ERROR] {path.name}: {error}")
        return

    if job is None:
        return

    if job.publish_at and job.publish_at > now_utc():
        add_to_schedule(paths["schedule"], path, job.publish_at)
        print(f"[SCHEDULED] {path.name} -> {job.publish_at.isoformat()}")
    else:
        print(f"[POSTING] {path.name}")
        success = post_job(job, path, paths, base_dir)
        if success:
            print(f"[SENT] {path.name}")
        else:
            print(f"[FAILED] {path.name}")


async def process_scheduled(paths: dict[str, Path], base_dir: Path) -> None:
    ready_jobs = pop_ready_jobs(paths["schedule"])
    for job_path in ready_jobs:
        if not job_path.exists():
            continue
        job, error = parse_job_file(job_path, paths["img"])
        if error or job is None:
            print(f"[ERROR] Scheduled job {job_path.name}: {error}")
            continue
        print(f"[POSTING] {job_path.name} (scheduled)")
        success = post_job(job, job_path, paths, base_dir)
        if success:
            print(f"[SENT] {job_path.name}")
        else:
            print(f"[FAILED] {job_path.name}")


async def watch_loop(data_dir: Path, base_dir: Path, debounce_seconds: float = 30.0) -> None:
    init_storage(data_dir)
    paths = data_paths(data_dir)
    queue_dir = paths["queue"]

    print(f"Watching {queue_dir} for new jobs...")
    print(f"Debounce: {int(debounce_seconds)}s after last file change")
    print("Press Ctrl+C to stop.")

    # Process existing files on startup
    for path in queue_dir.glob("*.json"):
        if not path.name.endswith(".result.json"):
            await process_new_file(path, paths, base_dir)

    async def scheduler() -> None:
        while True:
            next_time = next_scheduled_time(paths["schedule"])
            if next_time:
                wait_seconds = (next_time - now_utc()).total_seconds()
                if wait_seconds <= 0:
                    await process_scheduled(paths, base_dir)
                else:
                    print(f"[SCHEDULER] Next post at {next_time.isoformat()} (in {int(wait_seconds)}s)")
                    await asyncio.sleep(min(wait_seconds, 60))
            else:
                await asyncio.sleep(60)

    async def watcher() -> None:
        pending_files: set[Path] = set()
        last_change_time: float = 0

        async for changes in awatch(queue_dir):
            for change_type, change_path in changes:
                path = Path(change_path)
                if change_type == Change.added and path.suffix == ".json":
                    if not path.name.endswith(".result.json"):
                        pending_files.add(path)
                        last_change_time = asyncio.get_event_loop().time()
                        print(f"[QUEUED] {path.name} (waiting {int(debounce_seconds)}s...)")

            # Check if debounce period has passed
            while pending_files:
                current_time = asyncio.get_event_loop().time()
                elapsed = current_time - last_change_time
                if elapsed >= debounce_seconds:
                    # Process all pending files
                    to_process = list(pending_files)
                    pending_files.clear()
                    for path in to_process:
                        await process_new_file(path, paths, base_dir)
                    break
                else:
                    remaining = debounce_seconds - elapsed
                    # Wait for remaining time or next change
                    try:
                        async for new_changes in awatch(queue_dir, stop_event=asyncio.Event()):
                            for change_type, change_path in new_changes:
                                path = Path(change_path)
                                if change_type == Change.added and path.suffix == ".json":
                                    if not path.name.endswith(".result.json"):
                                        pending_files.add(path)
                                        last_change_time = asyncio.get_event_loop().time()
                                        print(f"[QUEUED] {path.name} (timer reset to {int(debounce_seconds)}s)")
                            break
                    except asyncio.TimeoutError:
                        pass
                    await asyncio.sleep(1)

    await asyncio.gather(scheduler(), watcher())


def run_watch(data_dir: Path, base_dir: Path) -> None:
    asyncio.run(watch_loop(data_dir, base_dir))
