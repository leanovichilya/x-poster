from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any

import typer

from .auth import ensure_access_token, login_flow
from .config import data_paths, load_settings
from .log import log_event
from .queue import (
    init_storage,
    move_with_result,
    resolve_image_path,
    scan_queue,
    sort_ready_jobs,
    validate_job_assets,
)
from .twitter import XApiError, XClient
from .utils import now_utc, resolve_data_dir


app = typer.Typer(help="xposter CLI")
mimetypes.add_type("image/webp", ".webp")
auth_app = typer.Typer(help="Authentication commands")
post_app = typer.Typer(help="Post commands")
app.add_typer(auth_app, name="auth")
app.add_typer(post_app, name="post")


@app.command()
def init(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory (default: ./data or XP_DATA_DIR)."),
) -> None:
    data_dir = resolve_data_dir(data_dir)
    init_storage(data_dir)
    paths = data_paths(data_dir)
    typer.echo(f"Initialized data directories in {paths['data']}")


@auth_app.command("login")
def auth_login(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory (default: ./data or XP_DATA_DIR)."),
) -> None:
    data_dir = resolve_data_dir(data_dir)
    init_storage(data_dir)
    settings = load_settings()
    tokens = login_flow(settings, data_paths(data_dir)["tokens"])
    typer.echo("Tokens saved.")
    typer.echo(f"Scopes: {tokens.get('scope', '')}")


@post_app.command("next")
def post_next(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory (default: ./data or XP_DATA_DIR)."),
    base_dir: Path = typer.Option(
        None, "--base-dir", help="Base directory for relative image paths (default: current working dir)."
    ),
) -> None:
    data_dir = resolve_data_dir(data_dir)
    init_storage(data_dir)
    paths = data_paths(data_dir)
    base_dir = base_dir or Path.cwd()

    jobs = scan_queue(paths["queue"])
    for item in jobs:
        if item.error:
            result = {
                "status": "error",
                "error": {"message": item.error},
                "ts": now_utc().isoformat(),
            }
            move_with_result(item.path, paths["failed"], result)
            log_event(paths["log"], "job_invalid", level="error", job_file=str(item.path), error=item.error)

    ready_jobs = sort_ready_jobs(jobs)
    if not ready_jobs:
        typer.echo("No ready jobs in queue.")
        return

    job_file = ready_jobs[0]
    job = job_file.job
    if job is None:
        typer.echo("No valid jobs found.")
        return

    asset_errors = validate_job_assets(job, base_dir)
    if asset_errors:
        result = {
            "status": "error",
            "error": {"message": "asset validation failed", "details": asset_errors},
            "ts": now_utc().isoformat(),
        }
        move_with_result(job_file.path, paths["failed"], result)
        log_event(paths["log"], "job_invalid_assets", level="error", job_id=job.id, errors=asset_errors)
        typer.echo("Job failed asset validation.")
        return

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
        move_with_result(job_file.path, paths["sent"], result)
        log_event(paths["log"], "job_sent", job_id=job.id, media_count=len(media_ids))
        typer.echo("Post created successfully.")
    except XApiError as exc:
        result = {
            "status": "error",
            "job_id": job.id,
            "error": {"message": str(exc), "status_code": exc.status_code, "payload": exc.payload},
            "ts": now_utc().isoformat(),
        }
        move_with_result(job_file.path, paths["failed"], result)
        log_event(
            paths["log"],
            "job_failed",
            level="error",
            job_id=job.id,
            status_code=exc.status_code,
        )
        typer.echo("Post failed. See result file for details.")


@app.command()
def run(
    interval: int = typer.Option(30, "--interval", help="Seconds between attempts."),
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory (default: ./data or XP_DATA_DIR)."),
    base_dir: Path = typer.Option(
        None, "--base-dir", help="Base directory for relative image paths (default: current working dir)."
    ),
) -> None:
    typer.echo("Starting xposter run loop. Press Ctrl+C to stop.")
    while True:
        try:
            post_next(data_dir=data_dir, base_dir=base_dir)
        except Exception as exc:
            typer.echo(f"Error: {exc}")
        time.sleep(interval)


@app.command()
def validate(
    data_dir: Path = typer.Option(None, "--data-dir", help="Data directory (default: ./data or XP_DATA_DIR)."),
    base_dir: Path = typer.Option(
        None, "--base-dir", help="Base directory for relative image paths (default: current working dir)."
    ),
) -> None:
    data_dir = resolve_data_dir(data_dir)
    init_storage(data_dir)
    paths = data_paths(data_dir)
    base_dir = base_dir or Path.cwd()

    errors: list[str] = []
    jobs = scan_queue(paths["queue"])
    for item in jobs:
        if item.error:
            errors.append(f"{item.path.name}: {item.error}")
            continue
        job = item.job
        if job is None:
            continue
        asset_errors = validate_job_assets(job, base_dir)
        for asset_error in asset_errors:
            errors.append(f"{item.path.name}: {asset_error}")

    if errors:
        typer.echo("Validation failed:")
        for err in errors:
            typer.echo(f"- {err}")
        raise typer.Exit(code=1)
    typer.echo("Validation OK.")


if __name__ == "__main__":
    app()
