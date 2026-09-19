#!/usr/bin/env python3
"""Full DRY_RUN: advance past previewed products, run Daily Publisher, verify preview quality."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402

DAILY_WF = "3dprDailyPub0001"
TRACKING = "http://127.0.0.1:8081"
REQUIRED_NODES = [
    "List Google Drive Folder",
    "Select Next Product",
    "Download Drive Media",
    "Prepare Vision Still",
    "Generate AI Content",
    "Save Preview",
    "Finalize Dry Run",
]


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_flat(arr, x, depth=0):
    if depth > 80:
        return x
    if isinstance(x, str) and x.isdigit():
        i = int(x)
        if isinstance(arr, list) and i < len(arr):
            return resolve_flat(arr, arr[i], depth + 1)
    if isinstance(x, list):
        return [resolve_flat(arr, v, depth + 1) for v in x]
    if isinstance(x, dict):
        return {k: resolve_flat(arr, v, depth + 1) for k, v in x.items()}
    return x


def node_ok(run_data: dict, name: str) -> dict:
    runs = run_data.get(name) or []
    for nr in runs if isinstance(runs, list) else [runs]:
        err = (nr or {}).get("error")
        main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
        j = main[0].get("json") if main else None
        if err:
            return {"ok": False, "error": str(err.get("message") if isinstance(err, dict) else err)[:400]}
        if isinstance(j, dict):
            return {
                "ok": True,
                "product_id": j.get("product_id"),
                "filename": j.get("filename"),
                "overall_status": j.get("overall_status"),
            }
    return {"ok": False, "error": "missing"}


def quality_report(preview: dict) -> dict:
    content = preview.get("content") or {}
    issues: list[str] = []
    for platform in ("instagram", "facebook", "pinterest", "youtube"):
        if platform not in content:
            issues.append(f"missing {platform}")
    ig = content.get("instagram") or {}
    fb = content.get("facebook") or {}
    pin = content.get("pinterest") or {}
    yt = content.get("youtube") or {}

    if not ig.get("caption") or "\\n" not in ig.get("caption", "") and "\n" not in ig.get("caption", ""):
        issues.append("instagram caption lacks line breaks")
    ig_tags = ig.get("hashtags") or []
    fb_tags = fb.get("hashtags") or []
    if ig_tags and fb_tags and sorted(ig_tags) == sorted(fb_tags):
        issues.append("instagram and facebook hashtags are identical")
    if not (5 <= len(ig_tags) <= 10):
        issues.append(f"instagram hashtag count odd: {len(ig_tags)}")
    if not (3 <= len(fb_tags) <= 8):
        issues.append(f"facebook hashtag count odd: {len(fb_tags)}")
    if not pin.get("title") or not pin.get("description") or not (pin.get("keywords") or []):
        issues.append("pinterest SEO fields incomplete")
    yt_desc = str(yt.get("description") or "")
    if len(yt_desc) < 40:
        issues.append("youtube shorts description too short")
    if len(yt_desc) > 1200:
        issues.append("youtube description looks long-form; Shorts should stay concise")
    if len(yt.get("tags") or []) < 3:
        issues.append("youtube tags too few")
    title = str(yt.get("title") or "")
    if len(title) > 100:
        issues.append("youtube shorts title too long")
    hashtags = [str(h).lower() for h in (yt.get("hashtags") or [])]
    if not any(h.replace("#", "") == "shorts" for h in hashtags) and "#shorts" not in yt_desc.lower():
        issues.append("youtube shorts missing #shorts")

    blob = json.dumps(content).lower()
    for banned in ("http://", "https://", "www.", "shipping", "$", "£", "€", "in stock"):
        if banned in blob:
            issues.append(f"possible banned claim/url: {banned}")

    meta_ok = all(
        preview.get(k)
        for k in ("product_id", "filename", "media_type", "drive_file_id", "content")
    )
    if not meta_ok:
        issues.append("preview metadata incomplete")

    return {
        "meta_ok": meta_ok,
        "issues": issues,
        "instagram_caption_preview": str(ig.get("caption") or "")[:220],
        "facebook_caption_preview": str(fb.get("caption") or "")[:220],
        "pinterest_title": pin.get("title"),
        "youtube_title": yt.get("title"),
        "youtube_description_len": len(yt_desc),
        "ig_hashtags": ig_tags,
        "fb_hashtags": fb_tags,
    }


def main() -> None:
    env = load_env()
    cfg = http_json("GET", f"{TRACKING}/config")
    print("config", {"dry_run": cfg.get("dry_run"), "gemini_model": cfg.get("gemini_model")})
    if cfg.get("dry_run") is not True:
        raise SystemExit("DRY_RUN must stay true")

    # Advance any stuck processing product into previewed so the next ID is selected.
    status = http_json("GET", f"{TRACKING}/status")
    for product in status.get("products") or []:
        if product.get("overall_status") in {"processing", "pending"} and product.get("product_id") == 1:
            fin = http_json("POST", f"{TRACKING}/products/1/finalize", {})
            print("advance_product_1", fin.get("overall_status"), fin.get("product_id"))

    client = N8n(f"http://127.0.0.1:{env.get('N8N_PORT', '5678')}")
    st, _ = client.json(
        "POST",
        "/rest/login",
        {
            "emailOrLdapLoginId": env.get("N8N_OWNER_EMAIL", "admin@localhost.local"),
            "password": env.get("N8N_OWNER_PASSWORD", ""),
        },
    )
    if st not in {200, 201}:
        raise SystemExit(f"login failed: {st}")

    st, run = client.json(
        "POST",
        f"/rest/workflows/{DAILY_WF}/run",
        {"triggerToStartFrom": {"name": "Run Manually"}},
    )
    eid = (run.get("data") or {}).get("executionId")
    print("execution", eid)
    result: dict = {"ok": False, "execution_id": eid, "nodes": {}}
    for _ in range(300):
        st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
        d = detail.get("data", detail)
        status_name = d.get("status")
        if status_name not in {"success", "error", "crashed", "canceled"}:
            time.sleep(1)
            continue
        result["status"] = status_name
        arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
        root = resolve_flat(arr, arr[0])
        run_data = (root.get("resultData") or {}).get("runData") or {}
        for name in REQUIRED_NODES:
            result["nodes"][name] = node_ok(run_data, name)
        selected = result["nodes"].get("Select Next Product") or {}
        finalized = result["nodes"].get("Finalize Dry Run") or {}
        result["product_id"] = selected.get("product_id")
        result["filename"] = selected.get("filename")
        result["finalize_status"] = finalized.get("overall_status")
        result["ok"] = status_name == "success" and all(
            (result["nodes"].get(n) or {}).get("ok") for n in REQUIRED_NODES
        )
        if not result["ok"]:
            for name in REQUIRED_NODES:
                info = result["nodes"].get(name) or {}
                if not info.get("ok"):
                    result["failed_node"] = name
                    result["error"] = info.get("error")
                    break
        break
    else:
        raise SystemExit("timeout")

    if not result.get("ok"):
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    pid = result["product_id"]
    preview = http_json("GET", f"{TRACKING}/previews/{pid}")
    file_preview = json.loads((ROOT / "data" / "previews" / f"{pid}.json").read_text(encoding="utf-8"))
    report = quality_report(preview)
    out = {
        "workflow_ok": True,
        "product_id": pid,
        "filename": result.get("filename"),
        "finalize_status": result.get("finalize_status"),
        "preview_meta": {
            "product_id": preview.get("product_id"),
            "filename": preview.get("filename"),
            "media_type": preview.get("media_type"),
            "drive_file_id": preview.get("drive_file_id"),
            "google_drive_folder_id": preview.get("google_drive_folder_id"),
            "dry_run": preview.get("dry_run"),
            "ai_provider_used": preview.get("ai_provider_used"),
            "gemini_model_used": preview.get("gemini_model_used"),
        },
        "file_matches_api": preview.get("content") == file_preview.get("content"),
        "quality": report,
        "advanced_past_product_1": pid not in (1, "1"),
    }
    print(json.dumps(out, indent=2))
    if not report["meta_ok"] or report["issues"]:
        # Soft-fail on stylistic issues only if metadata missing; hard-fail metadata.
        if not report["meta_ok"]:
            raise SystemExit(2)
        print("QUALITY_WARNINGS", report["issues"])
    if pid in (1, "1"):
        print("NOTE: selected product_id is still 1; check whether later products exist in Drive")


if __name__ == "__main__":
    main()
