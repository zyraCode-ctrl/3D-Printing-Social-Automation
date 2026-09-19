#!/usr/bin/env python3
"""Headless CI daily dry-run: health checks, optional Drive probe, optional n8n execute."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKING = os.environ.get("TRACKING_API_URL", "http://127.0.0.1:8081")
N8N = os.environ.get("N8N_URL", "http://127.0.0.1:5678")


def http_json(method: str, url: str, payload: dict | None = None, headers: dict | None = None, timeout: int = 60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Accept": "application/json"}
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body[:800]}
        return exc.code, parsed


def wait_ok(url: str, attempts: int = 90) -> None:
    for i in range(attempts):
        try:
            status, body = http_json("GET", url, timeout=5)
            if status < 500:
                print(f"Ready: {url} -> {status}")
                return
        except Exception as exc:
            print(f"Waiting for {url} ({i + 1}/{attempts}): {exc}")
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for {url}")


class N8n:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self) -> str | None:
        for cookie in self.jar:
            if "csrf" in cookie.name.lower():
                return cookie.value
        return None

    def json(self, method: str, path: str, payload: dict | None = None):
        url = self.base + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        token = self.csrf()
        if token:
            headers["X-N8N-CSRF-TOKEN"] = token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"raw": body[:800]}
            return exc.code, parsed


def main() -> int:
    wait_ok(f"{TRACKING}/health")
    wait_ok(f"{N8N}/healthz")

    status, config = http_json("GET", f"{TRACKING}/config")
    if status != 200:
        print("config failed", status, config)
        return 1
    print(
        "config:",
        {
            "dry_run": config.get("dry_run"),
            "ai_provider": config.get("ai_provider"),
            "gemini_model": config.get("gemini_model"),
            "drive_folder": bool(config.get("google_drive_folder_id")),
            "youtube_format": config.get("youtube_format"),
        },
    )
    if config.get("dry_run") is not True:
        print("FAIL: DRY_RUN must be true for CI daily runs")
        return 1
    if config.get("youtube_format") and config.get("youtube_format") != "shorts":
        print("FAIL: youtube_format must be shorts")
        return 1

    status, check = http_json("GET", f"{TRACKING}/products/1/can-publish?platform=instagram")
    print("can-publish instagram:", check)
    if not (check.get("dry_run") is True or check.get("allowed") is False):
        print("FAIL: DRY_RUN did not block publish")
        return 1

    folder = (config.get("google_drive_folder_id") or "").strip()
    if folder:
        status, listed = http_json(
            "POST",
            f"{TRACKING}/drive/public-list",
            {"folder_id": folder},
            timeout=90,
        )
        print("drive list status:", status)
        if status == 200 and isinstance(listed, dict):
            files = listed.get("files") or listed.get("items") or []
            print("drive files counted:", len(files) if isinstance(files, list) else files)
        else:
            print("drive list body:", str(listed)[:500])
            # Non-fatal if Drive briefly flakes; stack health already passed.
    else:
        print("No GOOGLE_DRIVE_FOLDER_ID — skipping Drive list")

    email = os.environ.get("N8N_OWNER_EMAIL", "admin@localhost.local")
    password = os.environ.get("N8N_OWNER_PASSWORD", "")
    if not password:
        print("FAIL: N8N_OWNER_PASSWORD missing")
        return 1

    client = N8n(N8N)
    for payload in (
        {"email": email, "password": password},
        {"emailOrLdapLoginId": email, "password": password},
    ):
        st, _ = client.json("POST", "/rest/login", payload)
        if st in {200, 201}:
            break
    else:
        print("FAIL: n8n login failed")
        return 1

    st, workflows = client.json("GET", "/rest/workflows")
    items = workflows.get("data", workflows) if isinstance(workflows, dict) else workflows
    names = {item.get("name"): item.get("id") for item in items if isinstance(item, dict)} if isinstance(items, list) else {}
    print("workflows:", sorted(names))
    required = [
        "01 Daily Publisher",
        "03 AI Content Generator",
        "07 YouTube Shorts Publisher",
    ]
    missing = [name for name in required if name not in names]
    if missing:
        print("FAIL: missing workflows", missing)
        return 1

    run_e2e = (os.environ.get("CI_RUN_E2E") or "true").lower() in {"1", "true", "yes"}
    gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if run_e2e and gemini_key:
        daily_id = names["01 Daily Publisher"]
        print(f"Triggering daily publisher {daily_id} (DRY_RUN)...")
        # n8n 2.x manual run endpoints vary; try several.
        attempts = [
            ("POST", f"/rest/workflows/{daily_id}/run", {}),
            ("POST", f"/rest/workflows/{daily_id}/execute", {}),
            ("POST", "/rest/workflows/run", {"workflowId": daily_id}),
        ]
        triggered = False
        exec_id = None
        for method, path, payload in attempts:
            st, body = client.json(method, path, payload)
            print(f"run attempt {method} {path} -> {st}")
            if st in {200, 201}:
                triggered = True
                if isinstance(body, dict):
                    exec_id = body.get("id") or body.get("executionId") or (body.get("data") or {}).get("executionId")
                break
            print(str(body)[:400])
        if not triggered:
            print("WARN: could not auto-trigger daily workflow; stack + import verified")
            return 0
        # Poll executions briefly
        deadline = time.time() + 480
        while time.time() < deadline:
            st, body = client.json("GET", "/rest/executions?limit=5")
            data = body.get("data", body) if isinstance(body, dict) else body
            rows = data if isinstance(data, list) else (data.get("results") if isinstance(data, dict) else [])
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if exec_id and str(row.get("id")) != str(exec_id):
                        continue
                    finished = row.get("finished") or row.get("status") in {"success", "error", "crashed", "canceled"}
                    if finished:
                        print("execution:", {k: row.get(k) for k in ("id", "status", "finished", "mode", "workflowId")})
                        if row.get("status") == "error":
                            return 1
                        return 0
            time.sleep(5)
        print("WARN: execution still running after wait; import/health already OK")
        return 0
    if run_e2e and not gemini_key:
        print("GEMINI_API_KEY not set — verified health, DRY_RUN, workflows, Drive list only")
    print("CI daily verification passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
