#!/usr/bin/env python3
"""GitHub Actions gate: run the daily job once per local day at/after the time in config/schedule.json.

GitHub cron cannot be rewritten by the default workflow token, so the workflow ticks every 15 minutes
and this gate decides. The dashboard is the only place the time is chosen.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "config" / "schedule.json"
DEFAULTS = {"publish_time": "09:00", "timezone": "Asia/Kolkata"}


def get_tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(hours=5, minutes=30)) if name == "Asia/Kolkata" else timezone.utc


def load_schedule(path: Path = SCHEDULE_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if v}}


def slot(schedule: dict, day: date) -> datetime:
    hour, minute = (int(p) for p in schedule["publish_time"].split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=get_tz(schedule["timezone"]))


def decide(schedule: dict, now: datetime, marker_exists: bool, event: str) -> tuple[bool, str]:
    if event != "schedule":
        return True, f"{event} event always runs the verification job"
    local = now.astimezone(get_tz(schedule["timezone"]))
    today_slot = slot(schedule, local.date())
    if local < today_slot:
        return False, f"before today's slot {today_slot.isoformat()}"
    if marker_exists:
        return False, f"already ran for {local.date().isoformat()}"
    return True, f"due: slot {today_slot.isoformat()} reached"


def marker_exists(key: str) -> bool:
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return False
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    req = urllib.request.Request(
        f"{api}/repos/{repo}/actions/caches?key={key}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            caches = json.loads(resp.read().decode("utf-8")).get("actions_caches", [])
    except urllib.error.HTTPError as exc:
        print(f"WARN: cache lookup failed ({exc.code}); treating as not yet run")
        return False
    return any(c.get("key") == key for c in caches)


def main() -> int:
    schedule = load_schedule()
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    now = datetime.now(timezone.utc)
    local_date = now.astimezone(get_tz(schedule["timezone"])).date().isoformat()
    key = f"daily-run-marker-{local_date}"
    exists = marker_exists(key) if event == "schedule" else False
    due, reason = decide(schedule, now, exists, event)
    lines = {
        "due": str(due).lower(),
        "local_date": local_date,
        "marker_key": key,
        "publish_time": schedule["publish_time"],
        "timezone": schedule["timezone"],
    }
    print(f"schedule {schedule['publish_time']} {schedule['timezone']} | event={event} | due={due} | {reason}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.writelines(f"{k}={v}\n" for k, v in lines.items())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"Daily publish time **{schedule['publish_time']} {schedule['timezone']}** · due: **{due}** — {reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
