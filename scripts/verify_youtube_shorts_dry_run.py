#!/usr/bin/env python3
"""Verify YouTube OAuth + Shorts DRY_RUN path. Never uploads."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N8N = "http://127.0.0.1:5678"
TRACK = "http://127.0.0.1:8081"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            values[k.strip()] = v.strip()
    return values


class N8n:
    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def json(self, method: str, path: str, payload: dict | None = None, timeout: int = 120):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        for cookie in self.jar:
            if "csrf" in cookie.name.lower():
                headers["X-N8N-CSRF-TOKEN"] = cookie.value
                break
        req = urllib.request.Request(N8N + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                body = resp.read().decode()
                if not body or body.lstrip()[:1] not in "{[":
                    return resp.status, {"raw": body[:400]}
                return resp.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if not body or body.lstrip()[:1] not in "{[":
                return exc.code, {"raw": body[:400]}
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"raw": body[:400]}


def track(path: str):
    with urllib.request.urlopen(TRACK + path, timeout=30) as resp:
        return json.loads(resp.read().decode())


def wait_exec(client: N8n, exec_id: str, seconds: int = 300) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        _st, wrap = client.json("GET", f"/rest/executions/{exec_id}?includeData=true")
        ex = wrap.get("data", wrap) if isinstance(wrap, dict) else {}
        if not isinstance(ex, dict):
            time.sleep(2)
            continue
        status = ex.get("status")
        finished = ex.get("finished")
        if finished or status in {"success", "error", "crashed", "canceled"}:
            return ex
        time.sleep(2)
    raise SystemExit(f"execution {exec_id} timed out")


def summarize_probe(ex: dict) -> dict | None:
    from dump_execution import resolve_flat

    raw = ex.get("data")
    if isinstance(raw, str):
        arr = json.loads(raw)
        root = resolve_flat(arr, arr[0])
    elif isinstance(raw, dict):
        root = raw
    else:
        return None
    run_data = (root.get("resultData") or {}).get("runData") or {}
    for name, entries in run_data.items():
        if "summarize" not in str(name).lower():
            continue
        nr = entries[0] if isinstance(entries, list) else entries
        main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
        if main and isinstance(main[0], dict):
            return main[0].get("json")
    return None


def main() -> int:
    env = load_env()
    client = N8n()
    st, _ = client.json(
        "POST",
        "/rest/login",
        {"emailOrLdapLoginId": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"]},
    )
    print("login", st, flush=True)
    if st not in {200, 201}:
        st, _ = client.json(
            "POST",
            "/rest/login",
            {"email": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"]},
        )
        print("login_retry", st, flush=True)
    if st not in {200, 201}:
        return 1

    cfg = track("/config")
    print("dry_run", cfg.get("dry_run"), "youtube_format", cfg.get("youtube_format"), flush=True)
    if cfg.get("dry_run") is not True or cfg.get("youtube_format") != "shorts":
        return 1

    ready = track("/youtube/readiness")
    print(
        "upload_allowed",
        ready.get("upload_allowed"),
        "blocked",
        ready.get("publish_blocked_by_dry_run"),
        flush=True,
    )

    st, wfs = client.json("GET", "/rest/workflows")
    items = wfs.get("data", wfs) if isinstance(wfs, dict) else wfs
    by_name = {i.get("name"): i.get("id") for i in (items or []) if isinstance(i, dict)}
    probe_id = by_name.get("10 YouTube Shorts Auth Probe")
    daily_id = by_name.get("01 Daily Publisher")
    print("probe", probe_id, "daily", daily_id, flush=True)
    if not probe_id or not daily_id:
        return 1

    st, run = client.json(
        "POST",
        f"/rest/workflows/{probe_id}/run",
        {"triggerToStartFrom": {"name": "Run Manually"}},
    )
    print("probe_run", st, flush=True)
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    exec_id = (data or {}).get("executionId") or (data or {}).get("id") or run.get("executionId") or run.get("id")
    print("probe_exec", exec_id, flush=True)
    if not exec_id:
        print("probe_body", str(run)[:400], flush=True)
        return 1
    ex = wait_exec(client, str(exec_id), 180)
    print("probe_status", ex.get("status"), flush=True)
    summary = summarize_probe(ex)
    if summary:
        print("oauth_ok", summary.get("oauth_ok"), flush=True)
        print("upload_attempted", summary.get("upload_attempted"), flush=True)
        print("channels", len(summary.get("channels_found") or []), flush=True)
        print("error", summary.get("error"), flush=True)
        if not summary.get("oauth_ok"):
            return 1
        if summary.get("upload_attempted"):
            return 1
    else:
        print("summary_missing", flush=True)
        return 1

    check = track("/products/1/can-publish?platform=youtube")
    print("yt_can_publish", check.get("allowed"), check.get("dry_run"), flush=True)
    if check.get("allowed") is not False:
        return 1

    st, run = client.json(
        "POST",
        f"/rest/workflows/{daily_id}/run",
        {"triggerToStartFrom": {"name": "Run Manually"}},
    )
    print("daily_run", st, flush=True)
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    daily_exec = (data or {}).get("executionId") or (data or {}).get("id") or run.get("executionId") or run.get("id")
    print("daily_exec", daily_exec, flush=True)
    if not daily_exec:
        return 1
    daily_ex = wait_exec(client, str(daily_exec), 480)
    print("daily_status", daily_ex.get("status"), flush=True)

    prod = track("/products/1")
    print("product1_youtube", prod.get("youtube_status"), "overall", prod.get("overall_status"), flush=True)
    if prod.get("youtube_status") == "published":
        return 1

    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
