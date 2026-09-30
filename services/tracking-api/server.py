#!/usr/bin/env python3
"""SQLite tracking API for the n8n 3D printing social workflows.

This is not an automation engine. n8n owns scheduling, AI calls, and publishing.
This service stores product status, enforces duplicate protection, and logs events.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import traceback
from datetime import date, datetime, timedelta, timezone, tzinfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request
import http.cookiejar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(os.environ.get("APP_ROOT", "/data"))
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "db" / "tracking.sqlite")))
SCHEMA_PATH = Path(os.environ.get("SCHEMA_PATH", "/app/schema.sql"))
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", str(ROOT / "config" / "settings.json")))
PROMPTS_DIR = Path(os.environ.get("PROMPTS_DIR", str(ROOT / "config" / "prompts")))
SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", str(ROOT / "samples")))
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", str(ROOT / "media")))
PREVIEWS_DIR = Path(os.environ.get("PREVIEWS_DIR", str(ROOT / "previews")))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", str(ROOT / "logs")))
HOST = os.environ.get("TRACKING_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("TRACKING_API_PORT", "8081"))
SCHEDULE_PATH = Path(os.environ.get("SCHEDULE_PATH", str(CONFIG_PATH.parent / "schedule.json")))
SCHEDULE_DEFAULTS = {"publish_time": "09:00", "timezone": "Asia/Kolkata", "queue_size": 3}
PUBLISH_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SCHEDULER_TICK_SECONDS = int(os.environ.get("SCHEDULER_TICK_SECONDS", "30"))
PREPARE_COOLDOWN_SECONDS = int(os.environ.get("PREPARE_COOLDOWN_SECONDS", "300"))
PREPARE_ERROR_BACKOFF_SECONDS = int(os.environ.get("PREPARE_ERROR_BACKOFF_SECONDS", "1800"))
STALE_CLAIM_SECONDS = int(os.environ.get("STALE_CLAIM_SECONDS", "7200"))
DAILY_WORKFLOW_ID = "3dprDailyPub0001"
PREPARER_WORKFLOW_ID = "3dprQueuePrep016"
GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
GITHUB_SCHEDULE_FILE = "config/schedule.json"
N8N_INTERNAL_URL = os.environ.get("N8N_INTERNAL_URL", "http://n8n:5678").rstrip("/")
SECRET_RE = re.compile(r"(EAA[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9._-]+|gsk_[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{30,}|pina_[A-Za-z0-9]{10,}|Bearer\s+[A-Za-z0-9._-]{16,}|OAuth\s+[A-Za-z0-9._-]{16,})")
STEP_SUMMARY_KEYS = (
    "product_id", "filename", "media_type", "platform", "status", "overall_status", "ok", "found",
    "guard_ok", "page_name", "post_id", "published_id", "id", "permalink", "dry_run", "skip_record",
    "ai_provider_used", "ai_model_used", "ai_fallback_reason", "error", "message", "reason",
)

IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXT = {"mp4", "mov"}
FILENAME_RE = re.compile(r"^(\d+)\.(jpg|jpeg|png|webp|mp4|mov)$", re.IGNORECASE)
PLATFORM_COLUMNS = ("instagram", "facebook", "pinterest", "youtube")
SUCCESS_STATUSES = {"published", "skipped"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(sql)
        conn.commit()


def load_settings_file() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def load_prompts() -> dict[str, str]:
    prompts: dict[str, str] = {}
    if PROMPTS_DIR.exists():
        for path in PROMPTS_DIR.glob("*.txt"):
            prompts[path.stem] = path.read_text(encoding="utf-8").strip()
    return prompts


def get_tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if name == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), "IST")
        return timezone.utc


def load_schedule() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if SCHEDULE_PATH.exists():
        try:
            data = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    schedule = {**SCHEDULE_DEFAULTS, **{k: v for k, v in data.items() if v not in (None, "")}}
    if not PUBLISH_TIME_RE.match(str(schedule["publish_time"])):
        schedule["publish_time"] = SCHEDULE_DEFAULTS["publish_time"]
    try:
        schedule["queue_size"] = max(1, min(int(schedule["queue_size"]), 10))
    except (TypeError, ValueError):
        schedule["queue_size"] = SCHEDULE_DEFAULTS["queue_size"]
    schedule["source"] = "file" if data else "defaults"
    return schedule


def schedule_cron(schedule: dict[str, Any]) -> str:
    hour, minute = (int(part) for part in schedule["publish_time"].split(":"))
    return f"{minute} {hour} * * *"


def schedule_now(schedule: dict[str, Any], now: datetime | None = None) -> datetime:
    tz = get_tz(schedule["timezone"])
    return now.astimezone(tz) if now else datetime.now(tz)


def slot_for(schedule: dict[str, Any], day: date) -> datetime:
    hour, minute = (int(part) for part in schedule["publish_time"].split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=get_tz(schedule["timezone"]))


def publish_due(schedule: dict[str, Any], last_trigger_date: str | None, now: datetime | None = None) -> bool:
    """Once per local day, at or after the slot (catches up the same day if the PC was off)."""
    local = schedule_now(schedule, now)
    return last_trigger_date != local.date().isoformat() and local >= slot_for(schedule, local.date())


def next_publish_run(schedule: dict[str, Any], last_trigger_date: str | None, now: datetime | None = None) -> dict[str, Any]:
    local = schedule_now(schedule, now)
    today_slot = slot_for(schedule, local.date())
    if last_trigger_date == local.date().isoformat():
        return {"at": slot_for(schedule, local.date() + timedelta(days=1)).isoformat(), "catch_up": False}
    if local < today_slot:
        return {"at": today_slot.isoformat(), "catch_up": False}
    return {"at": local.isoformat(timespec="seconds"), "catch_up": True}


def write_schedule(publish_time: str, updated_by: str) -> dict[str, Any]:
    if not PUBLISH_TIME_RE.match(publish_time or ""):
        raise ValueError("publish_time must be HH:MM in 24-hour format, for example 18:30")
    current = load_schedule()
    doc = {
        "publish_time": publish_time,
        "timezone": current["timezone"],
        "queue_size": current["queue_size"],
        "updated_at": now_iso(),
        "updated_by": updated_by,
    }
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, SCHEDULE_PATH)
    return doc


def runtime_config() -> dict[str, Any]:
    settings = load_settings_file()
    schedule = load_schedule()
    dry_run = env_bool("DRY_RUN", True)
    use_sample = env_bool("USE_SAMPLE_MEDIA", False)
    include_url = env_bool("INCLUDE_WEBSITE_URL", False)
    ai = settings.get("ai", {})
    config = {
        **settings,
        "dry_run": dry_run,
        "use_sample_media": use_sample,
        "daily_cron": schedule_cron(schedule),
        "publish_time": schedule["publish_time"],
        "queue_size": schedule["queue_size"],
        "timezone": schedule["timezone"],
        "google_drive_folder_id": os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "") or settings.get("google_drive_folder_id", ""),
        "facebook_page_id": os.environ.get("FACEBOOK_PAGE_ID", ""),
        "instagram_business_account_id": os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
        "meta_graph_version": os.environ.get("META_GRAPH_VERSION", "v22.0"),
        "pinterest_board_id": os.environ.get("PINTEREST_BOARD_ID", ""),
        "youtube_privacy_status": os.environ.get("YOUTUBE_PRIVACY_STATUS", settings.get("youtube_privacy_status", "private")),
        "youtube_format": settings.get("youtube_format", "shorts"),
        "youtube_oauth_redirect_uri": "http://localhost:5678/rest/oauth2-credential/callback",
        "website_url": os.environ.get("WEBSITE_URL", "") or settings.get("website_url", ""),
        "include_website_url": include_url or bool(settings.get("include_website_url")),
        "ai_provider": os.environ.get("AI_PROVIDER", ai.get("provider", "gemini")),
        "gemini_model": os.environ.get("GEMINI_MODEL", ai.get("gemini_model", "gemini-3.6-flash")),
        "gemini_host": os.environ.get("GEMINI_HOST", ai.get("gemini_host", "https://generativelanguage.googleapis.com")),
        "ai_fallback_provider": os.environ.get("AI_FALLBACK_PROVIDER", ai.get("fallback_provider", "groq")),
        "groq_model": os.environ.get("GROQ_MODEL", ai.get("groq_model", "qwen/qwen3.8-27b")),
        "drive_access_mode": os.environ.get("DRIVE_ACCESS_MODE", settings.get("drive_access_mode", "public")),
        "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", ai.get("ollama_base_url", "http://ollama:11434")),
        "ollama_model": os.environ.get("OLLAMA_MODEL", ai.get("ollama_model", "llava")),
        "prompts": load_prompts(),
        "tracking_api": "http://tracking-api:8081",
        "n8n_url": os.environ.get("WEBHOOK_URL", "http://localhost:5678/"),
    }
    return config


def parse_files(files: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    ignored: list[str] = []
    for item in files:
        name = str(item.get("name") or item.get("filename") or "").strip()
        match = FILENAME_RE.match(name)
        if not match:
            ignored.append(name)
            continue
        product_id = int(match.group(1))
        ext = match.group(2).lower()
        kind = "video" if ext in VIDEO_EXT else "image"
        group = grouped.setdefault(
            product_id,
            {"product_id": product_id, "files": [], "has_image": False, "has_video": False},
        )
        entry = {
            "filename": name,
            "media_kind": kind,
            "extension": ext,
            "drive_file_id": item.get("id") or item.get("drive_file_id"),
            "mime_type": item.get("mimeType") or item.get("mime_type"),
            "local_path": item.get("local_path") or f"/data/samples/{name}",
        }
        group["files"].append(entry)
        if kind == "image":
            group["has_image"] = True
        else:
            group["has_video"] = True
    for group in grouped.values():
        if group["has_image"] and group["has_video"]:
            group["media_type"] = "both"
        elif group["has_video"]:
            group["media_type"] = "video"
        else:
            group["media_type"] = "image"
        group["filename"] = next(
            (f["filename"] for f in group["files"] if f["media_kind"] == "video"),
            group["files"][0]["filename"],
        )
        group["image_file"] = next((f for f in group["files"] if f["media_kind"] == "image"), None)
        group["video_file"] = next((f for f in group["files"] if f["media_kind"] == "video"), None)
    return {"products": grouped, "ignored": [name for name in ignored if name]}


def required_platforms(media_type: str, settings: dict[str, Any] | None = None) -> list[str]:
    settings = settings or load_settings_file()
    mapping = settings.get("required_platforms", {})
    return list(mapping.get(media_type, ["instagram", "facebook"]))


def skipped_platforms(media_type: str) -> dict[str, str]:
    skips: dict[str, str] = {}
    if media_type == "image":
        skips["youtube"] = "YouTube Shorts require video media. Image-only products are skipped."
    if media_type == "video":
        skips["pinterest"] = "This workflow creates image Pins only. Video products are skipped on Pinterest."
    return skips


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "extra_files" in data and isinstance(data["extra_files"], str):
        try:
            data["extra_files"] = json.loads(data["extra_files"])
        except json.JSONDecodeError:
            pass
    return data


def append_jsonl(event: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / "actions.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_event(conn: sqlite3.Connection, level: str, event: str, message: str, product_id: int | None = None, platform: str | None = None, details: Any = None) -> None:
    payload = {
        "ts": now_iso(),
        "level": level,
        "event": event,
        "product_id": product_id,
        "platform": platform,
        "message": message,
        "details": details,
    }
    conn.execute(
        """
        INSERT INTO logs (ts, level, event, product_id, platform, message, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["ts"],
            level,
            event,
            product_id,
            platform,
            message,
            json_dumps(details) if details is not None else None,
        ),
    )
    append_jsonl(payload)


def compute_overall(record: dict[str, Any], media_type: str) -> str:
    required = required_platforms(media_type)
    statuses = [record.get(f"{name}_status", "pending") for name in required]
    if any(status == "processing" for status in statuses):
        return "processing"
    if all(status in SUCCESS_STATUSES for status in statuses):
        return "published"
    if any(status == "failed" for status in statuses) and any(status in SUCCESS_STATUSES for status in statuses):
        return "partial"
    if any(status == "failed" for status in statuses):
        return "failed"
    return "pending"


def platforms_to_publish(record: dict[str, Any], media_type: str) -> tuple[list[str], dict[str, str]]:
    required = required_platforms(media_type)
    skips = skipped_platforms(media_type)
    to_publish: list[str] = []
    blocked: dict[str, str] = dict(skips)
    for platform in required:
        status = record.get(f"{platform}_status", "pending")
        if status == "published":
            blocked[platform] = "already published — duplicate protection skipped this platform"
            continue
        if status == "skipped":
            blocked[platform] = "platform is not required for this media type"
            continue
        to_publish.append(platform)
    return to_publish, blocked


def list_sample_files() -> list[dict[str, Any]]:
    if not SAMPLES_DIR.exists():
        return []
    files = []
    for path in sorted(SAMPLES_DIR.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        match = FILENAME_RE.match(path.name)
        if not match:
            continue
        ext = match.group(2).lower()
        files.append(
            {
                "name": path.name,
                "filename": path.name,
                "local_path": f"/data/samples/{path.name}",
                "mime_type": {
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "webp": "image/webp",
                    "mp4": "video/mp4",
                    "mov": "video/quicktime",
                }[ext],
                "size": path.stat().st_size,
            }
        )
    return files


def guess_mime(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
    }.get(ext, "application/octet-stream")


def http_get_bytes(url: str, opener: Any | None = None, timeout: int = 90) -> tuple[int, bytes, dict[str, str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req = urllib_request.Request(url, headers=headers)
    try:
        if opener is not None:
            response_cm = opener.open(req, timeout=timeout)
        else:
            response_cm = urllib_request.urlopen(req, timeout=timeout)
        with response_cm as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib_error.HTTPError as exc:
        return int(exc.code), exc.read(), {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}


def extract_drive_api_keys(html: str) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"AIza[0-9A-Za-z_-]{20,}", html):
        key = match.group(0)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def parse_public_folder_html(html: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    patterns = [
        r'aria-label="([^"]+\.(?:mp4|mov|jpg|jpeg|png|webp))[^"]*"[^>]*ssk=\'[^:]*:[^:]*:([A-Za-z0-9_-]{20,})-',
        r"ssk='[^:]*:[^:]*:([A-Za-z0-9_-]{20,})-[^']*'[^>]*aria-label=\"([^\"]+\.(?:mp4|mov|jpg|jpeg|png|webp))",
        r'\["([A-Za-z0-9_-]{20,})"\s*,\s*\["([^"]+\.(?:mp4|mov|jpg|jpeg|png|webp))"',
        r'\\"([A-Za-z0-9_-]{20,})\\"\s*,\s*\[\\"([^\\"]+\.(?:mp4|mov|jpg|jpeg|png|webp))\\"',
    ]
    for pattern in patterns:
        for left, right in re.findall(pattern, html, flags=re.IGNORECASE):
            if "." in left and re.search(r"\.(mp4|mov|jpg|jpeg|png|webp)$", left, re.I):
                name, file_id = left, right
            else:
                file_id, name = left, right
            key = file_id + "|" + name
            if key in seen:
                continue
            seen.add(key)
            files.append(
                {
                    "name": name,
                    "id": file_id,
                    "drive_file_id": file_id,
                    "mimeType": guess_mime(name),
                    "thumbnailLink": None,
                    "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
                }
            )
    return files


def list_public_drive_folder(folder_id: str) -> dict[str, Any]:
    folder_id = (folder_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
        raise ValueError("Invalid Google Drive folder id")

    page_url = f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
    status, body, _headers = http_get_bytes(page_url)
    if status >= 400:
        raise RuntimeError(f"Public Drive folder page returned HTTP {status}")
    html = body.decode("utf-8", "replace")

    files: list[dict[str, Any]] = []
    method = "none"
    query = quote(f"'{folder_id}' in parents and trashed = false", safe="")
    for api_key in extract_drive_api_keys(html):
        api_url = (
            "https://www.googleapis.com/drive/v3/files"
            f"?q={query}"
            "&fields=files(id,name,mimeType,thumbnailLink,webViewLink)"
            "&pageSize=1000"
            "&supportsAllDrives=true"
            "&includeItemsFromAllDrives=true"
            f"&key={api_key}"
        )
        api_status, api_body, _ = http_get_bytes(api_url)
        if api_status != 200:
            continue
        payload = json.loads(api_body.decode("utf-8"))
        for item in payload.get("files") or []:
            name = str(item.get("name") or "").strip()
            file_id = str(item.get("id") or "").strip()
            if not name or not file_id:
                continue
            files.append(
                {
                    "name": name,
                    "id": file_id,
                    "drive_file_id": file_id,
                    "mimeType": item.get("mimeType") or guess_mime(name),
                    "thumbnailLink": item.get("thumbnailLink"),
                    "webViewLink": item.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view",
                }
            )
        if files:
            method = "public_api_key"
            break

    if not files:
        files = parse_public_folder_html(html)
        if files:
            method = "public_html_parse"

    if not files:
        raise RuntimeError(
            "Could not list the public Google Drive folder. Confirm the folder is shared as "
            "'Anyone with the link' and contains ProductID.ext files."
        )

    return {
        "ok": True,
        "folder_id": folder_id,
        "files": files,
        "count": len(files),
        "method": method,
        "access_mode": "public",
    }


def download_public_drive_file(file_id: str, filename: str, folder_id: str | None = None) -> dict[str, Any]:
    file_id = (file_id or "").strip()
    filename = Path(str(filename or "").strip()).name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise ValueError("Invalid Google Drive file id")
    if not filename or not FILENAME_RE.match(filename):
        raise ValueError("Invalid filename. Use ProductID.ext such as 1.jpg or 001.mp4.")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    dest = MEDIA_DIR / filename
    jar = http.cookiejar.CookieJar()
    opener = urllib_request.build_opener(urllib_request.HTTPCookieProcessor(jar))

    data = b""
    last_error = "unknown"
    folder = (folder_id or runtime_config().get("google_drive_folder_id") or "").strip()
    if folder:
        page_status, page_body, _ = http_get_bytes(f"https://drive.google.com/drive/folders/{folder}?usp=sharing")
        if page_status < 400:
            html = page_body.decode("utf-8", "replace")
            for api_key in extract_drive_api_keys(html):
                media_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={api_key}&supportsAllDrives=true"
                status, payload, headers = http_get_bytes(media_url, opener=opener, timeout=300)
                content_type = headers.get("content-type", "")
                if status == 200 and "json" not in content_type and len(payload) >= 64:
                    data = payload
                    break
                last_error = f"alt=media HTTP {status}"

    if len(data) < 64:
        candidates = [
            f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
            f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
            f"https://drive.google.com/uc?export=download&id={file_id}",
        ]
        for url in candidates:
            status, payload, headers = http_get_bytes(url, opener=opener, timeout=300)
            content_type = headers.get("content-type", "")
            if status >= 400:
                last_error = f"HTTP {status} from download endpoint"
                continue
            if "text/html" in content_type or payload[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                html = payload.decode("utf-8", "replace")
                token = None
                for pattern in (
                    r'confirm=([0-9A-Za-z_-]+)',
                    r'name="confirm"\s+value="([0-9A-Za-z_-]+)"',
                    r'"confirm"\s*,\s*"([0-9A-Za-z_-]+)"',
                ):
                    match = re.search(pattern, html)
                    if match:
                        token = match.group(1)
                        break
                uuid_match = re.search(r'name="uuid"\s+value="([^"]+)"', html)
                at_match = re.search(r'name="at"\s+value="([^"]+)"', html)
                if not (uuid_match or token):
                    last_error = "Google Drive download returned HTML without a confirm token"
                    continue
                params = [f"id={file_id}", "export=download", f"confirm={token or 't'}"]
                if uuid_match:
                    params.append(f"uuid={uuid_match.group(1)}")
                if at_match:
                    params.append(f"at={quote(at_match.group(1), safe='')}")
                retry_url = "https://drive.usercontent.google.com/download?" + "&".join(params)
                status, payload, headers = http_get_bytes(retry_url, opener=opener, timeout=300)
                content_type = headers.get("content-type", "")
                if status >= 400 or "text/html" in content_type:
                    last_error = "Google Drive returned an HTML interstitial that could not be bypassed"
                    continue
            data = payload
            break

    if len(data) < 64:
        raise RuntimeError(f"Public Drive download failed ({last_error}).")

    dest.write_bytes(data)
    return {
        "ok": True,
        "file_id": file_id,
        "filename": filename,
        "local_path": str(dest),
        "bytes": len(data),
        "mimeType": guess_mime(filename),
        "access_mode": "public",
    }


def prepare_vision(body: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(body.get("local_path") or body.get("path") or "")
    if not raw_path:
        raise ValueError("local_path is required")
    src = Path(raw_path)
    if not src.exists():
        src = MEDIA_DIR / Path(raw_path).name
    if not src.exists():
        raise FileNotFoundError(f"Media not found: {raw_path}")
    ext = src.suffix.lower().lstrip(".")
    kind = str(body.get("media_kind") or body.get("media_type") or "")
    if not kind:
        kind = "video" if ext in VIDEO_EXT else "image"
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    out = MEDIA_DIR / f"{src.stem}_vision.jpg"
    ffmpeg = shutil.which("ffmpeg")
    image_mimes = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    if ffmpeg:
        if kind == "video" or ext in VIDEO_EXT:
            cmd = [ffmpeg, "-y", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)]
            source = "video_frame"
        else:
            cmd = [ffmpeg, "-y", "-i", str(src), "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(out)]
            source = "resized_image"
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            data = out.read_bytes()
            return {
                "ok": True,
                "source": source,
                "mime_type": "image/jpeg",
                "base64": base64.b64encode(data).decode("ascii"),
                "path": str(out),
                "bytes": len(data),
            }
        if ext in image_mimes:
            data = src.read_bytes()
            return {
                "ok": True,
                "source": "original_after_ffmpeg_error",
                "mime_type": image_mimes[ext],
                "base64": base64.b64encode(data).decode("ascii"),
                "path": str(src),
                "bytes": len(data),
                "ffmpeg_error": (proc.stderr or "")[-400:],
            }
        raise RuntimeError((proc.stderr or "ffmpeg failed to extract a vision frame")[-400:])
    if ext in image_mimes:
        data = src.read_bytes()
        return {
            "ok": True,
            "source": "original_bytes",
            "mime_type": image_mimes[ext],
            "base64": base64.b64encode(data).decode("ascii"),
            "path": str(src),
            "bytes": len(data),
        }
    raise RuntimeError("ffmpeg is required to inspect video files for AI vision.")


def select_next(files: list[dict[str, Any]], exclude_ids: set[int] | None = None) -> dict[str, Any]:
    exclude_ids = exclude_ids or set()
    parsed = parse_files(files)
    products = parsed["products"]
    if not products:
        return {
            "found": False,
            "reason": "No supported media files were found. Use ProductID.ext such as 1.jpg or 4.mp4.",
            "ignored": parsed["ignored"],
        }
    with connect() as conn:
        rows = {row["product_id"]: row_to_dict(row) for row in conn.execute("SELECT * FROM products")}
        for product_id in sorted(products):
            if product_id in exclude_ids:
                continue
            record = rows.get(product_id)
            if record and record["overall_status"] == "published":
                continue
            # During DRY_RUN, skip products that already have a completed preview so
            # sequential selection advances one Product ID per daily run.
            if runtime_config()["dry_run"] and record and record["overall_status"] == "previewed":
                continue
            group = products[product_id]
            media_type = group["media_type"]
            skips = skipped_platforms(media_type)
            if record is None:
                extra = json_dumps(group["files"])
                ts = now_iso()
                instagram = "skipped" if "instagram" in skips else "pending"
                facebook = "skipped" if "facebook" in skips else "pending"
                pinterest = "skipped" if "pinterest" in skips else "pending"
                youtube = "skipped" if "youtube" in skips else "pending"
                conn.execute(
                    """
                    INSERT INTO products (
                        product_id, filename, extra_files, media_type,
                        instagram_status, facebook_status, pinterest_status, youtube_status,
                        overall_status, attempt_count, dry_run, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (
                        product_id,
                        group["filename"],
                        extra,
                        media_type,
                        instagram,
                        facebook,
                        pinterest,
                        youtube,
                        1 if runtime_config()["dry_run"] else 0,
                        ts,
                        ts,
                    ),
                )
                record = row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())
            else:
                record = dict(record)
            to_publish, blocked = platforms_to_publish(record, media_type)
            log_event(
                conn,
                "info",
                "product_selected",
                f"Selected Product ID {product_id}",
                product_id=product_id,
                details={"platforms_to_publish": to_publish, "blocked": blocked, "dry_run": runtime_config()["dry_run"]},
            )
            conn.commit()
            return {
                "found": True,
                "product_id": product_id,
                "media_type": media_type,
                "filename": group["filename"],
                "files": group["files"],
                "image_file": group["image_file"],
                "video_file": group["video_file"],
                "required_platforms": required_platforms(media_type),
                "platforms_to_publish": to_publish,
                "blocked_platforms": blocked,
                "record": record,
                "ignored": parsed["ignored"],
                "dry_run": runtime_config()["dry_run"],
            }
        return {
            "found": False,
            "reason": "Every supported Product ID in the folder is already fully published.",
            "ignored": parsed["ignored"],
            "known_product_ids": sorted(products),
        }


def mark_processing(product_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown product_id {product_id}")
        record = row_to_dict(row)
        assert record is not None
        to_publish, _blocked = platforms_to_publish(record, record["media_type"])
        assignments = []
        values: list[Any] = []
        for platform in to_publish:
            assignments.append(f"{platform}_status = ?")
            values.append("processing")
        values.extend([now_iso(), product_id])
        if assignments:
            conn.execute(
                f"UPDATE products SET {', '.join(assignments)}, overall_status = 'processing', attempt_count = attempt_count + 1, updated_at = ? WHERE product_id = ?",
                values,
            )
        else:
            conn.execute(
                "UPDATE products SET attempt_count = attempt_count + 1, updated_at = ? WHERE product_id = ?",
                (now_iso(), product_id),
            )
        log_event(conn, "info", "processing", "Marked product processing", product_id=product_id, details={"platforms": to_publish})
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())  # type: ignore[return-value]


def can_publish(product_id: int, platform: str) -> dict[str, Any]:
    platform = platform.lower()
    if platform not in PLATFORM_COLUMNS:
        return {"allowed": False, "reason": f"Unknown platform {platform}"}
    with connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if row is None:
            return {"allowed": False, "reason": f"Unknown product_id {product_id}"}
        record = row_to_dict(row)
        assert record is not None
        status = record[f"{platform}_status"]
        post_id = record[f"{platform}_post_id"]
        if runtime_config()["dry_run"]:
            return {
                "allowed": False,
                "reason": "DRY_RUN=true — publishing is blocked. Generated content will be saved as a preview only.",
                "status": status,
                "post_id": post_id,
                "dry_run": True,
            }
        if status == "published" and post_id:
            return {
                "allowed": False,
                "reason": f"{platform} already published as {post_id}. Duplicate protection will not post again.",
                "status": status,
                "post_id": post_id,
            }
        if status == "published":
            return {
                "allowed": False,
                "reason": f"{platform} already marked published. Duplicate protection will not post again.",
                "status": status,
                "post_id": post_id,
            }
        if status == "skipped":
            return {
                "allowed": False,
                "reason": f"{platform} is skipped for media type {record['media_type']}.",
                "status": status,
            }
        return {"allowed": True, "status": status, "post_id": post_id, "product": record}


def save_platform_result(product_id: int, platform: str, status: str, post_id: str | None, error_message: str | None) -> dict[str, Any]:
    platform = platform.lower()
    if platform not in PLATFORM_COLUMNS:
        raise ValueError(f"Unknown platform {platform}")
    if status not in {"pending", "processing", "published", "failed", "skipped"}:
        raise ValueError(f"Invalid status {status}")
    with connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown product_id {product_id}")
        current = row_to_dict(row)
        assert current is not None
        if current[f"{platform}_status"] == "published" and status != "published":
            log_event(
                conn,
                "warning",
                "duplicate_blocked",
                f"Refused to overwrite successful {platform} result",
                product_id=product_id,
                platform=platform,
                details={"incoming_status": status, "existing_post_id": current[f"{platform}_post_id"]},
            )
            conn.commit()
            return current
        ts = now_iso()
        conn.execute(
            f"""
            UPDATE products
            SET {platform}_status = ?, {platform}_post_id = COALESCE(?, {platform}_post_id),
                error_message = ?, updated_at = ?
            WHERE product_id = ?
            """,
            (status, post_id, error_message, ts, product_id),
        )
        updated = row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())
        assert updated is not None
        overall = compute_overall(updated, updated["media_type"])
        published_at = ts if overall == "published" else updated.get("published_at")
        conn.execute(
            "UPDATE products SET overall_status = ?, published_at = ?, updated_at = ? WHERE product_id = ?",
            (overall, published_at, ts, product_id),
        )
        log_event(
            conn,
            "info" if status in SUCCESS_STATUSES else "error",
            "platform_result",
            f"{platform} -> {status}",
            product_id=product_id,
            platform=platform,
            details={"post_id": post_id, "error_message": error_message, "overall_status": overall},
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())  # type: ignore[return-value]


def save_preview(body: dict[str, Any]) -> dict[str, Any]:
    """Persist AI preview JSON with publishing metadata for later platform APIs."""
    if "product_id" not in body:
        raise ValueError("preview requires product_id")
    product_id = int(body["product_id"])
    content = body.get("content")
    if not isinstance(content, dict):
        raise ValueError("preview requires a content object with platform blocks")
    for platform in ("instagram", "facebook", "pinterest", "youtube"):
        if platform not in content or not isinstance(content.get(platform), dict):
            raise ValueError(f"preview content is missing platform block: {platform}")

    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_iso()
    dry_run = runtime_config()["dry_run"] if body.get("dry_run") is None else bool(body.get("dry_run"))
    drive_file_id = body.get("drive_file_id") or body.get("file_id")
    payload = {
        "product_id": product_id,
        "created_at": ts,
        "dry_run": dry_run,
        "filename": body.get("filename"),
        "media_type": body.get("media_type"),
        "drive_file_id": drive_file_id,
        "google_drive_folder_id": body.get("google_drive_folder_id")
        or runtime_config().get("google_drive_folder_id"),
        "local_path": body.get("local_path"),
        "vision_notes": body.get("vision_notes"),
        "vision_source": body.get("vision_source"),
        "ai_provider_used": body.get("ai_provider_used"),
        "ai_model_used": body.get("ai_model_used"),
        "gemini_model_used": body.get("gemini_model_used"),
        "ai_fallback_reason": body.get("ai_fallback_reason"),
        "content": content,
    }
    path = PREVIEWS_DIR / f"{product_id}.json"
    path.write_text(json_dumps(payload), encoding="utf-8")
    with connect() as conn:
        conn.execute(
            "INSERT INTO content_previews (product_id, created_at, dry_run, content_json) VALUES (?, ?, ?, ?)",
            (product_id, ts, 1 if dry_run else 0, json_dumps(payload)),
        )
        log_event(
            conn,
            "info",
            "ai_preview_saved",
            f"Saved generated content for Product {product_id}",
            product_id=product_id,
            details={
                "filename": payload.get("filename"),
                "media_type": payload.get("media_type"),
                "drive_file_id": payload.get("drive_file_id"),
            },
        )
        if body.get("queue"):
            mark_prepared(conn, product_id, reused=False)
        conn.commit()
    return payload


def finalize_product(product_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown product_id {product_id}")
        record = row_to_dict(row)
        assert record is not None
        ts = now_iso()
        # In DRY_RUN, a successful preview+finalize advances sequential selection
        # without treating the product as actually published to social platforms.
        if runtime_config()["dry_run"]:
            required = required_platforms(str(record["media_type"]))
            for platform in required:
                status = record.get(f"{platform}_status", "pending")
                if status in {"pending", "processing"}:
                    conn.execute(
                        f"UPDATE products SET {platform}_status = ?, updated_at = ? WHERE product_id = ?",
                        ("previewed", ts, product_id),
                    )
            overall = "previewed"
            published_at = record.get("published_at")
        else:
            refreshed = row_to_dict(
                conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
            )
            assert refreshed is not None
            overall = compute_overall(refreshed, refreshed["media_type"])
            published_at = ts if overall == "published" else refreshed.get("published_at")
        conn.execute(
            "UPDATE products SET overall_status = ?, published_at = ?, updated_at = ? WHERE product_id = ?",
            (overall, published_at, ts, product_id),
        )
        log_event(
            conn,
            "info",
            "final_status",
            f"Product {product_id} final status is {overall}",
            product_id=product_id,
            details={"dry_run": runtime_config()["dry_run"], "overall_status": overall},
        )
        settle_queue(conn, product_id, overall)
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())  # type: ignore[return-value]


def status_payload() -> dict[str, Any]:
    with connect() as conn:
        products = [row_to_dict(row) for row in conn.execute("SELECT * FROM products ORDER BY product_id")]
        logs = [row_to_dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 50")]
    return {
        "config": {
            "dry_run": runtime_config()["dry_run"],
            "use_sample_media": runtime_config()["use_sample_media"],
            "ai_provider": runtime_config()["ai_provider"],
            "timezone": runtime_config()["timezone"],
        },
        "products": products,
        "recent_logs": logs,
    }


def retry_failed() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE overall_status IN ('failed', 'partial') ORDER BY product_id LIMIT 1"
        ).fetchall()
        if not rows:
            return {"found": False, "reason": "No failed or partial products to retry."}
        record = row_to_dict(rows[0])
        assert record is not None
        to_publish, blocked = platforms_to_publish(record, record["media_type"])
        log_event(conn, "info", "retry", f"Retry requested for Product {record['product_id']}", product_id=record["product_id"], details={"platforms": to_publish})
        conn.commit()
        return {"found": True, "product_id": record["product_id"], "record": record, "platforms_to_publish": to_publish, "blocked_platforms": blocked}


def pinterest_s3_upload(body: dict[str, Any]) -> dict[str, Any]:
    """POST a local media file to the presigned S3 form returned by Pinterest POST /v5/media."""
    upload_url = str(body.get("upload_url") or "")
    params = body.get("upload_parameters") or {}
    if not upload_url.startswith("https://") or not isinstance(params, dict):
        return {"ok": False, "error": "upload_url and upload_parameters are required"}
    target = (MEDIA_DIR / Path(str(body.get("name") or "")).name).resolve()
    if target.parent != MEDIA_DIR.resolve() or not target.is_file():
        return {"ok": False, "error": "Media file not found"}
    boundary = "----zyra" + os.urandom(12).hex()
    parts: list[bytes] = []
    for key, value in params.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{target.name}"\r\n'
        f"Content-Type: video/mp4\r\n\r\n".encode()
    )
    payload = b"".join(parts) + target.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib_request.Request(upload_url, data=payload, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib_request.urlopen(req, timeout=300) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "bytes": target.stat().st_size}
    except urllib_error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode("utf-8", "replace")[:500]}


def reset_preview(product_id: int) -> dict[str, Any]:
    """DRY_RUN only: re-queue a previewed product so the next run regenerates its content."""
    if not runtime_config()["dry_run"]:
        return {"ok": False, "reason": "reset-preview is only allowed while DRY_RUN=true."}
    with connect() as conn:
        record = row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())
        if record is None:
            return {"ok": False, "reason": f"Product {product_id} not found."}
        if any(record.get(f"{p}_status") == "published" or record.get(f"{p}_post_id") for p in PLATFORM_COLUMNS):
            return {"ok": False, "reason": f"Product {product_id} has published posts; refusing to reset."}
        updates = {f"{p}_status": "pending" for p in PLATFORM_COLUMNS if record.get(f"{p}_status") == "previewed"}
        updates["overall_status"] = "pending"
        updates["updated_at"] = now_iso()
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE products SET {assignments} WHERE product_id = ?", (*updates.values(), product_id))
        log_event(conn, "info", "reset_preview", f"Preview reset for Product {product_id}", product_id=product_id)
        conn.commit()
    return {"ok": True, "product_id": product_id, "reset": sorted(updates)}


def get_state(key: str, default: Any = None) -> Any:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(key: str, value: Any) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now_iso()),
        )
        conn.commit()


def local_today() -> str:
    return schedule_now(load_schedule()).date().isoformat()


def handled_date() -> str | None:
    """Local date whose slot is already taken care of (triggered, or deliberately skipped)."""
    today = local_today()
    last = get_state("last_publish_trigger_date")
    return today if today in {last, get_state("publish_skip_date")} else last


def skip_today_if_slot_passed(reason: str) -> bool:
    schedule = load_schedule()
    if not publish_due(schedule, handled_date()):
        return False
    set_state("publish_skip_date", local_today())
    with connect() as conn:
        log_event(conn, "info", "schedule_skip_today", reason)
        conn.commit()
    return True


def mark_prepared(conn: sqlite3.Connection, product_id: int, reused: bool) -> None:
    conn.execute(
        """
        INSERT INTO content_queue (product_id, status, prepared_at, reused_preview)
        VALUES (?, 'prepared', ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
          status = CASE WHEN content_queue.status = 'publishing' THEN 'publishing' ELSE 'prepared' END,
          prepared_at = excluded.prepared_at,
          completed_at = NULL,
          last_error = NULL,
          reused_preview = excluded.reused_preview
        """,
        (product_id, now_iso(), 1 if reused else 0),
    )
    log_event(
        conn,
        "info",
        "queue_prepared",
        f"Product {product_id} content is ready in the queue" + (" (reused saved content)" if reused else ""),
        product_id=product_id,
        details={"reused_preview": reused},
    )


def settle_queue(conn: sqlite3.Connection, product_id: int, overall: str) -> None:
    row = conn.execute("SELECT status FROM content_queue WHERE product_id = ?", (product_id,)).fetchone()
    if row is None:
        return
    if overall in {"published", "previewed"}:
        conn.execute(
            "UPDATE content_queue SET status = 'done', completed_at = ?, last_error = NULL WHERE product_id = ?",
            (now_iso(), product_id),
        )
        log_event(conn, "info", "queue_advanced", f"Product {product_id} left the queue ({overall})", product_id=product_id)
    elif row["status"] == "publishing":
        conn.execute(
            "UPDATE content_queue SET status = 'prepared', claimed_at = NULL, last_error = ? WHERE product_id = ?",
            (f"Publish attempt finished as {overall}; will retry at the next slot", product_id),
        )
        log_event(conn, "warning", "queue_retry", f"Product {product_id} stays at the head of the queue ({overall})", product_id=product_id)


def reset_stale_claims(conn: sqlite3.Connection) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_CLAIM_SECONDS)
    for row in conn.execute("SELECT product_id, claimed_at FROM content_queue WHERE status = 'publishing'").fetchall():
        try:
            claimed = datetime.fromisoformat(row["claimed_at"])
        except (TypeError, ValueError):
            claimed = None
        if claimed is None or claimed < cutoff:
            conn.execute(
                "UPDATE content_queue SET status = 'prepared', claimed_at = NULL, last_error = ? WHERE product_id = ?",
                ("Publish claim expired without a final status", row["product_id"]),
            )
            log_event(conn, "warning", "queue_claim_expired", f"Product {row['product_id']} claim expired; returned to queue", product_id=row["product_id"])


def load_preview_for(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    path = PREVIEWS_DIR / f"{product_id}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("content"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    row = conn.execute(
        "SELECT content_json FROM content_previews WHERE product_id = ? ORDER BY id DESC LIMIT 1", (product_id,)
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row["content_json"])
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(data), encoding="utf-8")
    return data


def active_queue_ids(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT product_id FROM content_queue WHERE status IN ('prepared', 'publishing') ORDER BY product_id")]


def select_to_prepare(files: list[dict[str, Any]]) -> dict[str, Any]:
    schedule = load_schedule()
    with connect() as conn:
        reset_stale_claims(conn)
        conn.commit()
        active = active_queue_ids(conn)
    if len(active) >= schedule["queue_size"]:
        return {"found": False, "reason_code": "queue_full", "reason": f"Queue already holds {len(active)} prepared products.", "queue": active}
    selected = select_next(files, set(active))
    if not selected.get("found"):
        set_state("prepare_idle_until", (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat())
        return {**selected, "reason_code": "no_more_products", "queue": active}
    product_id = selected["product_id"]
    names = {f["filename"] for f in selected.get("files", [])}
    with connect() as conn:
        preview = load_preview_for(conn, product_id)
        reused = bool(preview and preview.get("filename") in names)
        if reused:
            mark_prepared(conn, product_id, reused=True)
            conn.commit()
    return {**selected, "reused": reused, "queue": active}


def claim_next() -> dict[str, Any]:
    """Hand the queue head to the Daily Publisher: one product per local day in live mode."""
    dry_run = runtime_config()["dry_run"]
    today = local_today()
    with connect() as conn:
        reset_stale_claims(conn)
        if not dry_run:
            posted = conn.execute(
                "SELECT product_id FROM content_queue WHERE run_date = ? AND status IN ('publishing', 'done') LIMIT 1", (today,)
            ).fetchone()
            if posted:
                conn.commit()
                return {"found": False, "reason_code": "already_published_today", "reason": f"Product {posted[0]} was already published today ({today}). One product per day.", "product_id": posted[0]}
        busy = conn.execute("SELECT product_id FROM content_queue WHERE status = 'publishing' LIMIT 1").fetchone()
        if busy:
            conn.commit()
            return {"found": False, "reason_code": "publish_in_progress", "reason": f"Product {busy[0]} is being published right now.", "product_id": busy[0]}
        claimed: tuple[int, dict[str, Any]] | None = None
        rows = conn.execute(
            "SELECT q.product_id, p.overall_status FROM content_queue q JOIN products p ON p.product_id = q.product_id "
            "WHERE q.status = 'prepared' ORDER BY q.product_id"
        ).fetchall()
        for row in rows:
            product_id, overall = row["product_id"], row["overall_status"]
            if overall == "published" or (dry_run and overall == "previewed"):
                conn.execute("UPDATE content_queue SET status = 'done', completed_at = ? WHERE product_id = ?", (now_iso(), product_id))
                log_event(conn, "warning", "duplicate_blocked", f"Product {product_id} is already {overall}; removed from queue", product_id=product_id)
                continue
            preview = load_preview_for(conn, product_id)
            if preview is None:
                conn.execute("DELETE FROM content_queue WHERE product_id = ?", (product_id,))
                log_event(conn, "warning", "queue_content_missing", f"Product {product_id} had no saved content; will be prepared again", product_id=product_id)
                continue
            conn.execute(
                "UPDATE content_queue SET status = 'publishing', claimed_at = ?, run_date = ?, claim_count = claim_count + 1, last_error = NULL WHERE product_id = ?",
                (now_iso(), today, product_id),
            )
            log_event(conn, "info", "queue_claimed", f"Product {product_id} taken from the queue for today's post", product_id=product_id, details={"dry_run": dry_run, "run_date": today})
            claimed = (product_id, preview)
            break
        conn.commit()
    if claimed is None:
        return {"found": False, "reason_code": "queue_empty", "reason": "No prepared content in the queue."}
    product_id, preview = claimed
    media = ensure_media(preview)
    if not media["ok"] and not dry_run:
        with connect() as conn:
            conn.execute(
                "UPDATE content_queue SET status = 'prepared', claimed_at = NULL, run_date = NULL, last_error = ? WHERE product_id = ?",
                (media["error"], product_id),
            )
            log_event(conn, "error", "queue_media_missing", f"Product {product_id} media unavailable: {media['error']}", product_id=product_id)
            conn.commit()
        return {"found": False, "reason_code": "media_missing", "reason": media["error"], "product_id": product_id}
    with connect() as conn:
        record = row_to_dict(conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone())
    return {**preview, "found": True, "product_id": product_id, "record": record, "media_ready": media["ok"], "dry_run": dry_run}


def ensure_media(preview: dict[str, Any]) -> dict[str, Any]:
    local_path = str(preview.get("local_path") or "")
    target = MEDIA_DIR / Path(local_path).name if local_path else None
    if target and target.is_file():
        return {"ok": True, "path": str(target)}
    if not preview.get("drive_file_id") or not preview.get("filename"):
        return {"ok": False, "error": "No local media file and no Google Drive file id to re-download it."}
    try:
        result = download_public_drive_file(
            str(preview["drive_file_id"]), str(preview["filename"]), str(preview.get("google_drive_folder_id") or runtime_config().get("google_drive_folder_id") or "")
        )
    except Exception as exc:  # network failures must not crash the claim
        return {"ok": False, "error": f"Drive re-download failed: {exc}"}
    return {"ok": bool(result.get("ok")), "path": result.get("local_path"), "error": None if result.get("ok") else f"Drive re-download failed: {str(result)[:300]}"}


def queue_snapshot() -> dict[str, Any]:
    schedule = load_schedule()
    today = local_today()
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT q.*, p.filename, p.media_type, p.overall_status FROM content_queue q "
                "LEFT JOIN products p ON p.product_id = q.product_id ORDER BY q.product_id"
            )
        ]
    active = [r for r in rows if r["status"] in {"prepared", "publishing"}]
    for row in active:
        row["has_preview"] = (PREVIEWS_DIR / f"{row['product_id']}.json").exists()
    todays = [r for r in rows if r.get("run_date") == today]
    return {
        "queue_size": schedule["queue_size"],
        "active": active,
        "head": next((r for r in active if r["status"] == "prepared"), None),
        "publishing": next((r for r in active if r["status"] == "publishing"), None),
        "today": todays[-1] if todays else None,
        "recent_done": sorted((r for r in rows if r["status"] == "done"), key=lambda r: r.get("completed_at") or "", reverse=True)[:5],
    }


def redact(value: Any) -> str:
    return SECRET_RE.sub("[redacted]", str(value))


class N8nSession:
    """Read-only n8n REST session; the owner password stays server-side."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib_request.build_opener(urllib_request.HTTPCookieProcessor(self.jar))
        self.logged_in = False

    def _raw(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, bytes]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        csrf = next((c.value for c in self.jar if "csrf" in c.name.lower()), None)
        if csrf:
            headers["X-N8N-CSRF-TOKEN"] = csrf
        req = urllib_request.Request(N8N_INTERNAL_URL + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=20) as resp:
                return resp.status, resp.read()
        except urllib_error.HTTPError as exc:
            return exc.code, exc.read()

    def _login(self) -> None:
        email = os.environ.get("N8N_OWNER_EMAIL", "admin@localhost.local")
        password = os.environ.get("N8N_OWNER_PASSWORD", "")
        if not password:
            raise RuntimeError("N8N_OWNER_PASSWORD is not set for tracking-api")
        for payload in ({"emailOrLdapLoginId": email, "password": password}, {"email": email, "password": password}):
            status, _ = self._raw("POST", "/rest/login", payload)
            if status in {200, 201}:
                self.logged_in = True
                return
        raise RuntimeError("n8n login failed for the dashboard")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        with self.lock:
            if not self.logged_in:
                self._login()
            status, body = self._raw(method, path, payload)
            if status == 401:
                self._reset()
                self._login()
                status, body = self._raw(method, path, payload)
        if status not in {200, 201}:
            raise RuntimeError(f"n8n {method} {path.split('?')[0]} returned {status}")
        parsed = json.loads(body.decode("utf-8"))
        return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def run_workflow(self, workflow_id: str) -> str | None:
        data = self.request("POST", f"/rest/workflows/{workflow_id}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
        if not isinstance(data, dict):
            return None
        execution_id = data.get("executionId") or data.get("id")
        return str(execution_id) if execution_id else None

    def running(self, workflow_id: str) -> bool:
        # n8n 2.x only accepts "status" as a list in the executions filter.
        query = {"workflowId": workflow_id, "status": ["running", "new", "waiting"]}
        data = self.get("/rest/executions?limit=1&filter=" + quote(json.dumps(query)))
        return bool(data.get("results"))

    def last_execution(self, workflow_id: str) -> dict[str, Any] | None:
        data = self.get(f"/rest/executions?limit=1&filter=" + quote(json.dumps({"workflowId": workflow_id})))
        results = data.get("results") or []
        return execution_row(results[0]) if results else None


N8N = N8nSession()


def parse_flatted(raw: Any) -> Any:
    arr = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(arr, list) or not arr:
        return {}
    memo: dict[int, Any] = {}

    def resolve(index: int) -> Any:
        if index in memo:
            return memo[index]
        value = arr[index]
        if isinstance(value, list):
            out_list: list[Any] = []
            memo[index] = out_list
            out_list.extend(walk(v) for v in value)
            return out_list
        if isinstance(value, dict):
            out_dict: dict[str, Any] = {}
            memo[index] = out_dict
            out_dict.update({k: walk(v) for k, v in value.items()})
            return out_dict
        memo[index] = value
        return value

    def walk(value: Any) -> Any:
        return resolve(int(value)) if isinstance(value, str) and value.isdigit() else value

    return resolve(0)


def execution_row(item: dict[str, Any]) -> dict[str, Any]:
    started, stopped = item.get("startedAt"), item.get("stoppedAt")
    duration_ms = None
    if started and stopped:
        duration_ms = int(
            (datetime.fromisoformat(stopped.replace("Z", "+00:00")) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds() * 1000
        )
    return {
        "id": item.get("id"),
        "workflow_id": item.get("workflowId"),
        "workflow_name": item.get("workflowName"),
        "mode": item.get("mode"),
        "status": item.get("status"),
        "started_at": started,
        "stopped_at": stopped,
        "duration_ms": duration_ms,
        "retry_of": item.get("retryOf"),
    }


def dashboard_executions(limit: int, workflow_id: str = "", status: str = "") -> dict[str, Any]:
    filters: dict[str, Any] = {"workflowId": workflow_id} if workflow_id else {}
    if status:
        filters["status"] = [status]
    path = f"/rest/executions?limit={max(1, min(limit, 200))}"
    if filters:
        path += "&filter=" + quote(json.dumps(filters))
    data = N8N.get(path)
    return {"count": data.get("count"), "executions": [execution_row(item) for item in data.get("results", [])]}


def step_summary(run: dict[str, Any]) -> dict[str, str]:
    main = ((run.get("data") or {}).get("main") or [[]])
    first = next((branch[0] for branch in main if branch), None)
    payload = (first or {}).get("json") if isinstance(first, dict) else None
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, str] = {}
    for key in STEP_SUMMARY_KEYS:
        value = payload.get(key)
        if value is None or value == "" or isinstance(value, (dict, list)):
            continue
        summary[key] = redact(value)[:200]
    return summary


def dashboard_execution_detail(execution_id: int) -> dict[str, Any]:
    data = N8N.get(f"/rest/executions/{execution_id}?includeData=true")
    root = parse_flatted(data.get("data")) if data.get("data") else {}
    result = (root or {}).get("resultData") or {}
    steps: list[dict[str, Any]] = []
    for node, runs in (result.get("runData") or {}).items():
        for index, run in enumerate(runs or []):
            if not isinstance(run, dict):
                continue
            error = run.get("error")
            items = sum(len(branch or []) for branch in ((run.get("data") or {}).get("main") or []))
            steps.append(
                {
                    "node": node,
                    "run": index,
                    "start_ms": run.get("startTime"),
                    "duration_ms": run.get("executionTime"),
                    "status": run.get("executionStatus") or ("error" if error else "success"),
                    "items": items,
                    "error": redact((error or {}).get("message") if isinstance(error, dict) else error)[:500] if error else None,
                    "summary": step_summary(run),
                }
            )
    steps.sort(key=lambda s: s["start_ms"] or 0)
    top_error = result.get("error")
    return {
        **execution_row(data),
        "last_node": result.get("lastNodeExecuted"),
        "error": redact(top_error.get("message") if isinstance(top_error, dict) else top_error)[:500] if top_error else None,
        "steps": steps,
    }


def github_sync_schedule() -> dict[str, Any]:
    """Mirror config/schedule.json to the GitHub repo so the Actions schedule gate follows it."""
    token = os.environ.get("GITHUB_SYNC_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
    result: dict[str, Any] = {"at": now_iso(), "configured": bool(token and repo), "repo": repo or None, "branch": branch}
    if not result["configured"]:
        result.update(ok=False, message="GitHub sync not configured (set GITHUB_SYNC_TOKEN and GITHUB_REPOSITORY in .env).")
        set_state("github_sync", result)
        return result
    local_text = SCHEDULE_PATH.read_text(encoding="utf-8") if SCHEDULE_PATH.exists() else json.dumps(SCHEDULE_DEFAULTS, indent=2) + "\n"
    local = json.loads(local_text)
    url = f"{GITHUB_API_URL}/repos/{repo}/contents/{GITHUB_SCHEDULE_FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "zyra-tracking-api"}

    def call(method: str, target: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        req = urllib_request.Request(target, data=None if payload is None else json.dumps(payload).encode("utf-8"), method=method, headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib_request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"message": body[:300]}

    try:
        status, remote = call("GET", f"{url}?ref={quote(branch)}")
        sha = remote.get("sha") if status == 200 else None
        if status == 200:
            remote_doc = json.loads(base64.b64decode(remote.get("content", "")).decode("utf-8") or "{}")
            if all(remote_doc.get(k) == local.get(k) for k in ("publish_time", "timezone", "queue_size")):
                result.update(ok=True, in_sync=True, message=f"GitHub already uses {local.get('publish_time')} {local.get('timezone')}.")
                set_state("github_sync", result)
                return result
        elif status != 404:
            raise RuntimeError(f"GitHub GET returned {status}: {remote.get('message')}")
        payload = {
            "message": f"chore(schedule): daily publish time {local.get('publish_time')} {local.get('timezone')}",
            "content": base64.b64encode(local_text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        status, written = call("PUT", url, payload)
        if status not in {200, 201}:
            raise RuntimeError(f"GitHub PUT returned {status}: {written.get('message')}")
        result.update(ok=True, in_sync=True, commit=(written.get("commit") or {}).get("sha"), message=f"Pushed {local.get('publish_time')} to GitHub.")
    except Exception as exc:
        result.update(ok=False, in_sync=False, message=redact(exc)[:300])
    set_state("github_sync", result)
    return result


def save_schedule(publish_time: str, updated_by: str = "dashboard") -> dict[str, Any]:
    before = load_schedule()
    doc = write_schedule(publish_time, updated_by)
    with connect() as conn:
        log_event(conn, "info", "schedule_changed", f"Daily publish time set to {publish_time} {doc['timezone']} (was {before['publish_time']})", details={"from": before["publish_time"], "to": publish_time, "by": updated_by})
        conn.commit()
    if get_state("publish_skip_date") == local_today():
        set_state("publish_skip_date", None)
    skip_today_if_slot_passed(f"{publish_time} has already passed today; the next post is tomorrow (no surprise post right after saving).")
    sync = github_sync_schedule()
    return {**schedule_status(), "github_sync": sync}


def schedule_status() -> dict[str, Any]:
    schedule = load_schedule()
    last_date = handled_date()
    local = schedule_now(schedule)
    hour, minute = (int(part) for part in schedule["publish_time"].split(":"))
    utc_slot = slot_for(schedule, local.date()).astimezone(timezone.utc)
    return {
        "publish_time": schedule["publish_time"],
        "timezone": schedule["timezone"],
        "queue_size": schedule["queue_size"],
        "source": schedule["source"],
        "updated_at": schedule.get("updated_at"),
        "updated_by": schedule.get("updated_by"),
        "cron_local": schedule_cron(schedule),
        "cron_utc_equivalent": f"{utc_slot.minute} {utc_slot.hour} * * *",
        "now_local": local.isoformat(timespec="seconds"),
        "next_run": next_publish_run(schedule, last_date, local),
        "last_trigger_date": get_state("last_publish_trigger_date"),
        "skipped_today": get_state("publish_skip_date") == local.date().isoformat() and get_state("last_publish_trigger_date") != local.date().isoformat(),
        "last_trigger": get_state("last_publish_trigger"),
        "scheduler": {"enabled": SCHEDULER_ENABLED, **(get_state("scheduler_heartbeat") or {})},
        "github_sync": get_state("github_sync"),
        "display_12h": f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}",
    }


class Scheduler:
    """Fires the Daily Publisher at the dashboard-selected time and keeps the content queue full."""

    def __init__(self) -> None:
        self.publish_retry_after = 0.0
        self.last_prepare_trigger = 0.0
        self.last_sync_attempt = 0.0

    def run_forever(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:
                print(f"[scheduler] tick failed: {redact(exc)}", flush=True)
                set_state("scheduler_heartbeat", {"at": now_iso(), "ok": False, "error": redact(exc)[:300]})
            time.sleep(SCHEDULER_TICK_SECONDS)

    def tick(self) -> None:
        schedule = load_schedule()
        with connect() as conn:
            reset_stale_claims(conn)
            conn.commit()
        if publish_due(schedule, handled_date()) and time.time() >= self.publish_retry_after:
            self.fire_publish(schedule)
        self.maybe_prepare(schedule)
        self.maybe_sync()
        set_state("scheduler_heartbeat", {"at": now_iso(), "ok": True})

    def fire_publish(self, schedule: dict[str, Any]) -> None:
        today = schedule_now(schedule).date().isoformat()
        try:
            execution_id = N8N.run_workflow(DAILY_WORKFLOW_ID)
        except Exception as exc:
            self.publish_retry_after = time.time() + 300
            with connect() as conn:
                log_event(conn, "error", "scheduled_publish_failed", f"Could not start the Daily Publisher: {redact(exc)}", details={"retry_in_seconds": 300})
                conn.commit()
            return
        set_state("last_publish_trigger_date", today)
        set_state("last_publish_trigger", {"at": now_iso(), "execution_id": execution_id, "publish_time": schedule["publish_time"], "dry_run": runtime_config()["dry_run"]})
        with connect() as conn:
            log_event(conn, "info", "scheduled_publish", f"Daily Publisher started for {today} at {schedule['publish_time']} {schedule['timezone']}", details={"execution_id": execution_id})
            conn.commit()

    def maybe_prepare(self, schedule: dict[str, Any]) -> None:
        with connect() as conn:
            active = active_queue_ids(conn)
        if len(active) >= schedule["queue_size"] or time.time() - self.last_prepare_trigger < PREPARE_COOLDOWN_SECONDS:
            return
        idle_until = get_state("prepare_idle_until")
        if idle_until and datetime.fromisoformat(idle_until) > datetime.now(timezone.utc):
            return
        if N8N.running(PREPARER_WORKFLOW_ID) or N8N.running(DAILY_WORKFLOW_ID):
            return
        last = N8N.last_execution(PREPARER_WORKFLOW_ID)
        if last and last["status"] in {"error", "crashed"} and last.get("stopped_at"):
            stopped = datetime.fromisoformat(last["stopped_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - stopped).total_seconds() < PREPARE_ERROR_BACKOFF_SECONDS:
                return
        self.last_prepare_trigger = time.time()
        execution_id = N8N.run_workflow(PREPARER_WORKFLOW_ID)
        with connect() as conn:
            log_event(conn, "info", "queue_refill", f"Preparing content ({len(active)}/{schedule['queue_size']} ready)", details={"execution_id": execution_id})
            conn.commit()

    def maybe_sync(self) -> None:
        if not os.environ.get("GITHUB_SYNC_TOKEN"):
            return
        state = get_state("github_sync") or {}
        if (self.last_sync_attempt and state.get("in_sync")) or time.time() - self.last_sync_attempt < 600:
            return
        self.last_sync_attempt = time.time()
        github_sync_schedule()


def dashboard_payload() -> dict[str, Any]:
    cfg = runtime_config()
    with connect() as conn:
        products = [row_to_dict(row) for row in conn.execute("SELECT * FROM products ORDER BY product_id")]
        logs = [row_to_dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200")]
    for product in products:
        if product is not None:
            product["has_preview"] = (PREVIEWS_DIR / f"{product['product_id']}.json").exists()
            product["error_message"] = redact(product["error_message"]) if product.get("error_message") else None
    for log in logs:
        if log is not None:
            log["message"] = redact(log.get("message") or "")
            log["details"] = redact(log["details"])[:2000] if log.get("details") not in (None, "") else None
    n8n: dict[str, Any] = {"ok": False, "workflows": [], "error": None, "daily_last": None, "preparer_last": None}
    try:
        workflows = N8N.get("/rest/workflows")
        n8n["workflows"] = sorted(
            ({"id": w.get("id"), "name": w.get("name"), "active": bool(w.get("active")), "updated_at": w.get("updatedAt")} for w in workflows if str(w.get("id", "")).startswith("3dpr")),
            key=lambda w: w["name"] or "",
        )
        n8n["daily_last"] = N8N.last_execution(DAILY_WORKFLOW_ID)
        n8n["preparer_last"] = N8N.last_execution(PREPARER_WORKFLOW_ID)
        n8n["ok"] = True
    except Exception as exc:
        n8n["error"] = redact(exc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with connect() as conn:
        db_ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        latest_ai = conn.execute("SELECT product_id, created_at, content_json FROM content_previews ORDER BY id DESC LIMIT 1").fetchone()
        recent = conn.execute("SELECT ts, level FROM logs ORDER BY id DESC LIMIT 1000").fetchall()
    errors_24h = sum(1 for r in recent if r["level"] == "error" and datetime.fromisoformat(r["ts"]) >= cutoff)
    ai_last = None
    if latest_ai:
        doc = json.loads(latest_ai["content_json"])
        ai_last = {
            "product_id": latest_ai["product_id"],
            "at": latest_ai["created_at"],
            "provider": doc.get("ai_provider_used"),
            "model": doc.get("ai_model_used") or doc.get("gemini_model_used"),
            "fallback_reason": redact(doc["ai_fallback_reason"])[:200] if doc.get("ai_fallback_reason") else None,
        }
    heartbeat = get_state("scheduler_heartbeat") or {}
    scheduler_alive = bool(heartbeat.get("at")) and (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat["at"])).total_seconds() < SCHEDULER_TICK_SECONDS * 4
    return {
        "time": now_iso(),
        "schedule": schedule_status(),
        "queue": queue_snapshot(),
        "ai_last": ai_last,
        "errors_24h": errors_24h,
        "system": {
            "tracking_api": True,
            "database": db_ok,
            "n8n": n8n["ok"],
            "scheduler": SCHEDULER_ENABLED and scheduler_alive and heartbeat.get("ok", False),
            "scheduler_enabled": SCHEDULER_ENABLED,
            "scheduler_error": heartbeat.get("error"),
        },
        "config": {
            "dry_run": cfg["dry_run"],
            "ai_provider": cfg.get("ai_provider"),
            "gemini_model": cfg.get("gemini_model"),
            "ai_fallback_provider": cfg.get("ai_fallback_provider"),
            "groq_model": cfg.get("groq_model"),
            "daily_cron": cfg.get("daily_cron"),
            "timezone": cfg.get("timezone"),
            "youtube_privacy_status": cfg.get("youtube_privacy_status"),
            "facebook_page_id_set": bool(str(cfg.get("facebook_page_id") or "").strip()),
            "instagram_account_set": bool(str(cfg.get("instagram_business_account_id") or "").strip()),
            "pinterest_board_set": bool(str(cfg.get("pinterest_board_id") or "").strip()),
            "drive_folder_set": bool(str(cfg.get("google_drive_folder_id") or "").strip()),
        },
        "products": products,
        "logs": logs,
        "n8n": n8n,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TrackingAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print("[%s] %s" % (now_iso(), format % args), flush=True)

    def _send(self, code: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        body = payload if isinstance(payload, (bytes, bytearray)) else json_dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path in {"/", "/health"}:
                self._send(200, {"ok": True, "service": "tracking-api", "time": now_iso(), "dry_run": runtime_config()["dry_run"]})
                return
            if path == "/config":
                self._send(200, runtime_config())
                return
            if path == "/status":
                self._send(200, status_payload())
                return
            if path == "/meta/readiness":
                cfg = runtime_config()
                self._send(
                    200,
                    {
                        "dry_run": cfg["dry_run"],
                        "meta_graph_version": cfg.get("meta_graph_version"),
                        "facebook_page_id_set": bool(str(cfg.get("facebook_page_id") or "").strip()),
                        "instagram_business_account_id_set": bool(
                            str(cfg.get("instagram_business_account_id") or "").strip()
                        ),
                        "pinterest_active_phase": False,
                        "youtube_shorts_done": True,
                        "publish_blocked_by_dry_run": bool(cfg["dry_run"]),
                        "next_steps": [
                            "Finish Pinterest OAuth first (see /pinterest/readiness)",
                            "Create a Meta Developer app (Business type)",
                            "Connect a Facebook Page + Instagram professional account",
                            "Generate a Page access token with pages_manage_posts + instagram_content_publish",
                            "Paste the token into n8n → Credentials → Facebook Graph account",
                            "Set FACEBOOK_PAGE_ID and INSTAGRAM_BUSINESS_ACCOUNT_ID in .env",
                            "Keep DRY_RUN=true until you explicitly approve a live post",
                        ],
                    },
                )
                return
            if path == "/pinterest/readiness":
                cfg = runtime_config()
                client_id_set = bool(str(os.environ.get("PINTEREST_OAUTH_CLIENT_ID") or "").strip())
                client_secret_set = bool(str(os.environ.get("PINTEREST_OAUTH_CLIENT_SECRET") or "").strip())
                board_id = str(cfg.get("pinterest_board_id") or "").strip()
                self._send(
                    200,
                    {
                        "ok": True,
                        "dry_run": cfg["dry_run"],
                        "image_pins_only": True,
                        "video_pins_skipped": True,
                        "publish_blocked_by_dry_run": bool(cfg["dry_run"]),
                        "pinterest_board_id_set": bool(board_id),
                        "oauth_redirect_uri": "http://localhost:5678/rest/oauth2-credential/callback",
                        "required_scopes": [
                            "user_accounts:read",
                            "boards:read",
                            "boards:write",
                            "pins:read",
                            "pins:write",
                        ],
                        "n8n_credential_name": "Pinterest account",
                        "n8n_credential_type": "oAuth2Api",
                        "auth_url": "https://www.pinterest.com/oauth/",
                        "access_token_url": "https://api.pinterest.com/v5/oauth/token",
                        "oauth_client_id_env_set": client_id_set,
                        "oauth_client_secret_env_set": client_secret_set,
                        "oauth_browser_consent_required": True,
                        "pin_create_allowed": False,
                        "note": "Auth is completed in n8n Connect my account. Never paste app secrets or tokens into chat. DRY_RUN blocks all Pin creates.",
                        "next_browser_steps": [
                            "Open https://developers.pinterest.com/apps/ with a Pinterest business account",
                            "Accept Developer Terms if prompted",
                            "Click Connect app and submit trial access",
                            "Add redirect URI http://localhost:5678/rest/oauth2-credential/callback",
                            "Paste App ID/Secret only into n8n → Credentials → Pinterest account",
                            "Click Connect my account",
                            "Run 11 Pinterest Auth Probe (read-only)",
                            "Set PINTEREST_BOARD_ID from a listed board id",
                            "Keep DRY_RUN=true",
                        ],
                    },
                )
                return
            if path == "/youtube/readiness":
                cfg = runtime_config()
                client_id_set = bool(str(os.environ.get("YOUTUBE_OAUTH_CLIENT_ID") or "").strip())
                client_secret_set = bool(str(os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET") or "").strip())
                self._send(
                    200,
                    {
                        "ok": True,
                        "dry_run": cfg["dry_run"],
                        "youtube_format": cfg.get("youtube_format") or "shorts",
                        "youtube_privacy_status": cfg.get("youtube_privacy_status") or "private",
                        "publish_blocked_by_dry_run": bool(cfg["dry_run"]),
                        "long_form_disabled": True,
                        "oauth_redirect_uri": "http://localhost:5678/rest/oauth2-credential/callback",
                        "required_scopes": [
                            "https://www.googleapis.com/auth/youtube.upload",
                            "https://www.googleapis.com/auth/youtube.readonly",
                        ],
                        "n8n_credential_name": "YouTube account",
                        "n8n_credential_type": "youTubeOAuth2Api",
                        "oauth_client_id_env_set": client_id_set,
                        "oauth_client_secret_env_set": client_secret_set,
                        "oauth_browser_consent_required": True,
                        "upload_allowed": False,
                        "note": "Auth is completed in n8n Sign in with Google. Never paste client secrets or tokens into chat. DRY_RUN blocks all uploads.",
                        "next_browser_steps": [
                            "Enable YouTube Data API v3 in Google Cloud",
                            "Configure OAuth consent screen (External or Internal)",
                            "Create OAuth client type Web application",
                            "Add redirect URI http://localhost:5678/rest/oauth2-credential/callback",
                            "Paste Client ID/Secret only into n8n → Credentials → YouTube account",
                            "Click Sign in with Google (channel owner account)",
                            "Keep DRY_RUN=true",
                        ],
                    },
                )
                return
            if path in {"/admin", "/dashboard"}:
                self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/dashboard/data":
                self._send(200, dashboard_payload())
                return
            if path == "/schedule":
                self._send(200, schedule_status())
                return
            if path == "/queue":
                self._send(200, queue_snapshot())
                return
            if path == "/dashboard/executions":
                try:
                    self._send(
                        200,
                        dashboard_executions(
                            int(query.get("limit", ["50"])[0]),
                            query.get("workflow_id", [""])[0],
                            query.get("status", [""])[0],
                        ),
                    )
                except (RuntimeError, OSError) as exc:
                    self._send(502, {"error": redact(exc)})
                return
            if path.startswith("/dashboard/executions/"):
                try:
                    self._send(200, dashboard_execution_detail(int(path.rsplit("/", 1)[-1])))
                except (RuntimeError, OSError) as exc:
                    self._send(502, {"error": redact(exc)})
                return
            if path == "/samples":
                self._send(200, {"files": list_sample_files()})
                return
            if path == "/products":
                with connect() as conn:
                    products = [row_to_dict(row) for row in conn.execute("SELECT * FROM products ORDER BY product_id")]
                self._send(200, {"products": products})
                return
            if path.startswith("/products/") and path.endswith("/can-publish"):
                parts = path.strip("/").split("/")
                product_id = int(parts[1])
                platform = query.get("platform", [""])[0]
                self._send(200, can_publish(product_id, platform))
                return
            if path.startswith("/products/") and path.count("/") == 2:
                product_id = int(path.rsplit("/", 1)[-1])
                with connect() as conn:
                    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
                if row is None:
                    self._send(404, {"error": f"Unknown product_id {product_id}"})
                    return
                self._send(200, row_to_dict(row))
                return
            if path == "/logs":
                limit = int(query.get("limit", ["100"])[0])
                with connect() as conn:
                    logs = [row_to_dict(row) for row in conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))]
                self._send(200, {"logs": logs})
                return
            if path == "/media/size":
                target = (MEDIA_DIR / Path(query.get("name", [""])[0]).name).resolve()
                if target.parent != MEDIA_DIR.resolve() or not target.is_file():
                    self._send(404, {"error": "Media file not found"})
                    return
                self._send(200, {"name": target.name, "path": str(target), "bytes": target.stat().st_size})
                return
            if path.startswith("/media/"):
                filename = path.split("/media/", 1)[1]
                if "/" in filename or "\\" in filename or filename.startswith("."):
                    self._send(400, {"error": "Invalid filename"})
                    return
                for folder in (MEDIA_DIR, SAMPLES_DIR):
                    candidate = folder / filename
                    if candidate.exists() and candidate.is_file():
                        data = candidate.read_bytes()
                        ext = candidate.suffix.lower()
                        content_type = {
                            ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".png": "image/png",
                            ".webp": "image/webp",
                            ".mp4": "video/mp4",
                            ".mov": "video/quicktime",
                            ".json": "application/json",
                        }.get(ext, "application/octet-stream")
                        self._send(200, data, content_type)
                        return
                self._send(404, {"error": "File not found"})
                return
            if path.startswith("/previews/"):
                product_id = path.split("/previews/", 1)[1]
                path_file = PREVIEWS_DIR / f"{product_id}.json"
                if not path_file.exists():
                    self._send(404, {"error": "Preview not found"})
                    return
                self._send(200, json.loads(path_file.read_text(encoding="utf-8")))
                return
            self._send(404, {"error": f"Not found: {path}"})
        except Exception as exc:
            self._send(500, {"error": str(exc), "trace": traceback.format_exc()})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            body = self._read_json()
            if path == "/init":
                init_db()
                self._send(200, {"ok": True, "db": str(DB_PATH)})
                return
            if path == "/logs":
                with connect() as conn:
                    log_event(
                        conn,
                        str(body.get("level", "info")),
                        str(body.get("event", "custom")),
                        str(body.get("message", "")),
                        product_id=body.get("product_id"),
                        platform=body.get("platform"),
                        details=body.get("details"),
                    )
                    conn.commit()
                self._send(
                    200,
                    {
                        "ok": True,
                        "product_id": body.get("product_id"),
                        "event": body.get("event", "custom"),
                    },
                )
                return
            if path == "/files/parse":
                self._send(200, parse_files(body.get("files", [])))
                return
            if path == "/products/select-next":
                self._send(200, select_next(body.get("files", [])))
                return
            if path == "/products/retry-failed":
                self._send(200, retry_failed())
                return
            if path == "/schedule":
                if not self._same_origin():
                    self._send(403, {"error": "Schedule changes are only accepted from the local dashboard."})
                    return
                self._send(200, save_schedule(str(body.get("publish_time") or "").strip(), "dashboard"))
                return
            if path == "/queue/select-to-prepare":
                self._send(200, select_to_prepare(body.get("files", [])))
                return
            if path == "/queue/claim":
                self._send(200, claim_next())
                return
            if path == "/pinterest/s3-upload":
                self._send(200, pinterest_s3_upload(body))
                return
            if path.startswith("/products/") and path.endswith("/reset-preview"):
                self._send(200, reset_preview(int(path.split("/")[2])))
                return
            if path.startswith("/products/") and path.endswith("/processing"):
                product_id = int(path.split("/")[2])
                self._send(200, mark_processing(product_id))
                return
            if path.startswith("/products/") and path.endswith("/platform-result"):
                product_id = int(path.split("/")[2])
                result = save_platform_result(
                    product_id,
                    str(body.get("platform")),
                    str(body.get("status")),
                    body.get("post_id"),
                    body.get("error_message"),
                )
                self._send(200, result)
                return
            if path.startswith("/products/") and path.endswith("/finalize"):
                raw_id = path.split("/")[2]
                try:
                    product_id = int(raw_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"finalize requires a numeric product_id in the URL path; got {raw_id!r}"
                    ) from exc
                self._send(200, finalize_product(product_id))
                return
            if path == "/previews":
                saved = save_preview(body)
                self._send(200, saved)
                return
            if path == "/media/prepare-vision":
                self._send(200, prepare_vision(body))
                return
            if path == "/drive/public-list":
                folder_id = str(body.get("folder_id") or runtime_config().get("google_drive_folder_id") or "")
                self._send(200, list_public_drive_folder(folder_id))
                return
            if path == "/drive/public-download":
                self._send(
                    200,
                    download_public_drive_file(
                        str(body.get("file_id") or body.get("drive_file_id") or ""),
                        str(body.get("filename") or ""),
                        str(body.get("folder_id") or runtime_config().get("google_drive_folder_id") or ""),
                    ),
                )
                return
            if path == "/ai/mock":
                self._send(410, {"error": "Mock AI is removed from the production path. Use Google Gemini through the n8n Google Gemini account credential."})
                return
            self._send(404, {"error": f"Not found: {path}"})
        except KeyError as exc:
            self._send(404, {"error": str(exc)})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc), "trace": traceback.format_exc()})


DASHBOARD_HTML = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")


def main() -> None:
    for folder in (DB_PATH.parent, MEDIA_DIR, PREVIEWS_DIR, LOGS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    init_db()
    if SCHEDULER_ENABLED:
        if get_state("last_publish_trigger_date") is None:
            skip_today_if_slot_passed("Scheduler first start after today's slot; today is treated as already handled to avoid a duplicate post.")
        threading.Thread(target=Scheduler().run_forever, name="scheduler", daemon=True).start()
    print(f"Scheduler: {'enabled' if SCHEDULER_ENABLED else 'disabled'} ({load_schedule()['publish_time']} {load_schedule()['timezone']})", flush=True)
    print(f"Tracking API listening on {HOST}:{PORT}", flush=True)
    print(f"SQLite database: {DB_PATH}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
