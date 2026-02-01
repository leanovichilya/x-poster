from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .models import Config, LogEntry, PostJob, VALID_SLOTS

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_PATTERN = re.compile(r"^0[1-4]\.(png|jpg|jpeg|webp)$", re.IGNORECASE)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_data_dir() -> Path:
    import os
    return Path(os.getenv("XP_DATA_DIR", "./data"))


def init_directories(data_dir: Path) -> None:
    (data_dir / "queue").mkdir(parents=True, exist_ok=True)
    for slot in VALID_SLOTS:
        (data_dir / "sent" / slot).mkdir(parents=True, exist_ok=True)
        (data_dir / "failed" / slot).mkdir(parents=True, exist_ok=True)
    if not (data_dir / "log.jsonl").exists():
        (data_dir / "log.jsonl").touch()
    if not (data_dir / "tokens.json").exists():
        (data_dir / "tokens.json").write_text("{}", encoding="utf-8")
    if not (data_dir / "config.json").exists():
        default_config = {
            "timezone": "local",
            "default_times": {"morning": "09:00", "day": "13:00", "night": "22:30"}
        }
        (data_dir / "config.json").write_text(json.dumps(default_config, indent=2), encoding="utf-8")


def discover_images(folder: Path) -> list[Path]:
    images = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and IMAGE_PATTERN.match(f.name):
            images.append(f)
    return images


def parse_scheduled_datetime(date_str: str, time_str: str) -> datetime:
    dt_str = f"{date_str} {time_str}"
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")


def scan_queue(data_dir: Path, config: Config) -> tuple[list[PostJob], list[tuple[Path, str]]]:
    queue_dir = data_dir / "queue"
    jobs = []
    errors = []

    if not queue_dir.exists():
        return jobs, errors

    for date_folder in sorted(queue_dir.iterdir()):
        if not date_folder.is_dir():
            continue
        if not DATE_PATTERN.match(date_folder.name):
            errors.append((date_folder, f"invalid date folder name: {date_folder.name}"))
            continue

        date_str = date_folder.name

        for post_folder in sorted(date_folder.iterdir()):
            if not post_folder.is_dir():
                continue

            post_json = post_folder / "post.json"
            if not post_json.exists():
                errors.append((post_folder, "missing post.json"))
                continue

            try:
                with post_json.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                errors.append((post_folder, f"invalid JSON: {e}"))
                continue

            text = data.get("text", "")
            publish_at = data.get("publish_at", "")
            labels = data.get("labels", [])

            if not labels:
                errors.append((post_folder, "labels array is empty"))
                continue

            slot = labels[0]
            if slot not in VALID_SLOTS:
                errors.append((post_folder, f"first label must be slot (morning/day/night), got '{slot}'"))
                continue

            time_str = publish_at if publish_at else config.get_time_for_slot(slot)

            try:
                scheduled_dt = parse_scheduled_datetime(date_str, time_str)
            except ValueError as e:
                errors.append((post_folder, f"invalid time format: {e}"))
                continue

            images = discover_images(post_folder)

            job = PostJob(
                folder=post_folder,
                text=text,
                publish_at=publish_at,
                labels=labels,
                images=images,
                date_str=date_str,
                slot=slot,
                scheduled_dt=scheduled_dt
            )

            validation_errors = job.validate()
            if validation_errors:
                for err in validation_errors:
                    errors.append((post_folder, err))
                continue

            jobs.append(job)

    return jobs, errors


def get_due_jobs(jobs: list[PostJob], now: datetime | None = None) -> list[PostJob]:
    now = now or datetime.now()
    return [j for j in jobs if j.scheduled_dt <= now]


def move_post(job: PostJob, data_dir: Path, status: str, error_msg: str = "") -> Path:
    now = datetime.now()
    time_str = now.strftime("%H-%M")

    if status == "sent":
        base = data_dir / "sent"
    else:
        base = data_dir / "failed"

    dest = base / job.slot / job.date_str / time_str / job.folder.name
    dest.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(job.folder), str(dest))

    if status == "failed" and error_msg:
        error_file = dest / "error.txt"
        error_file.write_text(error_msg, encoding="utf-8")

    date_folder = job.folder.parent
    if date_folder.exists() and not any(date_folder.iterdir()):
        date_folder.rmdir()

    return dest


def log_attempt(data_dir: Path, entry: LogEntry) -> None:
    log_file = data_dir / "log.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")


def load_tokens(data_dir: Path) -> dict:
    tokens_file = data_dir / "tokens.json"
    if not tokens_file.exists():
        return {}
    with tokens_file.open("r", encoding="utf-8") as f:
        return json.load(f)
