from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path

import typer

from .models import Config, LogEntry
from .queue import (
    get_data_dir,
    get_due_jobs,
    init_directories,
    load_tokens,
    log_attempt,
    move_post,
    scan_queue,
)
from .twitter import XApiError, XClient
from .watcher import run_watcher

app = typer.Typer(help="x-poster CLI")
mimetypes.add_type("image/webp", ".webp")


def publish_job(job, tokens: dict, data_dir: Path) -> tuple[bool, str]:
    access_token = tokens.get("access_token")
    if not access_token:
        return False, "No access_token in tokens.json"

    base_url = tokens.get("base_url", "https://api.twitter.com")
    client = XClient(base_url, access_token)

    media_ids: list[str] = []
    try:
        for image_path in job.images:
            media_type, _ = mimetypes.guess_type(image_path.name)
            if not media_type:
                return False, f"Cannot determine media type for {image_path.name}"
            response = client.upload_media(image_path, media_type)
            media_id = (
                response.get("media_id")
                or response.get("media_id_string")
                or response.get("data", {}).get("id")
            )
            if not media_id:
                return False, f"Upload response missing media_id: {response}"
            media_ids.append(str(media_id))

        client.create_tweet(job.text, media_ids if media_ids else None)
        return True, ""
    except XApiError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


@app.command()
def run(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory"),
) -> None:
    data_dir = data_dir or get_data_dir()
    init_directories(data_dir)
    config = Config.load(data_dir / "config.json")
    tokens = load_tokens(data_dir)

    jobs, errors = scan_queue(data_dir, config)

    for path, err in errors:
        typer.echo(f"Error in {path}: {err}")

    due_jobs = get_due_jobs(jobs)

    if not due_jobs:
        typer.echo("No due posts to process.")
        return

    for job in due_jobs:
        typer.echo(f"Processing: {job.folder}")
        now = datetime.now()

        success, error_msg = publish_job(job, tokens, data_dir)

        if success:
            dest = move_post(job, data_dir, "sent")
            status = "sent"
            typer.echo(f"  Sent -> {dest}")
        else:
            dest = move_post(job, data_dir, "failed", error_msg)
            status = "failed"
            typer.echo(f"  Failed -> {dest}")
            typer.echo(f"  Error: {error_msg}")

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
        log_attempt(data_dir, entry)


@app.command("dry-run")
def dry_run(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory"),
) -> None:
    data_dir = data_dir or get_data_dir()
    init_directories(data_dir)
    config = Config.load(data_dir / "config.json")

    jobs, errors = scan_queue(data_dir, config)

    for path, err in errors:
        typer.echo(f"Error in {path}: {err}")

    due_jobs = get_due_jobs(jobs)

    if not due_jobs:
        typer.echo("No due posts to process.")
        return

    typer.echo(f"Would process {len(due_jobs)} post(s):\n")
    now = datetime.now()
    time_str = now.strftime("%H-%M")

    for job in due_jobs:
        dest_sent = data_dir / "sent" / job.slot / job.date_str / time_str / job.folder.name
        dest_failed = data_dir / "failed" / job.slot / job.date_str / time_str / job.folder.name
        typer.echo(f"Post: {job.folder}")
        typer.echo(f"  Text: {job.text[:50]}{'...' if len(job.text) > 50 else ''}")
        typer.echo(f"  Slot: {job.slot}")
        typer.echo(f"  Scheduled: {job.scheduled_dt}")
        typer.echo(f"  Images: {len(job.images)}")
        typer.echo(f"  On success -> {dest_sent}")
        typer.echo(f"  On failure -> {dest_failed}")
        typer.echo()


@app.command()
def validate(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory"),
) -> None:
    data_dir = data_dir or get_data_dir()
    init_directories(data_dir)
    config = Config.load(data_dir / "config.json")

    jobs, errors = scan_queue(data_dir, config)

    if errors:
        typer.echo("Validation errors:")
        for path, err in errors:
            typer.echo(f"  {path}: {err}")
        raise typer.Exit(code=1)

    typer.echo(f"Validation OK. Found {len(jobs)} valid post(s).")
    for job in jobs:
        typer.echo(f"  {job.folder.name} ({job.slot}, {job.scheduled_dt})")


@app.command()
def init(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory"),
) -> None:
    data_dir = data_dir or get_data_dir()
    init_directories(data_dir)
    typer.echo(f"Initialized data directories in {data_dir}")


def _publish_job_for_watcher(job, tokens: dict) -> tuple[bool, str]:
    return publish_job(job, tokens, None)


@app.command()
def watch(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory"),
    interval: int = typer.Option(30, "--interval", help="Check interval in seconds"),
) -> None:
    data_dir = data_dir or get_data_dir()
    run_watcher(data_dir, _publish_job_for_watcher, interval)


if __name__ == "__main__":
    app()
