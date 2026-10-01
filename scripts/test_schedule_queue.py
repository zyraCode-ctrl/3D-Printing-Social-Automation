#!/usr/bin/env python3
"""Offline tests for the multi-slot schedule, rolling queue, duplicate prevention and GitHub sync.

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
FILES = [{"name": n, "id": f"drive-{n}"} for n in ("1.jpg", "002.mp4", "003.mp4", "004.mp4", "005.mp4", "006.mp4", "notes.txt")]
CONTENT = {p: {"caption": f"{p} caption", "title": "t", "description": "d"} for p in ("instagram", "facebook", "pinterest", "youtube")}


def write_schedule_file(**doc: object) -> None:
    S.SCHEDULE_PATH.write_text(json.dumps(doc), encoding="utf-8")


def prepare_with_ai(product_id: int, filename: str) -> None:
    """Simulate 16 Content Queue Preparer's Save Preview step."""
    (S.MEDIA_DIR / filename).write_bytes(b"x" * 128)
    S.save_preview({"product_id": product_id, "filename": filename, "media_type": "video", "drive_file_id": f"drive-{filename}", "local_path": f"/data/media/{filename}", "content": CONTENT, "queue": True})


def queue_ids(status: str | None = None) -> list[int]:
    with S.connect() as conn:
        if status:
            return [r[0] for r in conn.execute("SELECT product_id FROM content_queue WHERE status = ? ORDER BY product_id", (status,))]
        return S.active_queue_ids(conn)


def handled() -> set[str]:
    with S.connect() as conn:
        return S.handled_slots(conn)


def at(hh: int, mm: int, day_offset: int = 0) -> datetime:
    base = datetime.now(IST).date() + timedelta(days=day_offset)
    return datetime(base.year, base.month, base.day, hh, mm, tzinfo=IST)


def publish_all(product_id: int) -> None:
    S.mark_processing(product_id)
    for platform in ("instagram", "facebook", "youtube"):
        S.save_platform_result(product_id, platform, "published", f"{platform}-post-{product_id}", None)
    S.finalize_product(product_id)


def new_day() -> None:
    """Simulate the next local day: today's slot bookkeeping no longer applies."""
    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET run_slot = NULL")
        conn.commit()
    S.set_state("slot_attempts", {})
    S.set_state("skipped_slots", [])


def test_schedule() -> None:
    sched = S.load_schedule()
    check("defaults: 6 PM + 10 PM IST, 3-day buffer", sched["publish_times"] == ["18:00", "22:00"] and sched["timezone"] == "Asia/Kolkata" and sched["source"] == "defaults")
    check("buffer target = tomorrow's 2 + 3 days x 2 = 8, minimum 6", sched["queue_size"] == 8 and sched["min_buffer"] == 6, sched)
    S.write_schedule(["22:00", "18:30", "18:30"], "test")
    saved = json.loads(S.SCHEDULE_PATH.read_text())
    check("times persist sorted and de-duplicated in config/schedule.json", saved["publish_times"] == ["18:30", "22:00"] and S.load_schedule()["source"] == "file", saved)
    check("runtime config follows the schedule file", S.runtime_config()["publish_times"] == ["18:30", "22:00"])
    for bad in (["25:00"], ["9:00"], ["18:60"], [], "noon", [f"0{i}:00" for i in range(7)]):
        try:
            S.write_schedule(bad, "test")
            check(f"reject invalid times {bad!r}", False)
        except ValueError:
            check(f"reject invalid times {bad!r}", True)
    check("invalid input did not overwrite the saved times", S.load_schedule()["publish_times"] == ["18:30", "22:00"])
    write_schedule_file(publish_time="09:00")
    check("legacy single publish_time file still loads", S.load_schedule()["publish_times"] == ["09:00"])

    write_schedule_file(publish_times=["18:00", "22:00"], buffer_days=3)
    sched = S.load_schedule()
    today = at(0, 0).date().isoformat()
    check("no slot due before 6 PM", S.due_slot(sched, set(), at(17, 59)) is None)
    check("6 PM slot due at 18:00", S.due_slot(sched, set(), at(18, 0)) == f"{today}T18:00")
    check("nothing due between slots once 6 PM is handled", S.due_slot(sched, {f"{today}T18:00"}, at(21, 0)) is None)
    check("10 PM slot due at 22:05", S.due_slot(sched, {f"{today}T18:00"}, at(22, 5)) == f"{today}T22:00")
    check("late 6 PM slot is caught up within the window", S.due_slot(sched, set(), at(20, 30)) == f"{today}T18:00")
    check("a slot missed by more than 3 hours is not posted late", S.due_slot(sched, set(), at(23, 0)) == f"{today}T22:00")
    utc = at(18, 0).astimezone(timezone.utc)
    check("UTC clock is converted to Asia/Kolkata", S.due_slot(sched, set(), utc) == f"{today}T18:00")
    upcoming = S.upcoming_slots(sched, set(), 8, at(19, 0))
    keys = [u["slot"] for u in upcoming]
    check("upcoming: overdue 6 PM first, then 10 PM, then 2 per day", keys[:3] == [f"{today}T18:00", f"{today}T22:00", f"{at(0, 0, 1).date()}T18:00"] and len(set(keys)) == 8, keys)

    tomorrow = at(0, 0, 1).date().isoformat()
    write_schedule_file(publish_times=["18:00", "22:00"], buffer_days=3, start_date=tomorrow)
    sched = S.load_schedule()
    check("start_date: nothing publishes today", S.due_slot(sched, set(), at(22, 30)) is None)
    check("start_date: first upcoming slot is tomorrow 6 PM", S.upcoming_slots(sched, set(), 1, at(12, 0))[0]["slot"] == f"{tomorrow}T18:00")


def test_schedule_save_rules() -> None:
    now = datetime.now(IST)
    if now.hour == 0 and now.minute < 3 or now.hour == 23 and now.minute > 56:
        print("SKIP save-rule timing test near midnight")
        return
    write_schedule_file(publish_times=["23:59"], buffer_days=3)
    past = (now - timedelta(minutes=1)).strftime("%H:%M")
    future = (now + timedelta(minutes=2)).strftime("%H:%M")
    result = S.save_schedule([past, "23:59"])
    check("a newly added time that already passed today is skipped (no surprise post)", result["due_slot"] is None and f"{now.date()}T{past}" in handled(), result["due_slot"])
    check("the skip is saved in config/schedule.json so GitHub Actions honours it", f"{now.date()}T{past}" in json.loads(S.SCHEDULE_PATH.read_text())["skip_slots"])
    result = S.save_schedule([future, "23:59"])
    check("a later time today becomes the next run", result["next_run"]["slot"] == f"{now.date()}T{future}", result["next_run"])
    check("schedule change is logged", any("schedule_changed" == r["event"] for r in S.connect().execute("SELECT event FROM logs")))


def test_github_sync() -> None:
    MockGitHub.puts.clear()
    S.write_schedule(["18:00", "22:00"], "test")
    result = S.github_sync_schedule()
    pushed = json.loads(base64.b64decode(MockGitHub.puts[-1]["content"])) if MockGitHub.puts else {}
    check("GitHub sync pushes config/schedule.json", result["ok"] and pushed.get("publish_times") == ["18:00", "22:00"], result)
    check("GitHub sync uses the token from env (never logged)", MockGitHub.auth and MockGitHub.auth[-1] == "Bearer test-token" and "test-token" not in json.dumps(S.get_state("github_sync")))
    before = len(MockGitHub.puts)
    result = S.github_sync_schedule()
    check("GitHub sync is idempotent when already in sync", result["ok"] and result.get("in_sync") and len(MockGitHub.puts) == before)
    S.write_schedule(["19:00", "21:30"], "test")
    S.github_sync_schedule()
    check("GitHub sync updates with the previous sha", MockGitHub.puts[-1].get("sha") == "sha1" and json.loads(base64.b64decode(MockGitHub.puts[-1]["content"]))["publish_times"] == ["19:00", "21:30"])
    os.environ["GITHUB_SYNC_TOKEN"] = ""
    check("GitHub sync reports not configured without a token", S.github_sync_schedule()["configured"] is False)
    os.environ["GITHUB_SYNC_TOKEN"] = "test-token"


def test_queue_dry_run() -> None:
    os.environ["DRY_RUN"] = "true"
    write_schedule_file(publish_times=["10:00"], buffer_days=2, start_date="2099-01-01")
    check("queue target follows posts/day x (buffer days + 1)", S.load_schedule()["queue_size"] == 3)
    sel = S.select_to_prepare(FILES)
    check("preparer picks the lowest Product ID first", sel["found"] and sel["product_id"] == 1 and not sel["reused"], sel.get("product_id"))
    prepare_with_ai(1, "1.jpg")
    for expected, name in ((2, "002.mp4"), (3, "003.mp4")):
        sel = S.select_to_prepare(FILES)
        check(f"preparer continues sequentially with Product {expected}", sel.get("product_id") == expected, sel.get("product_id"))
        prepare_with_ai(expected, name)
    check("queue holds 3 prepared products", queue_ids() == [1, 2, 3], queue_ids())
    check("queue refuses a 4th product at the target", S.select_to_prepare(FILES)["reason_code"] == "queue_full")
    claim = S.claim_next()
    check("dry run claims the queue head", claim["found"] and claim["product_id"] == 1 and claim["content"] == CONTENT, claim.get("reason"))
    check("a second concurrent claim is refused", S.claim_next()["reason_code"] == "publish_in_progress")
    S.mark_processing(1)
    S.finalize_product(1)
    check("finalize advances the queue", queue_ids() == [2, 3] and queue_ids("done") == [1], queue_ids())
    sel = S.select_to_prepare(FILES)
    check("refill picks the next unprepared Product ID (4)", sel.get("product_id") == 4, sel.get("product_id"))
    prepare_with_ai(4, "004.mp4")
    (S.PREVIEWS_DIR / "5.json").write_text(json.dumps({"product_id": 5, "filename": "005.mp4", "local_path": "/data/media/005.mp4", "content": CONTENT}))
    S.claim_next()
    S.mark_processing(2)
    S.finalize_product(2)
    sel = S.select_to_prepare(FILES)
    check("saved content is reused instead of calling AI again", sel.get("product_id") == 5 and sel.get("reused") is True, sel)
    check("queue is full again after reuse", queue_ids() == [3, 4, 5], queue_ids())
    snap = S.queue_snapshot()
    check("snapshot maps queued products onto upcoming slots", [p["product"]["product_id"] for p in snap["planned"][:3]] == [3, 4, 5] and snap["planned"][0]["slot"] == "2099-01-01T10:00", snap["planned"][:2])


def test_queue_live() -> None:
    now = datetime.now(IST)
    if now.hour == 0 and now.minute < 5:
        print("SKIP live slot test just after midnight")
        return
    os.environ["DRY_RUN"] = "false"
    first, second = ((now - timedelta(minutes=m)).strftime("%H:%M") for m in (3, 2))
    write_schedule_file(publish_times=[first, second], buffer_days=1)
    today = now.date().isoformat()
    claim = S.claim_next()
    check("live: first due slot claims the queue head (Product 3)", claim.get("product_id") == 3 and claim.get("slot") == f"{today}T{first}", claim)
    publish_all(3)
    row = S.connect().execute("SELECT q.status, q.run_slot, p.overall_status FROM content_queue q JOIN products p USING (product_id) WHERE product_id = 3").fetchone()
    check("live: published product leaves the queue and consumes its slot", tuple(row) == ("done", f"{today}T{first}", "published"), tuple(row))

    claim = S.claim_next()
    check("live: second slot takes the next product (Product 4)", claim.get("product_id") == 4 and claim.get("slot") == f"{today}T{second}", claim)
    S.mark_processing(4)
    S.save_platform_result(4, "instagram", "failed", None, "Graph API error")
    S.save_platform_result(4, "facebook", "published", "fb-4", None)
    S.save_platform_result(4, "youtube", "failed", None, "quota exceeded")
    S.finalize_product(4)
    q = S.connect().execute("SELECT status, run_slot, last_error FROM content_queue WHERE product_id = 4").fetchone()
    check("live: partial publish returns the product to the head and frees the slot for a retry", q[0] == "prepared" and q[1] is None and "partial" in (q[2] or ""), tuple(q))
    retry = S.claim_next()
    check("live: retry keeps sequential order (Product 4, same slot)", retry.get("product_id") == 4 and retry.get("slot") == f"{today}T{second}", retry)
    check("live: platforms already published are not re-posted", S.can_publish(4, "facebook")["allowed"] is False and S.can_publish(4, "instagram")["allowed"] is True)
    S.save_platform_result(4, "instagram", "published", "ig-4", None)
    S.save_platform_result(4, "youtube", "published", "yt-4", None)
    S.finalize_product(4)
    blocked = S.claim_next()
    check("live: no extra posts once both slots are handled", blocked["reason_code"] == "no_slot_due" and queue_ids("prepared") == [5], blocked)
    check("live: duplicate platform post blocked", S.can_publish(3, "instagram")["allowed"] is False)
    S.save_platform_result(3, "instagram", "failed", None, "late error")
    check("live: published result cannot be overwritten", S.connect().execute("SELECT instagram_status FROM products WHERE product_id = 3").fetchone()[0] == "published")

    new_day()
    (S.MEDIA_DIR / "005.mp4").write_bytes(b"x" * 128)
    for attempt in range(1, S.MAX_PRODUCT_ATTEMPTS + 1):
        claim = S.claim_next()
        check(f"live: attempt {attempt} claims Product 5", claim.get("found") and claim.get("product_id") == 5, claim)
        S.mark_processing(5)
        for platform in ("instagram", "facebook", "youtube"):
            S.save_platform_result(5, platform, "failed", None, "down")
        S.finalize_product(5)
    q = S.connect().execute("SELECT status, last_error FROM content_queue WHERE product_id = 5").fetchone()
    check("live: gives up after max attempts so the queue never stalls", q[0] == "done" and "Gave up" in (q[1] or ""), tuple(q))
    check("live: slot is consumed by the given-up product (no extra post)", f"{today}T{first}" in handled())

    new_day()
    sel = S.select_to_prepare(FILES)
    check("live: dry-run content is reused for production (Product 1)", sel.get("product_id") == 1 and sel.get("reused") is True, sel)
    with S.connect() as conn:
        conn.execute("UPDATE products SET overall_status = 'published' WHERE product_id IN (1, 2)")
        conn.commit()
    empty = S.claim_next()
    check("live: already-published product is dropped from the queue", empty["reason_code"] == "queue_empty" and 1 in queue_ids("done"), empty)
    check("live: given-up Product 5 is not retried; preparer moves on to Product 6", S.select_to_prepare(FILES).get("product_id") == 6)
    prepare_with_ai(6, "006.mp4")

    with S.connect() as conn:
        conn.execute("UPDATE products SET overall_status = 'pending' WHERE product_id = 6")
        S.mark_prepared(conn, 6, reused=True)
        conn.commit()
    (S.MEDIA_DIR / "006.mp4").unlink(missing_ok=True)
    (S.PREVIEWS_DIR / "6.json").write_text(json.dumps({"product_id": 6, "filename": "006.mp4", "local_path": "/data/media/006.mp4", "content": CONTENT}))
    missing = S.claim_next()
    check("live: missing media blocks the claim instead of a broken post", missing["reason_code"] == "media_missing" and queue_ids("prepared") == [6], missing)

    (S.MEDIA_DIR / "006.mp4").write_bytes(b"x" * 128)
    S.claim_next()
    with S.connect() as conn:
        conn.execute("UPDATE content_queue SET claimed_at = '2000-01-01T00:00:00+00:00' WHERE product_id = 6")
        S.reset_stale_claims(conn)
        conn.commit()
    check("stale publishing claim is returned to the queue", queue_ids("prepared") == [6])
    os.environ["DRY_RUN"] = "true"


def test_persistence() -> None:
    S.write_schedule(["18:00", "22:00"], "test")
    S.set_state("slot_attempts", {"2026-01-01T18:00": 1})
    fresh = importlib.util.spec_from_file_location("tracking_server_reload", ROOT / "services" / "tracking-api" / "server.py")
    reloaded = importlib.util.module_from_spec(fresh)
    assert fresh.loader is not None
    fresh.loader.exec_module(reloaded)
    check("schedule survives a restart", reloaded.load_schedule()["publish_times"] == ["18:00", "22:00"])
    check("slot bookkeeping survives a restart", reloaded.get_state("slot_attempts") == {"2026-01-01T18:00": 1})
    check("queue survives a restart", reloaded.queue_snapshot()["active"][0]["product_id"] == 6)
    state = reloaded.slot_state()
    check("slot state export for the GitHub gate", {"handled", "attempts", "due_slot"} <= state.keys())


class FakeN8n:
    def __init__(self) -> None:
        self.runs: list[str] = []
        self.busy: set[str] = set()

    def run_workflow(self, workflow_id: str) -> str:
        self.runs.append(workflow_id)
        return str(len(self.runs))

    def running(self, workflow_id: str) -> bool:
        return workflow_id in self.busy

    def last_execution(self, workflow_id: str):
        return None


def test_scheduler() -> None:
    fake = FakeN8n()
    S.N8N = fake
    now = datetime.now(IST)
    if now.hour == 0 and now.minute < 2:
        print("SKIP scheduler timing test at midnight")
        return
    new_day()
    write_schedule_file(publish_times=[(now - timedelta(minutes=1)).strftime("%H:%M")], buffer_days=1)
    fake.busy = {S.PREPARER_WORKFLOW_ID}
    sched = S.Scheduler()
    sched.tick()
    check("scheduler fires the Daily Publisher once a slot is due", fake.runs.count(S.DAILY_WORKFLOW_ID) == 1, fake.runs)
    sched.tick()
    check("scheduler does not re-fire the same slot within the retry window", fake.runs.count(S.DAILY_WORKFLOW_ID) == 1, fake.runs)
    check("scheduler records the trigger with its slot", (S.get_state("last_publish_trigger") or {}).get("slot", "").endswith((now - timedelta(minutes=1)).strftime("%H:%M")))
    check("no queue refill while the preparer is running", S.PREPARER_WORKFLOW_ID not in fake.runs, fake.runs)
    with S.connect() as conn:
        conn.execute("DELETE FROM content_queue")
        conn.commit()
    fake.busy = set()
    sched.tick()
    check("scheduler refills the queue when below target", fake.runs.count(S.PREPARER_WORKFLOW_ID) == 1, fake.runs)
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

    status, _ = post("/schedule", {"publish_times": ["10:10"]}, origin="https://evil.example")
    check("cross-site schedule change is rejected", status == 403 and S.load_schedule()["publish_times"] != ["10:10"])
    status, body = post("/schedule", {"publish_times": ["22:00", "18:00"]}, origin=base)
    check("dashboard can save both daily times", status == 200 and body["publish_times"] == ["18:00", "22:00"], body)
    status, body = post("/schedule", {"publish_times": ["99:99"]}, origin=base)
    check("invalid schedule rejected with 400", status == 400)
    with urllib.request.urlopen(base + "/dashboard", timeout=20) as resp:
        html = resp.read().decode()
    check("dashboard page served", "Schedule settings" in html and 'type="time"' in html)
    with urllib.request.urlopen(base + "/dashboard/data", timeout=30) as resp:
        data = json.loads(resp.read())
    check("dashboard data includes schedule, queue and system status", {"schedule", "queue", "system", "products", "logs"} <= data.keys() and data["schedule"]["timezone"] == "Asia/Kolkata")
    check("dashboard data lists upcoming slots and today's posts", "upcoming" in data["schedule"] and "today_posts" in data["queue"] and "planned" in data["queue"])
    check("dashboard degrades gracefully when n8n is down", data["system"]["n8n"] is False and data["system"]["database"] is True)
    with urllib.request.urlopen(base + "/schedule/slots", timeout=20) as resp:
        check("slot state endpoint", "handled" in json.loads(resp.read()))
    server.shutdown()


def test_gate() -> None:
    spec = importlib.util.spec_from_file_location("schedule_gate", ROOT / "scripts" / "schedule_gate.py")
    gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(gate)
    sched = {"publish_times": ["18:00", "22:00"], "timezone": "Asia/Kolkata", "start_date": "2026-10-02", "queue_size": 8}
    full = {"ready": 8, "queue_size": 8}
    oct1 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    oct2 = datetime(2026, 10, 2, tzinfo=timezone.utc)
    check("gate: nothing on the day before start_date", gate.decide(sched, {}, full, oct1.replace(hour=16, minute=40), "schedule")["run"] is False)
    check("gate: not due before 6 PM IST (12:29 UTC)", gate.decide(sched, {}, full, oct2.replace(hour=12, minute=29), "schedule")["run"] is False)
    d = gate.decide(sched, {}, full, oct2.replace(hour=12, minute=30), "schedule")
    check("gate: 12:30 UTC = 6 PM IST publishes the 6 PM slot", d["mode"] == "publish" and d["slot"] == "2026-10-02T18:00", d)
    d = gate.decide({**sched, "skip_slots": ["2026-10-02T18:00"]}, {}, full, oct2.replace(hour=12, minute=35), "schedule")
    check("gate: slots listed in schedule.json skip_slots never publish", d["run"] is False, d)
    d = gate.decide(sched, {"handled": ["2026-10-02T18:00"]}, full, oct2.replace(hour=15), "schedule")
    check("gate: handled slot is not published again", d["run"] is False, d)
    d = gate.decide(sched, {"handled": ["2026-10-02T18:00"]}, full, oct2.replace(hour=16, minute=35), "schedule")
    check("gate: 10 PM slot when GitHub delays the tick", d["mode"] == "publish" and d["slot"] == "2026-10-02T22:00", d)
    d = gate.decide(sched, {"handled": ["2026-10-02T18:00", "2026-10-02T22:00"]}, {"ready": 5, "queue_size": 8}, oct2.replace(hour=17), "schedule")
    check("gate: refill when the buffer is below target", d["mode"] == "prepare", d)
    d = gate.decide(sched, {}, full, oct2.replace(hour=16, minute=0), "schedule")
    check("gate: a 6 PM slot missed by 3.5 h is not posted late", d["run"] is False, d)
    recent = {"ready": 5, "queue_size": 8, "last_refill_at": oct2.replace(hour=16, minute=40).isoformat()}
    check("gate: refill waits an hour after the last attempt", gate.decide(sched, {"handled": ["2026-10-02T18:00", "2026-10-02T22:00"]}, recent, oct2.replace(hour=17), "schedule")["run"] is False)
    check("gate: manual validate-only", gate.decide(sched, {}, full, oct1, "workflow_dispatch", "validate-only")["mode"] == "validate")
    check("gate: manual dispatch never publishes outside a slot", gate.decide(sched, {}, full, oct1, "workflow_dispatch")["mode"] == "prepare")
    d = gate.decide(sched, {}, full, oct2.replace(hour=12, minute=32), "workflow_dispatch", "tick")
    check("gate: waiter tick publishes a due slot", d["mode"] == "publish" and d["slot"] == "2026-10-02T18:00", d)
    check("gate: waiter tick outside a slot does nothing (no heavy run)", gate.decide(sched, {}, full, oct2.replace(hour=10), "workflow_dispatch", "tick")["run"] is False)
    d = gate.decide(sched, {"handled": ["2026-10-02T18:00"]}, full, oct2.replace(hour=13, minute=5), "workflow_dispatch", "tick")
    check("gate: waiter retry after a handled slot is a no-op", d["run"] is False, d)

    w = gate.next_wake(sched, oct1.replace(hour=8, minute=35))
    check("waiter: today (before start_date) re-arms instead of waking for a slot", w["reason"].startswith("re-arm") and w["seconds"] <= 350 * 60, w)
    w = gate.next_wake(sched, oct2.replace(hour=7, minute=5))
    check("waiter: wakes 90 s after 6 PM IST", w["wake_at"] == "2026-10-02T18:01:30+05:30" and w["reason"] == "slot 2026-10-02T18:00", w)
    w = gate.next_wake(sched, oct2.replace(hour=12, minute=32))
    check("waiter: retry wake inside the catch-up window", w["wake_at"] == "2026-10-02T18:35:00+05:30", w)
    w = gate.next_wake(sched, oct2.replace(hour=13, minute=51))
    check("waiter: then wakes for 10 PM IST", w["wake_at"] == "2026-10-02T22:01:30+05:30", w)
    w = gate.next_wake(sched, oct2.replace(hour=17, minute=51))
    check("waiter: after 10 PM retries, re-arms toward tomorrow 6 PM", w["reason"].startswith("re-arm"), w)
    w = gate.next_wake({**sched, "skip_slots": ["2026-10-02T18:00"]}, oct2.replace(hour=12))
    check("waiter: skipped slots are not woken for", w["reason"] == "slot 2026-10-02T22:00", w)
    gaps = []
    t = oct1.replace(hour=0)
    while t < datetime(2026, 10, 4, tzinfo=timezone.utc):
        w = gate.next_wake(sched, t)
        gaps.append(w["seconds"])
        t = datetime.fromisoformat(w["wake_at"]).astimezone(timezone.utc)
    woke = set()
    t = oct1.replace(hour=0)
    while t < datetime(2026, 10, 4, tzinfo=timezone.utc):
        w = gate.next_wake(sched, t)
        t = datetime.fromisoformat(w["wake_at"]).astimezone(timezone.utc)
        if gate.due_slot(sched, set(), t):
            woke.add(gate.due_slot(sched, set(), t))
    check("waiter chain never sleeps past the 6-hour job limit", max(gaps) <= 350 * 60, max(gaps))
    check("waiter chain wakes inside every slot's window", {"2026-10-02T18:00", "2026-10-02T22:00", "2026-10-03T18:00", "2026-10-03T22:00"} <= woke, sorted(woke))
    real = gate.load_schedule()
    check("gate reads the committed config/schedule.json", real["publish_times"] == json.loads((ROOT / "config" / "schedule.json").read_text())["publish_times"])


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
