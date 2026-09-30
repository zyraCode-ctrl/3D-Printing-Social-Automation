#!/usr/bin/env python3
"""GitHub Actions gate for production publishing.

GitHub cron cannot be rewritten by the default workflow token, so the production workflow ticks
every 10 minutes and this gate decides what (if anything) the heavy job should do:

- publish: one of today's slots from config/schedule.json has started and is not handled yet
- prepare: the content buffer is below target (refill; at most once an hour)
- validate: manual dispatch asking for a credential/queue check only

Slot bookkeeping (state/slots.json) and queue summary (state/queue.json) come from the
production-state branch, written at the end of every production run.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_PATH = ROOT / "config" / "schedule.json"
STATE_DIR = Path(os.environ.get("STATE_DIR", str(ROOT / "state")))
DEFAULT_TIMES = ["18:00", "22:00"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
REFILL_INTERVAL = timedelta(minutes=60)
# Must match SLOT_CATCHUP_MINUTES in the tracking-api: a slot missed by more than this is not posted late.
CATCHUP = timedelta(minutes=int(os.environ.get("SLOT_CATCHUP_MINUTES", "180")))


def get_tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(hours=5, minutes=30)) if name == "Asia/Kolkata" else timezone.utc


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_schedule(path: Path = SCHEDULE_PATH) -> dict:
    data = read_json(path)
    raw = data.get("publish_times") or ([data["publish_time"]] if data.get("publish_time") else DEFAULT_TIMES)
    times = sorted({str(t).strip() for t in raw if TIME_RE.match(str(t).strip())}) or DEFAULT_TIMES
    buffer_days = max(1, min(int(data.get("buffer_days") or 3), 7))
    return {
        "publish_times": times,
        "timezone": data.get("timezone") or "Asia/Kolkata",
        "start_date": data.get("start_date"),
        "skip_slots": [str(s) for s in data.get("skip_slots") or []],
        "queue_size": len(times) * (buffer_days + 1),
    }


def day_slots(schedule: dict, day: date) -> list[str]:
    if schedule.get("start_date") and day.isoformat() < schedule["start_date"]:
        return []
    return [f"{day.isoformat()}T{t}" for t in schedule["publish_times"]]


def due_slot(schedule: dict, handled: set[str], now: datetime) -> str | None:
    local = now.astimezone(get_tz(schedule["timezone"]))
    for key in day_slots(schedule, local.date()):
        hh, mm = (int(p) for p in key.split("T")[1].split(":"))
        start = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start <= local < start + CATCHUP and key not in handled:
            return key
    return None


def decide(schedule: dict, slots: dict, queue: dict, now: datetime, event: str, mode: str = "auto") -> dict:
    handled = set(slots.get("handled") or []) | set(schedule.get("skip_slots") or [])
    slot = due_slot(schedule, handled, now)
    ready = queue.get("ready")
    target = queue.get("queue_size") or schedule["queue_size"]
    if event == "workflow_dispatch" and mode == "validate-only":
        return {"run": True, "mode": "validate", "slot": "", "reason": "manual validation"}
    if event == "workflow_dispatch" and mode == "prepare-only":
        return {"run": True, "mode": "prepare", "slot": "", "reason": "manual refill"}
    if slot:
        return {"run": True, "mode": "publish", "slot": slot, "reason": f"slot {slot} is due"}
    if event == "workflow_dispatch":
        return {"run": True, "mode": "prepare", "slot": "", "reason": "manual run with no slot due: refill + dashboard refresh"}
    if ready is None or ready < target:
        last = queue.get("last_refill_at")
        try:
            recent = last and now - datetime.fromisoformat(last) < REFILL_INTERVAL
        except ValueError:
            recent = False
        if not recent:
            return {"run": True, "mode": "prepare", "slot": "", "reason": f"buffer {ready}/{target} below target"}
        return {"run": False, "mode": "none", "slot": "", "reason": f"buffer {ready}/{target}; refilled recently, waiting"}
    return {"run": False, "mode": "none", "slot": "", "reason": f"no slot due; buffer {ready}/{target} full"}


def main() -> int:
    schedule = load_schedule()
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    mode = os.environ.get("GATE_MODE", "auto") or "auto"
    slots = read_json(STATE_DIR / "slots.json")
    queue = read_json(STATE_DIR / "queue.json")
    result = decide(schedule, slots, queue, datetime.now(timezone.utc), event, mode)
    times = ", ".join(schedule["publish_times"])
    print(f"schedule {times} {schedule['timezone']} (from {schedule.get('start_date') or 'now'}) | event={event} | {result}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"run={str(result['run']).lower()}\nmode={result['mode']}\nslot={result['slot']}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"Publishing times **{times} {schedule['timezone']}** · decision: **{result['mode']}** — {result['reason']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
