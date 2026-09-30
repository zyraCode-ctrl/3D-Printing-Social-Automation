#!/usr/bin/env python3
"""Offline tests for the dashboard schedule, rolling queue, duplicate prevention and GitHub sync.

Runs the real tracking-api code against a throwaway SQLite DB; never touches n8n or social APIs.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="zyra-test-"))
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}" + (f" — {detail}" if not condition and detail != "" else ""))
    if not condition:
        FAILURES.append(name)


class MockGitHub(BaseHTTPRequestHandler):
    files: dict[str, dict] = {}
    puts: list[dict] = []
    auth: list[str] = []

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        MockGitHub.auth.append(self.headers.get("Authorization", ""))
        path = self.path.split("?")[0]
        if path in MockGitHub.files:
            self._send(200, MockGitHub.files[path])
        else:
            self._send(404, {"message": "Not Found"})

    def do_PUT(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        MockGitHub.puts.append(body)
        path = self.path.split("?")[0]
        MockGitHub.files[path] = {"sha": f"sha{len(MockGitHub.puts)}", "content": body["content"]}
        self._send(200, {"commit": {"sha": f"commit{len(MockGitHub.puts)}"}})


def load_server():
    github = ThreadingHTTPServer(("127.0.0.1", 0), MockGitHub)
    threading.Thread(target=github.serve_forever, daemon=True).start()
    (TMP / "config").mkdir()
    shutil.copy(ROOT / "config" / "settings.json", TMP / "config" / "settings.json")
    os.environ.update(
        {
            "APP_ROOT": str(TMP),
            "DB_PATH": str(TMP / "db" / "tracking.sqlite"),
            "SCHEMA_PATH": str(ROOT / "db" / "schema.sql"),
            "CONFIG_PATH": str(TMP / "config" / "settings.json"),
            "SCHEDULE_PATH": str(TMP / "config" / "schedule.json"),
            "PROMPTS_DIR": str(TMP / "config" / "prompts"),
            "SAMPLES_DIR": str(TMP / "samples"),
            "MEDIA_DIR": str(TMP / "media"),
            "PREVIEWS_DIR": str(TMP / "previews"),
            "LOGS_DIR": str(TMP / "logs"),
            "DRY_RUN": "true",
            "SCHEDULER_ENABLED": "false",
            "GITHUB_API_URL": f"http://127.0.0.1:{github.server_port}",
            "GITHUB_SYNC_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "N8N_INTERNAL_URL": "http://127.0.0.1:9",
        }
    )
    spec = importlib.util.spec_from_file_location("tracking_server", ROOT / "services" / "tracking-api" / "server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for folder in (module.MEDIA_DIR, module.PREVIEWS_DIR, module.LOGS_DIR, module.DB_PATH.parent):
        folder.mkdir(parents=True, exist_ok=True)
    module.init_db()
    return module


S = load_server()
IST = S.get_tz("Asia/Kolkata")
FILES = [{"name": n, "id": f"drive-{n}"} for n in ("1.jpg", "002.mp4", "003.mp4", "004.mp4", "005.mp4", "notes.txt")]
CONTENT = {p: {"caption": f"{p} caption", "title": "t", "description": "d"} for p in ("instagram", "facebook", "pinterest", "youtube")}


def prepare_with_ai(product_id: int, filename: str) -> None:
    """Simulate 16 Content Queue Preparer's Save Preview step."""
    media = S.MEDIA_DIR / filename
    media.write_bytes(b"x" * 128)
    S.save_preview({"product_id": product_id, "filename": filename, "media_type": "video", "drive_file_id": f"drive-{filename}", "local_path": f"/data/media/{filename}", "content": CONTENT, "queue": True})


def queue_ids(status: str | None = None) -> list[int]:
    with S.connect() as conn:
        if status:
            return [r[0] for r in conn.execute("SELECT product_id FROM content_queue WHERE status = ? ORDER BY product_id", (status,))]
        return S.active_queue_ids(conn)


def at(hh: int, mm: int, day_offset: int = 0) -> datetime:
    base = datetime.now(IST).date() + timedelta(days=day_offset)
    return datetime(base.year, base.month, base.day, hh, mm, tzinfo=IST)


def test_schedule() -> None:
    check("schedule defaults when file missing", S.load_schedule()["publish_time"] == "09:00" and S.load_schedule()["source"] == "defaults")
    S.write_schedule("18:30", "test")
    sched = S.load_schedule()
    check("schedule persists to config/schedule.json", json.loads(S.SCHEDULE_PATH.read_text())["publish_time"] == "18:30" and sched["source"] == "file")
    check("runtime config follows the schedule file", S.runtime_config()["publish_time"] == "18:30" and S.runtime_config()["daily_cron"] == "30 18 * * *")
    for bad in ("25:00", "9:00", "18:60", "", "noon"):
        try:
            S.write_schedule(bad, "test")
            check(f"reject invalid time {bad!r}", False)
        except ValueError:
            check(f"reject invalid time {bad!r}", True)
    check("invalid time did not overwrite the saved one", S.load_schedule()["publish_time"] == "18:30")
    check("not due before the slot", not S.publish_due(sched, None, at(18, 29)))
    check("due at the slot", S.publish_due(sched, None, at(18, 30)))
    check("due later the same day (catch-up after downtime)", S.publish_due(sched, None, at(23, 10)))
    today = at(12, 0).date().isoformat()
    check("only once per local day", not S.publish_due(sched, today, at(23, 10)))
    check("UTC clock is converted to Asia/Kolkata", S.publish_due(sched, None, datetime(at(0, 0).year, at(0, 0).month, at(0, 0).day, 13, 0, tzinfo=timezone.utc)))
    nxt = S.next_publish_run(sched, None, at(10, 0))
    check("next run is today's slot when still ahead", nxt["at"].startswith(at(18, 30).isoformat()[:16]) and not nxt["catch_up"], nxt)
    nxt = S.next_publish_run(sched, today, at(19, 0))
    check("next run moves to tomorrow after today's run", nxt["at"].startswith(at(18, 30, 1).isoformat()[:16]), nxt)
    S.write_schedule("07:05", "test")
    check("changing the time changes the next run without code changes", S.next_publish_run(S.load_schedule(), today, at(19, 0))["at"].startswith(at(7, 5, 1).isoformat()[:16]))


def test_schedule_save_rules() -> None:
    now = datetime.now(IST)
    if now.hour == 0 and now.minute < 2 or now.hour == 23 and now.minute > 56:
        print("SKIP save-rule timing test near midnight")
        return
    past = (now - timedelta(minutes=1)).strftime("%H:%M")
    future = (now + timedelta(minutes=2)).strftime("%H:%M")
    S.set_state("last_publish_trigger_date", None)
    result = S.save_schedule(past)
    check("saving a time that already passed skips today (no surprise post)", result["skipped_today"] and not S.publish_due(S.load_schedule(), S.handled_date()), result["next_run"])
    result = S.save_schedule(future)
    check("saving a later time today re-enables today's post", not result["skipped_today"] and not result["next_run"]["catch_up"], result["next_run"])
    check("schedule change is logged", any("schedule_changed" == r["event"] for r in S.connect().execute("SELECT event FROM logs")))


def test_github_sync() -> None:
    MockGitHub.puts.clear()
    S.write_schedule("20:15", "test")
    result = S.github_sync_schedule()
    pushed = json.loads(base64.b64decode(MockGitHub.puts[-1]["content"])) if MockGitHub.puts else {}
    check("GitHub sync pushes config/schedule.json", result["ok"] and pushed.get("publish_time") == "20:15", result)
    check("GitHub sync uses the token from env (never logged)", MockGitHub.auth and MockGitHub.auth[-1] == "Bearer test-token" and "test-token" not in json.dumps(S.get_state("github_sync")))
    before = len(MockGitHub.puts)
    result = S.github_sync_schedule()
    check("GitHub sync is idempotent when already in sync", result["ok"] and result.get("in_sync") and len(MockGitHub.puts) == before)
    S.write_schedule("06:45", "test")
    S.github_sync_schedule()
    check("GitHub sync updates with the previous sha", MockGitHub.puts[-1].get("sha") == "sha1" and json.loads(base64.b64decode(MockGitHub.puts[-1]["content"]))["publish_time"] == "06:45")
    os.environ["GITHUB_SYNC_TOKEN"] = ""
    check("GitHub sync reports not configured without a token", S.github_sync_schedule()["configured"] is False)
    os.environ["GITHUB_SYNC_TOKEN"] = "test-token"


def test_queue_dry_run() -> None:
    os.environ["DRY_RUN"] = "true"
    sel = S.select_to_prepare(FILES)
    check("preparer picks the lowest Product ID first", sel["found"] and sel["product_id"] == 1 and not sel["reused"], sel.get("product_id"))
    prepare_with_ai(1, "1.jpg")
    for expected, name in ((2, "002.mp4"), (3, "003.mp4")):
        sel = S.select_to_prepare(FILES)
        check(f"preparer continues sequentially with Product {expected}", sel.get("product_id") == expected, sel.get("product_id"))
        prepare_with_ai(expected, name)
    check("queue holds 3 prepared products", queue_ids() == [1, 2, 3], queue_ids())
    check("queue refuses a 4th product (rolling window of 3)", S.select_to_prepare(FILES)["reason_code"] == "queue_full")
    claim = S.claim_next()
    check("daily run claims the queue head", claim["found"] and claim["product_id"] == 1 and claim["content"] == CONTENT, claim.get("reason"))
    check("a second concurrent claim is refused", S.claim_next()["reason_code"] == "publish_in_progress")
    S.mark_processing(1)
    S.finalize_product(1)
    check("dry-run finalize advances the queue", queue_ids() == [2, 3] and queue_ids("done") == [1], queue_ids())
    sel = S.select_to_prepare(FILES)
    check("refill picks the next unprepared Product ID (4)", sel.get("product_id") == 4, sel.get("product_id"))
    prepare_with_ai(4, "004.mp4")
    (S.PREVIEWS_DIR / "5.json").write_text(json.dumps({"product_id": 5, "filename": "005.mp4", "content": CONTENT}))
    S.claim_next()
    S.mark_processing(2)
    S.finalize_product(2)
    sel = S.select_to_prepare(FILES)
    check("saved content is reused instead of calling AI again", sel.get("product_id") == 5 and sel.get("reused") is True, sel)
    check("queue is full again after reuse", queue_ids() == [3, 4, 5], queue_ids())


def test_queue_live() -> None:
    os.environ["DRY_RUN"] = "false"
    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET run_date = NULL")
        conn.commit()
    claim = S.claim_next()
    check("live: queue head (Product 3) claimed", claim.get("product_id") == 3, claim)
    S.mark_processing(3)
    for platform in ("instagram", "facebook", "youtube"):
        S.save_platform_result(3, platform, "published", f"{platform}-post-3", None)
    S.finalize_product(3)
    row = S.connect().execute("SELECT overall_status FROM products WHERE product_id = 3").fetchone()[0]
    check("live: product published and queue advanced", row == "published" and 3 in queue_ids("done"), row)
    blocked = S.claim_next()
    check("live: only one product per day", blocked["reason_code"] == "already_published_today" and blocked["product_id"] == 3, blocked)
    check("live: duplicate platform post blocked", S.can_publish(3, "instagram")["allowed"] is False)
    S.save_platform_result(3, "instagram", "failed", None, "late error")
    check("live: published result cannot be overwritten", S.connect().execute("SELECT instagram_status FROM products WHERE product_id = 3").fetchone()[0] == "published")

    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET run_date = '2000-01-01' WHERE product_id = 3")
        conn.commit()
    claim = S.claim_next()
    check("live: next day claims Product 4", claim.get("product_id") == 4, claim)
    S.mark_processing(4)
    S.save_platform_result(4, "instagram", "failed", None, "Graph API error")
    S.save_platform_result(4, "facebook", "published", "fb-4", None)
    S.save_platform_result(4, "youtube", "failed", None, "quota exceeded")
    S.finalize_product(4)
    q = S.connect().execute("SELECT status, last_error FROM content_queue WHERE product_id = 4").fetchone()
    check("live: failed publish returns product to the head of the queue", q[0] == "prepared" and "partial" in (q[1] or ""), tuple(q))
    retry = S.claim_next()
    check("live: retry keeps sequential order (Product 4 again)", retry.get("product_id") == 4, retry)
    check("live: platforms already published are not re-posted", S.can_publish(4, "facebook")["allowed"] is False and S.can_publish(4, "instagram")["allowed"] is True)
    S.save_platform_result(4, "instagram", "published", "ig-4", None)
    S.save_platform_result(4, "youtube", "published", "yt-4", None)
    S.finalize_product(4)

    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET run_date = '2000-01-01'")
        conn.execute("UPDATE products SET overall_status = 'published' WHERE product_id = 5")
        conn.commit()
    empty = S.claim_next()
    check("live: already-published product is dropped from the queue", empty["reason_code"] == "queue_empty" and 5 in queue_ids("done"), empty)

    with S.connect() as conn:
        conn.execute("UPDATE products SET overall_status = 'pending' WHERE product_id = 5")
        S.mark_prepared(conn, 5, reused=True)
        conn.commit()
    (S.MEDIA_DIR / "005.mp4").unlink(missing_ok=True)
    (S.PREVIEWS_DIR / "5.json").write_text(json.dumps({"product_id": 5, "filename": "005.mp4", "local_path": "/data/media/005.mp4", "content": CONTENT}))
    missing = S.claim_next()
    check("live: missing media blocks the claim instead of a broken post", missing["reason_code"] == "media_missing" and queue_ids("prepared") == [5], missing)

    (S.MEDIA_DIR / "005.mp4").write_bytes(b"x" * 128)
    S.claim_next()
    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET claimed_at = '2000-01-01T00:00:00+00:00' WHERE product_id = 5")
        S.reset_stale_claims(conn)
        conn.commit()
    check("stale publishing claim is returned to the queue", queue_ids("prepared") == [5])
    os.environ["DRY_RUN"] = "true"


def test_persistence() -> None:
    S.write_schedule("21:00", "test")
    S.set_state("last_publish_trigger_date", "2026-01-01")
    fresh = importlib.util.spec_from_file_location("tracking_server_reload", ROOT / "services" / "tracking-api" / "server.py")
    reloaded = importlib.util.module_from_spec(fresh)
    assert fresh.loader is not None
    fresh.loader.exec_module(reloaded)
    check("schedule survives a restart", reloaded.load_schedule()["publish_time"] == "21:00")
    check("scheduler state survives a restart", reloaded.get_state("last_publish_trigger_date") == "2026-01-01")
    check("queue survives a restart", reloaded.queue_snapshot()["active"][0]["product_id"] == 5)


class FakeN8n:
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.busy = False

    def run_workflow(self, workflow_id: str) -> str:
        self.runs.append(workflow_id)
        return str(len(self.runs))

    def running(self, workflow_id: str) -> bool:
        return self.busy

    def last_execution(self, workflow_id: str):
        return None


def test_scheduler() -> None:
    fake = FakeN8n()
    S.N8N = fake
    now = datetime.now(IST)
    if now.hour == 0 and now.minute < 2:
        print("SKIP scheduler timing test at midnight")
        return
    S.write_schedule((now - timedelta(minutes=1)).strftime("%H:%M"), "test")
    S.set_state("last_publish_trigger_date", None)
    S.set_state("publish_skip_date", None)
    fake.busy = True
    sched = S.Scheduler()
    sched.tick()
    check("scheduler fires the Daily Publisher once the slot is reached", fake.runs.count(S.DAILY_WORKFLOW_ID) == 1, fake.runs)
    sched.tick()
    check("scheduler does not fire twice on the same day", fake.runs.count(S.DAILY_WORKFLOW_ID) == 1, fake.runs)
    check("scheduler records the trigger", S.get_state("last_publish_trigger")["execution_id"] == "1")
    check("no queue refill while a workflow is running", S.PREPARER_WORKFLOW_ID not in fake.runs, fake.runs)
    with S.connect() as conn:
        conn.execute("DELETE FROM content_queue")
        conn.commit()
    fake.busy = False
    sched.tick()
    check("scheduler refills the queue when fewer than 3 are ready", fake.runs.count(S.PREPARER_WORKFLOW_ID) == 1, fake.runs)
    sched.tick()
    check("refill respects the cooldown", fake.runs.count(S.PREPARER_WORKFLOW_ID) == 1)
    check("scheduler heartbeat recorded", (S.get_state("scheduler_heartbeat") or {}).get("ok") is True)


def test_http() -> None:
    S.N8N = S.N8nSession()
    server = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path: str, body: dict, origin: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    status, _ = post("/schedule", {"publish_time": "10:10"}, origin="https://evil.example")
    check("cross-site schedule change is rejected", status == 403 and S.load_schedule()["publish_time"] != "10:10")
    status, body = post("/schedule", {"publish_time": "10:10"}, origin=base)
    check("dashboard can save the schedule", status == 200 and body["publish_time"] == "10:10", body)
    status, body = post("/schedule", {"publish_time": "99:99"}, origin=base)
    check("invalid schedule rejected with 400", status == 400)
    with urllib.request.urlopen(base + "/dashboard", timeout=20) as resp:
        html = resp.read().decode()
    check("dashboard page served", "Schedule settings" in html and 'type="time"' in html)
    with urllib.request.urlopen(base + "/dashboard/data", timeout=30) as resp:
        data = json.loads(resp.read())
    check("dashboard data includes schedule, queue and system status", {"schedule", "queue", "system", "products", "logs"} <= data.keys() and data["schedule"]["timezone"] == "Asia/Kolkata")
    check("dashboard degrades gracefully when n8n is down", data["system"]["n8n"] is False and data["system"]["database"] is True)
    server.shutdown()


def test_gate() -> None:
    spec = importlib.util.spec_from_file_location("schedule_gate", ROOT / "scripts" / "schedule_gate.py")
    gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(gate)
    sched = {"publish_time": "18:30", "timezone": "Asia/Kolkata"}
    day = datetime(2026, 10, 1, tzinfo=timezone.utc)
    check("gate: not due before the slot (12:59 UTC = 18:29 IST)", not gate.decide(sched, day.replace(hour=12, minute=59), False, "schedule")[0])
    check("gate: due at 13:00 UTC = 18:30 IST", gate.decide(sched, day.replace(hour=13), False, "schedule")[0])
    check("gate: due when GitHub delays the tick", gate.decide(sched, day.replace(hour=14, minute=40), False, "schedule")[0])
    check("gate: once per day (marker present)", not gate.decide(sched, day.replace(hour=15), True, "schedule")[0])
    check("gate: manual dispatch always runs", gate.decide(sched, day.replace(hour=1), True, "workflow_dispatch")[0])
    real = gate.load_schedule()
    check("gate reads the committed config/schedule.json", real["publish_time"] == json.loads((ROOT / "config" / "schedule.json").read_text())["publish_time"])


def main() -> int:
    try:
        for test in (test_schedule, test_schedule_save_rules, test_github_sync, test_queue_dry_run, test_queue_live, test_persistence, test_scheduler, test_http, test_gate):
            print(f"\n== {test.__name__} ==")
            test()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
