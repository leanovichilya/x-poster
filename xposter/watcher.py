from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from watchfiles import Change, awatch

from .models import Config, LogEntry, PostJob
from .queue import (
    get_due_jobs,
    init_directories,
    load_tokens,
    log_attempt,
    move_post,
    scan_queue,
)

SCHEDULE_FILE = "schedule.json"
DEBOUNCE_SECONDS = 30


def load_schedule(data_dir: Path) -> list[dict]:
    schedule_path = data_dir / SCHEDULE_FILE
    if not schedule_path.exists():
        return []
    try:
        with schedule_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_schedule(data_dir: Path, jobs: list[PostJob]) -> None:
    schedule_path = data_dir / SCHEDULE_FILE
    entries = []
    for job in jobs:
        entries.append({
            "folder": str(job.folder),
            "text": job.text,
            "publish_at": job.publish_at,
            "labels": job.labels,
            "images": [str(p) for p in job.images],
            "date_str": job.date_str,
            "slot": job.slot,
            "scheduled_dt": job.scheduled_dt.isoformat(),
        })
    with schedule_path.open("w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def rebuild_schedule(data_dir: Path, config: Config) -> list[PostJob]:
    jobs, errors = scan_queue(data_dir, config)
    for path, err in errors:
        print(f"[scan error] {path}: {err}")
    jobs_sorted = sorted(jobs, key=lambda j: j.scheduled_dt)
    save_schedule(data_dir, jobs_sorted)
    return jobs_sorted


class Watcher:
    def __init__(
        self,
        data_dir: Path,
        config: Config,
        tokens: dict,
        publish_fn: Callable[[PostJob, dict], tuple[bool, str]],
    ):
        self.data_dir = data_dir
        self.config = config
        self.tokens = tokens
        self.publish_fn = publish_fn
        self.jobs: list[PostJob] = []
        self.next_post_task: asyncio.Task | None = None
        self.debounce_task: asyncio.Task | None = None
        self.running = True

    def get_next_job(self) -> PostJob | None:
        now = datetime.now()
        for job in self.jobs:
            if job.scheduled_dt > now:
                return job
        return None

    def get_due_now(self) -> list[PostJob]:
        now = datetime.now()
        return [j for j in self.jobs if j.scheduled_dt <= now]

    def process_job(self, job: PostJob) -> None:
        print(f"[posting] {job.folder.name}")
        now = datetime.now()

        success, error_msg = self.publish_fn(job, self.tokens)

        if success:
            dest = move_post(job, self.data_dir, "sent")
            status = "sent"
            print(f"  [sent] -> {dest}")
        else:
            dest = move_post(job, self.data_dir, "failed", error_msg)
            status = "failed"
            print(f"  [failed] -> {dest}")
            print(f"  [error] {error_msg}")

        entry = LogEntry(
            timestamp=now.isoformat(),
            status=status,
            slot=job.slot,
            scheduled_datetime=job.scheduled_dt.isoformat(),
            actual_send_time=now.strftime("%H:%M"),
            source_path=str(job.folder),
            destination_path=str(dest),
            labels=job.labels,
            error=error_msg,
        )
        log_attempt(self.data_dir, entry)

        self.jobs = [j for j in self.jobs if j.folder != job.folder]
        save_schedule(self.data_dir, self.jobs)

    def process_due_jobs(self) -> None:
        due = self.get_due_now()
        for job in due:
            self.process_job(job)

    async def schedule_next_post(self) -> None:
        if self.next_post_task and not self.next_post_task.done():
            self.next_post_task.cancel()
            try:
                await self.next_post_task
            except asyncio.CancelledError:
                pass

        self.process_due_jobs()

        next_job = self.get_next_job()
        if not next_job:
            print("[scheduler] No upcoming posts")
            self.next_post_task = None
            return

        now = datetime.now()
        delay = (next_job.scheduled_dt - now).total_seconds()
        if delay < 0:
            delay = 0

        print(f"[scheduler] Next post: {next_job.folder.name} at {next_job.scheduled_dt} (in {delay:.0f}s)")

        async def wait_and_post():
            await asyncio.sleep(delay)
            self.process_job(next_job)
            await self.schedule_next_post()

        self.next_post_task = asyncio.create_task(wait_and_post())

    async def debounced_rescan(self) -> None:
        print(f"[watcher] Changes detected, waiting {DEBOUNCE_SECONDS}s...")
        await asyncio.sleep(DEBOUNCE_SECONDS)
        print("[watcher] Rescanning queue...")
        self.jobs = rebuild_schedule(self.data_dir, self.config)
        print(f"[watcher] Found {len(self.jobs)} post(s)")
        for job in self.jobs:
            print(f"  {job.folder.name} @ {job.scheduled_dt}")
        await self.schedule_next_post()

    def trigger_rescan(self) -> None:
        if self.debounce_task and not self.debounce_task.done():
            self.debounce_task.cancel()
        self.debounce_task = asyncio.create_task(self.debounced_rescan())

    async def watch_files(self) -> None:
        queue_dir = self.data_dir / "queue"
        print(f"[watcher] Watching {queue_dir}")

        async for changes in awatch(queue_dir):
            if not self.running:
                break

            relevant = False
            for change_type, path in changes:
                path_obj = Path(path)
                if path_obj.name == "post.json" or path_obj.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    relevant = True
                    action = {Change.added: "added", Change.modified: "modified", Change.deleted: "deleted"}.get(change_type, "changed")
                    print(f"[watcher] {action}: {path_obj.name}")

            if relevant:
                self.trigger_rescan()

    async def run(self) -> None:
        print("[watcher] Initial scan...")
        self.jobs = rebuild_schedule(self.data_dir, self.config)
        print(f"[watcher] Found {len(self.jobs)} post(s)")
        for job in self.jobs:
            print(f"  {job.folder.name} @ {job.scheduled_dt}")

        await self.schedule_next_post()

        try:
            await self.watch_files()
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            if self.next_post_task:
                self.next_post_task.cancel()
            if self.debounce_task:
                self.debounce_task.cancel()
            save_schedule(self.data_dir, self.jobs)
            print("[watcher] Schedule saved")


def run_watcher(
    data_dir: Path,
    publish_fn: Callable[[PostJob, dict], tuple[bool, str]],
) -> None:
    init_directories(data_dir)
    config = Config.load(data_dir / "config.json")
    tokens = load_tokens(data_dir)

    print("[watcher] Starting x-poster watcher")
    print(f"[watcher] Data dir: {data_dir}")

    watcher = Watcher(data_dir, config, tokens, publish_fn)

    try:
        asyncio.run(watcher.run())
    except KeyboardInterrupt:
        print("\n[watcher] Stopped by user")
