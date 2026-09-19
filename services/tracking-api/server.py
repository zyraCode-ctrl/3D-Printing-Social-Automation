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
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request
import http.cookiejar

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


def runtime_config() -> dict[str, Any]:
    settings = load_settings_file()
    dry_run = env_bool("DRY_RUN", True)
    use_sample = env_bool("USE_SAMPLE_MEDIA", False)
    include_url = env_bool("INCLUDE_WEBSITE_URL", False)
    ai = settings.get("ai", {})
    config = {
        **settings,
        "dry_run": dry_run,
        "use_sample_media": use_sample,
        "daily_cron": os.environ.get("DAILY_CRON", settings.get("daily_cron", "0 9 * * *")),
        "timezone": os.environ.get("GENERIC_TIMEZONE", settings.get("timezone", "Asia/Kolkata")),
        "google_drive_folder_id": os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "") or settings.get("google_drive_folder_id", ""),
        "facebook_page_id": os.environ.get("FACEBOOK_PAGE_ID", ""),
        "instagram_business_account_id": os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
        "meta_graph_version": os.environ.get("META_GRAPH_VERSION", "v22.0"),
        "pinterest_board_id": os.environ.get("PINTEREST_BOARD_ID", ""),
        "youtube_privacy_status": os.environ.get("YOUTUBE_PRIVACY_STATUS", settings.get("youtube_privacy_status", "private")),
        "website_url": os.environ.get("WEBSITE_URL", "") or settings.get("website_url", ""),
        "include_website_url": include_url or bool(settings.get("include_website_url")),
        "ai_provider": os.environ.get("AI_PROVIDER", ai.get("provider", "gemini")),
        "gemini_model": os.environ.get("GEMINI_MODEL", ai.get("gemini_model", "gemini-3.6-flash")),
        "gemini_host": os.environ.get("GEMINI_HOST", ai.get("gemini_host", "https://generativelanguage.googleapis.com")),
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


def select_next(files: list[dict[str, Any]]) -> dict[str, Any]:
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
        "gemini_model_used": body.get("gemini_model_used"),
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
                        "pinterest_skipped_this_phase": True,
                        "youtube_skipped_this_phase": True,
                        "publish_blocked_by_dry_run": bool(cfg["dry_run"]),
                        "next_steps": [
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
            if path == "/admin":
                self._send(200, ADMIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
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


ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>3D Print Social Status</title>
  <style>
    :root { color-scheme: light; font-family: Georgia, serif; }
    body { margin: 24px; background: #f6f1e8; color: #1f1b16; }
    h1 { font-size: 1.6rem; }
    .cards { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
    .card { background: #fff; border: 1px solid #d9cfc0; border-radius: 12px; padding: 12px 16px; min-width: 160px; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { border-bottom: 1px solid #eadfce; padding: 8px; text-align: left; font-size: 0.92rem; }
    .pending { color: #8a6d3b; }
    .published { color: #2f6f3e; }
    .failed { color: #9b2c2c; }
    .partial { color: #9a5b12; }
    .processing { color: #1d4e89; }
    .muted { color: #6b6258; font-size: 0.9rem; }
  </style>
</head>
<body>
  <h1>3D Printing Store — posting status</h1>
  <p class="muted">Read-only tracker. Use n8n at <a href="http://localhost:5678">http://localhost:5678</a> to run or retry workflows. DRY_RUN stays on until you change it.</p>
  <div class="cards" id="cards"></div>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>File</th><th>Type</th><th>Overall</th>
        <th>IG</th><th>FB</th><th>Pin</th><th>YT</th><th>Attempts</th><th>Updated</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
  <h2>Recent logs</h2>
  <pre id="logs" class="muted"></pre>
  <script>
    async function load() {
      const data = await fetch('/status').then(r => r.json());
      const cfg = data.config || {};
      document.getElementById('cards').innerHTML = [
        ['DRY_RUN', cfg.dry_run],
        ['Sample media', cfg.use_sample_media],
        ['AI', cfg.ai_provider],
        ['Timezone', cfg.timezone]
      ].map(([k,v]) => `<div class="card"><strong>${k}</strong><div>${v}</div></div>`).join('');
      document.getElementById('rows').innerHTML = (data.products || []).map(p => `
        <tr>
          <td>${p.product_id}</td>
          <td>${p.filename}</td>
          <td>${p.media_type}</td>
          <td class="${p.overall_status}">${p.overall_status}</td>
          <td class="${p.instagram_status}">${p.instagram_status}</td>
          <td class="${p.facebook_status}">${p.facebook_status}</td>
          <td class="${p.pinterest_status}">${p.pinterest_status}</td>
          <td class="${p.youtube_status}">${p.youtube_status}</td>
          <td>${p.attempt_count}</td>
          <td>${p.updated_at}</td>
        </tr>`).join('');
      document.getElementById('logs').textContent = (data.recent_logs || []).map(l =>
        `${l.ts} [${l.level}] ${l.event} ${l.product_id ?? ''} ${l.platform ?? ''} — ${l.message}`
      ).join('\\n');
    }
    load();
    setInterval(load, 5000);
  </script>
</body>
</html>
"""


def main() -> None:
    for folder in (DB_PATH.parent, MEDIA_DIR, PREVIEWS_DIR, LOGS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    init_db()
    print(f"Tracking API listening on {HOST}:{PORT}", flush=True)
    print(f"SQLite database: {DB_PATH}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
