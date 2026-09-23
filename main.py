import csv
import io
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from bsky_client import BlueSkyClient
from config import get_settings
from database import create_database, list_targets, target_counts
from worker import BotWorker

settings = get_settings()
logger = logging.getLogger("bsky_bot")
logger.setLevel(settings.log_level.upper())
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
file_handler = logging.FileHandler(settings.log_path, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(console_handler)
logger.addHandler(file_handler)

engine, session_factory = create_database(settings)
logs: deque[dict[str, str]] = deque(maxlen=250)


def publish_log(message: str) -> None:
    logs.append({"timestamp": datetime.now().isoformat(timespec="seconds"), "message": message})


client = BlueSkyClient(settings.bsky_handle, settings.bsky_app_password)
worker = BotWorker(settings, session_factory, client, publish_log)
templates = Jinja2Templates(directory="templates")


def update_env_file(key: str, value: str) -> None:
    env_path = Path(".env")
    raw_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    new_lines = []
    updated = False
    for line in raw_lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("BlueSky Automation Bot ready")
    yield
    if worker.status in {"running", "paused"}:
        await worker.stop()
    engine.dispose()


app = FastAPI(title="BlueSky Automation Bot", lifespan=lifespan)


class SettingsUpdate(BaseModel):
    keywords: list[str] = Field(min_length=1)
    max_followers: int = Field(ge=1, le=10000)
    dry_run: bool | None = None


class PostImport(BaseModel):
    post_url: str = Field(min_length=1, max_length=500)


class AccountConfig(BaseModel):
    bsky_handle: str = Field(min_length=1, max_length=200)
    bsky_app_password: str = Field(min_length=1, max_length=500)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"settings": settings},
    )


@app.get("/healthz")
async def healthcheck():
    return {
        "status": "ok",
        "worker": worker.status,
        "database": "connected",
    }


@app.get("/api/status")
async def api_status():
    with session_factory() as session:
        targets = list_targets(session)
        counts = target_counts(session)
    return {
        "status": worker.status,
        "last_error": worker.last_error,
        "dry_run": settings.dry_run,
        "account_handle": settings.bsky_handle,
        "target_counts": counts,
        "logs": list(logs),
        "targets": [
            {
                "handle": item.handle,
                "did": item.did,
                "follower_count": item.follower_count,
                "matched_keyword": item.matched_keyword,
                "followed_at_timestamp": item.followed_at_timestamp.isoformat() if item.followed_at_timestamp else None,
                "status": item.status,
            }
            for item in targets
        ],
    }


@app.post("/api/start")
async def api_start():
    missing = []
    if not settings.bsky_handle:
        missing.append("BSKY_HANDLE")
    if not settings.bsky_app_password:
        missing.append("BSKY_APP_PASSWORD")
    if missing:
        raise HTTPException(400, f"Missing {', '.join(missing)}. Copy .env.example to .env and add your BlueSky App Password.")
    await worker.start()
    return {"status": worker.status}


@app.post("/api/pause")
async def api_pause():
    worker.pause()
    return {"status": worker.status}


@app.post("/api/resume")
async def api_resume():
    worker.resume()
    return {"status": worker.status}


@app.post("/api/stop")
async def api_stop():
    await worker.stop()
    return {"status": worker.status}


@app.post("/api/settings")
async def api_settings(update: SettingsUpdate):
    settings.search_keywords = [item.strip() for item in update.keywords if item.strip()]
    settings.max_followers = update.max_followers
    if update.dry_run is not None:
        settings.dry_run = update.dry_run
        publish_log(f"Mode changed to {'dry run' if settings.dry_run else 'live mode'}")
    publish_log(f"Settings updated: {len(settings.search_keywords)} keywords, < {settings.max_followers} followers")
    return {"keywords": settings.search_keywords, "max_followers": settings.max_followers, "dry_run": settings.dry_run}


@app.post("/api/account")
async def api_account(update: AccountConfig):
    handle = update.bsky_handle.strip().lstrip("@")
    password = update.bsky_app_password.strip()
    if not handle:
        raise HTTPException(400, "BlueSky handle cannot be empty")
    if not password:
        raise HTTPException(400, "BlueSky App Password cannot be empty")

    settings.bsky_handle = handle
    settings.bsky_app_password = password
    client.handle = handle
    client.app_password = password
    client.logged_in = False

    update_env_file("BSKY_HANDLE", handle)
    update_env_file("BSKY_APP_PASSWORD", password)
    publish_log(f"Account updated to @{handle}")
    return {"handle": handle, "status": worker.status}


@app.post("/api/import-likers")
async def api_import_likers(import_request: PostImport):
    try:
        matched = await worker.import_post_likers(import_request.post_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Bluesky post import failed")
        raise HTTPException(502, f"Could not import likers: {exc}") from exc
    return {"matched": matched}


@app.get("/api/export.csv")
async def export_csv():
    with session_factory() as session:
        targets = list_targets(session, 5000)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["handle", "did", "follower_count", "matched_keyword", "followed_at_timestamp", "status"])
    for item in targets:
        writer.writerow([item.handle, item.did, item.follower_count, item.matched_keyword, item.followed_at_timestamp, item.status])
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=target-users.csv"})
