#!/usr/bin/env python3
"""Production operations against a running stack (GitHub Actions or local).

  validate [--strict] [--expect-live]  read-only checks: credentials, Page/IG ids, Pinterest board,
           [--deep]                    YouTube OAuth, Groq fallback, duplicate prevention, queue, schedule;
                                       --deep also uploads the queue head to IG/FB without publishing
  publish                              run 01 Daily Publisher for the due slot (no-op when none is due)
  refill [--max N]                     run 16 Content Queue Preparer until the buffer target is reached
  export --out DIR                     write state/slots.json, state/queue.json and site/data.json

Never prints tokens: probe summaries only contain ids, names and booleans.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402

TRACKING = os.environ.get("TRACKING_API_URL", "http://127.0.0.1:8081")
EXPECTED_PAGE_ID = os.environ.get("EXPECTED_PAGE_ID", "1294584743741605")
DAILY = "3dprDailyPub0001"
PREPARER = "3dprQueuePrep016"
PATH_CHECK = "3dprPathCheck017"
META_REQUIRED_SCOPES = ("pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic", "instagram_content_publish")
META_TOKEN_MIN_DAYS = float(os.environ.get("META_TOKEN_MIN_DAYS", "7"))
META_TOKEN_WARN_DAYS = float(os.environ.get("META_TOKEN_WARN_DAYS", "14"))
PROBES = {
    "meta": "3dprMetaAuthProbe09",
    "youtube": "3dprYtAuthProbe10",
    "pinterest": "3dprPinAuthProbe11",
    "groq": "3dprGroqAuthProbe12",
}


SECRET_PATTERNS = [
    re.compile(r"(access_token|client_secret|refresh_token|api_key|key)=([^&\s\"'\\]+)", re.I),
    re.compile(r"(Bearer|OAuth)\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\b(EAA[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9._\-]+|gsk_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|pina_[A-Za-z0-9]{20,})"),
]


def redact(text: str) -> str:
    """The dashboard data is published on GitHub Pages: strip anything token-shaped from error text."""
    text = SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)} [redacted]", text)
    return SECRET_PATTERNS[2].sub("[redacted]", text)


def tracking(method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(TRACKING + path, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "body": exc.read().decode("utf-8", "replace")[:300]}


def resolve_flat(arr: list, x, depth: int = 0):
    if depth > 80:
        return x
    if isinstance(x, str) and x.isdigit() and int(x) < len(arr):
        return resolve_flat(arr, arr[int(x)], depth + 1)
    if isinstance(x, list):
        return [resolve_flat(arr, v, depth + 1) for v in x]
    if isinstance(x, dict):
        return {k: resolve_flat(arr, v, depth + 1) for k, v in x.items()}
    return x


class Stack:
    def __init__(self) -> None:
        env = load_env()
        self.client = N8n(f"http://127.0.0.1:{env.get('N8N_PORT', '5678')}")
        email = env.get("N8N_OWNER_EMAIL", "admin@localhost.local")
        password = env.get("N8N_OWNER_PASSWORD", "")
        for _ in range(30):
            for body in ({"emailOrLdapLoginId": email, "password": password}, {"email": email, "password": password}):
                status, _resp = self.client.json("POST", "/rest/login", body)
                if status in {200, 201}:
                    return
            time.sleep(2)
        raise SystemExit("n8n login failed")

    def run(self, workflow_id: str, timeout: int = 1500) -> tuple[str, dict]:
        """Start a workflow via its manual trigger and wait; returns (status, runData)."""
        status, body = self.client.json("POST", f"/rest/workflows/{workflow_id}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
        data = body.get("data", body) if isinstance(body, dict) else {}
        execution_id = (data or {}).get("executionId")
        if status not in {200, 201} or not execution_id:
            return "not_started", {"error": str(body)[:300]}
        deadline = time.time() + timeout
        while time.time() < deadline:
            _st, detail = self.client.json("GET", f"/rest/executions/{execution_id}?includeData=true")
            d = detail.get("data", detail) if isinstance(detail, dict) else {}
            if d.get("status") in {"success", "error", "crashed", "canceled"}:
                arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
                root = resolve_flat(arr, arr[0]) if isinstance(arr, list) and arr else {}
                run_data = ((root or {}).get("resultData") or {}).get("runData") or {}
                return d["status"], run_data
            time.sleep(3)
        return "timeout", {}


def node_json(run_data: dict, name: str) -> dict:
    runs = run_data.get(name) or []
    for run in reversed(runs if isinstance(runs, list) else [runs]):
        main = (((run or {}).get("data") or {}).get("main") or [[]])
        for branch in main:
            if branch:
                return branch[0].get("json") or {}
        if (run or {}).get("error"):
            err = run["error"]
            return {"node_error": str(err.get("message") if isinstance(err, dict) else err)[:300]}
    return {}


def meta_token_checks(debug: dict, page_id: str, now: float) -> list[dict]:
    """Checks on the Page token the publishers derive from the configured credential (debug_token metadata).
    expires_at 0 means the Page token does not expire; data_access_expires_at still requires re-consent."""
    debug = debug or {}
    scopes = set(debug.get("scopes") or [])
    missing = sorted(set(META_REQUIRED_SCOPES) - scopes)
    limits = [t for t in (debug.get("expires_at"), debug.get("data_access_expires_at")) if t]
    effective = min(limits) if limits else None
    remaining_days = None if effective is None else (effective - now) / 86400
    when = "never" if effective is None else datetime.fromtimestamp(effective, timezone.utc).isoformat(timespec="minutes")
    is_page = debug.get("valid") is True and debug.get("type") == "PAGE" and str(debug.get("profile_id")) == str(page_id)
    return [
        {
            "check": "Meta: credential yields a valid Page access token for the configured Page",
            "ok": is_page,
            "detail": f"valid={debug.get('valid')} type={debug.get('type')} profile_id={debug.get('profile_id')} expected={page_id} error={debug.get('error')}",
        },
        {
            "check": "Meta: required Facebook/Instagram permissions granted",
            "ok": not missing and bool(scopes),
            "detail": f"missing={missing}",
        },
        {
            "check": f"Meta: token lifetime at least {META_TOKEN_MIN_DAYS} days",
            "ok": remaining_days is None or remaining_days >= META_TOKEN_MIN_DAYS,
            "detail": f"expires={when} remaining_days={None if remaining_days is None else round(remaining_days, 1)} (expires_at={debug.get('expires_at')}, data_access_expires_at={debug.get('data_access_expires_at')})",
        },
        {
            "check": f"Meta: token renewal not due within {META_TOKEN_WARN_DAYS} days",
            "ok": remaining_days is None or remaining_days >= META_TOKEN_WARN_DAYS,
            "detail": f"expires={when}",
            "advisory": True,
        },
    ]


def validate(strict: bool, expect_live: bool | None, preflight: bool = False, deep: bool = False) -> dict:
    """Full validation; with preflight=True only safety-critical checks block a publish run
    (a YouTube/Pinterest/AI hiccup must not stop Instagram + Facebook — those platforms fail on their own)."""
    stack = Stack()
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, blocking: bool = True, critical: bool = False) -> None:
        blocks = critical if preflight else (blocking or strict)
        checks.append({"check": name, "ok": bool(ok), "blocking": blocks, "detail": detail})

    cfg = tracking("GET", "/config")
    add("DRY_RUN / live mode", expect_live is None or cfg.get("dry_run") is (not expect_live), f"dry_run={cfg.get('dry_run')}", critical=True)
    add("Facebook Page id configured", str(cfg.get("facebook_page_id")) == EXPECTED_PAGE_ID, f"configured={cfg.get('facebook_page_id')} expected={EXPECTED_PAGE_ID}", critical=True)
    add("Instagram account id configured", bool(cfg.get("instagram_business_account_id")), f"{cfg.get('instagram_business_account_id')}")
    add("AI: Gemini primary + Groq fallback", cfg.get("ai_provider") == "gemini" and cfg.get("ai_fallback_provider") == "groq", f"{cfg.get('ai_provider')}/{cfg.get('ai_fallback_provider')}")
    off = set(cfg.get("disabled_platforms") or [])
    for platform in sorted(off):
        add(f"{platform.capitalize()}: automation turned off (not checked, never published)", True, "disabled_platforms in config/settings.json")
    if "youtube" not in off:
        add("YouTube format is Shorts", cfg.get("youtube_format") == "shorts", f"{cfg.get('youtube_format')} privacy={cfg.get('youtube_privacy_status')}")
        add("YouTube Shorts are public", cfg.get("youtube_privacy_status") == "public", f"privacy={cfg.get('youtube_privacy_status')}")
    if "pinterest" not in off:
        add("Pinterest board configured", bool(cfg.get("pinterest_board_id")), f"board={cfg.get('pinterest_board_id')}")

    status, run = stack.run(PROBES["meta"], timeout=180)
    meta = node_json(run, "Summarize Probe")
    details = meta.get("page_details") or {}
    add(
        "Meta: Page token acts as the configured Page (never a personal profile)",
        status == "success" and meta.get("graph_ok") and details.get("page_token_is_page") and str(meta.get("configured_page_id")) == EXPECTED_PAGE_ID,
        f"page={[(p.get('id'), p.get('name')) for p in meta.get('pages_found') or []]} token_is_page={details.get('page_token_is_page')} error={meta.get('error')}",
        critical=True,
    )
    add(
        "Meta: Instagram account linked to that Page",
        bool(meta.get("ids_match")),
        f"configured={meta.get('configured_ig_user_id')} discovered={meta.get('discovered_ig_user_id')} ig=@{details.get('ig_username')}",
        critical=True,
    )
    # Blocking for full validation (go-live / credential sync); advisory in the pre-publish check.
    for c in meta_token_checks(meta.get("page_token_debug") or {}, EXPECTED_PAGE_ID, time.time()):
        add(c["check"], c["ok"], c["detail"], blocking=not c.get("advisory"))

    if "youtube" not in off:
        status, run = stack.run(PROBES["youtube"], timeout=180)
        yt = node_json(run, "Summarize Probe")
        add("YouTube: OAuth works (channels.list mine=true)", status == "success" and yt.get("oauth_ok"), f"channels={[(c.get('id'), c.get('title')) for c in yt.get('channels_found') or []]} error={yt.get('error')}")

    if "pinterest" not in off:
        status, run = stack.run(PROBES["pinterest"], timeout=180)
        pin = node_json(run, "Summarize Probe")
        board_ids = {str(b.get("id")) for b in pin.get("boards_found") or []}
        add(
            "Pinterest: OAuth works and PINTEREST_BOARD_ID is one of the account's boards",
            status == "success" and pin.get("oauth_ok") and str(cfg.get("pinterest_board_id")) in board_ids,
            f"user={pin.get('username')} board={cfg.get('pinterest_board_id')} in_account={str(cfg.get('pinterest_board_id')) in board_ids} error={pin.get('error')}",
            blocking=False,
        )

    status, run = stack.run(PROBES["groq"], timeout=180)
    groq = node_json(run, "Summarize Probe")
    add("Groq fallback: key, model and JSON call", status == "success" and groq.get("key_ok") and groq.get("model_available") and groq.get("json_call_ok"), f"model={groq.get('groq_model')} available={groq.get('model_available')} error={groq.get('models_error') or groq.get('chat_error')}", blocking=False)

    data = tracking("GET", "/dashboard/data")
    ai = data.get("ai_last") or {}
    add("Gemini: latest generation used Gemini", ai.get("provider") == "gemini", f"product={ai.get('product_id')} provider={ai.get('provider')} model={ai.get('model')}", blocking=False)

    dup_problems = []
    for product in data.get("products") or []:
        for platform in ("instagram", "facebook", "pinterest", "youtube"):
            if product.get(f"{platform}_status") == "published":
                check = tracking("GET", f"/products/{product['product_id']}/can-publish?platform={platform}")
                if check.get("allowed") is not False:
                    dup_problems.append(f"{product['product_id']}/{platform}")
    add("Duplicate prevention: every published platform post is blocked from re-posting", not dup_problems, f"problems={dup_problems}", critical=True)

    queue = tracking("GET", "/queue")
    ids = [r["product_id"] for r in queue.get("active") or []]
    statuses = {p["product_id"]: p.get("overall_status") for p in data.get("products") or []}
    problems = []
    if len(ids) != len(set(ids)):
        problems.append("duplicate product in queue")
    if ids != sorted(ids):
        problems.append("queue not in Product ID order")
    problems += [f"{pid} already published" for pid in ids if statuses.get(pid) == "published"]
    problems += [f"{r['product_id']} has no saved content" for r in queue.get("active") or [] if not r.get("has_preview")]
    if sum(1 for r in queue.get("active") or [] if r["status"] == "publishing") > 1:
        problems.append("more than one product publishing")
    add("Queue integrity (unique, sequential, unpublished, content saved)", not problems, f"queue={ids} problems={problems}", critical=True)
    add("Content buffer", queue.get("ready", 0) >= queue.get("min_buffer", 0), f"ready={queue.get('ready')} min={queue.get('min_buffer')} target={queue.get('queue_size')}", blocking=False)

    sched = tracking("GET", "/schedule")
    upcoming = sched.get("upcoming") or []
    add(
        "Scheduler: slots computed from config/schedule.json",
        bool(sched.get("publish_times")) and len(upcoming) >= sched.get("min_buffer", 1) and len({u["slot"] for u in upcoming}) == len(upcoming),
        f"times={sched.get('publish_times')} tz={sched.get('timezone')} start={sched.get('start_date')} next={[u['slot'] for u in upcoming[:4]]}",
    )

    if deep:
        status, run = stack.run(PATH_CHECK, timeout=1200)
        path = node_json(run, "Summarize Check")
        ig, fb = path.get("instagram") or {}, path.get("facebook") or {}
        add(
            "Publish path (no posting): IG container uploaded + FINISHED, FB Reel upload to the Page",
            status == "success" and path.get("instagram_ok") and path.get("facebook_ok"),
            f"product={path.get('product_id')} media_ok={path.get('media_ok')} media_error={path.get('media_error')} ig={ig.get('status')}/{ig.get('status_code')} ig_error={ig.get('error')} "
            f"fb={fb.get('status')} page={fb.get('page_id')} ({fb.get('page_name')}) fb_error={fb.get('error')} exec={status}",
        )
        pin, yt = path.get("pinterest") or {}, path.get("youtube") or {}
        if "pinterest" not in off:
            add(
                "Publish path (no posting): Pinterest video uploaded + processed for a Video Pin",
                status == "success" and bool(path.get("pinterest_ok")),
                f"pin={pin.get('status')} video={pin.get('is_video')} board={pin.get('board_id')} media={pin.get('media_id')}/{pin.get('media_status')} pin_error={pin.get('error')}",
            )
        if "youtube" not in off:
            add(
                "Publish path (no posting): YouTube Shorts upload session accepted",
                status == "success" and bool(path.get("youtube_ok")),
                f"yt={yt.get('status')} privacy={yt.get('privacy_status')} shorts={yt.get('shorts')} yt_error={yt.get('error')}",
            )

    ok = all(c["ok"] for c in checks if c["blocking"])
    report = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok, "strict": strict, "checks": checks}
    for c in checks:
        mark = "PASS" if c["ok"] else ("FAIL" if c["blocking"] else "WARN")
        print(f"{mark:4} {c['check']} — {c['detail']}")
    print("VALIDATION", "OK" if ok else "FAILED")
    return report


def publish() -> dict:
    sched = tracking("GET", "/schedule")
    slot = sched.get("due_slot")
    if not slot:
        print("No slot due; nothing to publish.")
        return {"published": False, "reason": "no_slot_due"}
    stack = Stack()
    print(f"Publishing slot {slot} ...")
    status, run = stack.run(DAILY)
    job = node_json(run, "Build Publish Job")
    product_id = job.get("product_id")
    claim = node_json(run, "Claim Queue Head")
    result = {"slot": slot, "execution_status": status, "product_id": product_id, "claim_reason": claim.get("reason_code")}
    if product_id:
        record = tracking("GET", f"/products/{product_id}")
        result["overall_status"] = record.get("overall_status")
        result["platforms"] = {p: {"status": record.get(f"{p}_status"), "post_id": record.get(f"{p}_post_id")} for p in ("instagram", "facebook", "pinterest", "youtube")}
    print(json.dumps(result, indent=2))
    return result


def refill(max_runs: int) -> dict:
    stack = Stack()
    runs = []
    for _ in range(max_runs):
        queue = tracking("GET", "/queue")
        if queue.get("ready", 0) >= queue.get("queue_size", 0):
            break
        status, run = stack.run(PREPARER, timeout=900)
        sel = node_json(run, "Select Next Product")
        runs.append({"status": status, "product_id": sel.get("product_id"), "reason": sel.get("reason_code"), "reused": sel.get("reused")})
        print("prepare:", runs[-1])
        if status != "success" or sel.get("reason_code") in {"no_more_products", "queue_full"} or not sel.get("found", True):
            break
    queue = tracking("GET", "/queue")
    ok = queue.get("ready", 0) >= queue.get("queue_size", 0)
    print(f"buffer {queue.get('ready')}/{queue.get('queue_size')} (minimum {queue.get('min_buffer')})")
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok, "runs": runs, "ready": queue.get("ready"), "queue_size": queue.get("queue_size")}


def export(out: Path, extra: dict) -> None:
    (out / "state").mkdir(parents=True, exist_ok=True)
    (out / "site").mkdir(parents=True, exist_ok=True)
    slots = tracking("GET", "/schedule/slots")
    queue = tracking("GET", "/queue")
    previous = {}
    prev_path = out / "state" / "queue.json"
    if prev_path.exists():
        previous = json.loads(prev_path.read_text(encoding="utf-8"))
    refill_info = extra.get("refill") or {}
    queue_state = {
        "ready": queue.get("ready"),
        "queue_size": queue.get("queue_size"),
        "min_buffer": queue.get("min_buffer"),
        "last_refill_at": refill_info.get("at") or previous.get("last_refill_at"),
        "last_refill_ok": refill_info.get("ok", previous.get("last_refill_ok")),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "state" / "slots.json").write_text(json.dumps(slots, indent=2) + "\n", encoding="utf-8")
    prev_path.write_text(json.dumps(queue_state, indent=2) + "\n", encoding="utf-8")
    data = tracking("GET", "/dashboard/data", timeout=120)
    data["production"] = {**extra, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_url": os.environ.get("RUN_URL")}
    (out / "site" / "data.json").write_text(redact(json.dumps(data, default=str)), encoding="utf-8")
    print(f"exported state + dashboard data to {out}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--strict", action="store_true")
    v.add_argument("--preflight", action="store_true")
    v.add_argument("--expect-live", choices=["true", "false"])
    v.add_argument("--deep", action="store_true", help="also run 17 Publish Path Check (uploads, never publishes)")
    v.add_argument("--report")
    sub.add_parser("publish").add_argument("--report")
    r = sub.add_parser("refill")
    r.add_argument("--max", type=int, default=10)
    r.add_argument("--report")
    e = sub.add_parser("export")
    e.add_argument("--out", required=True)
    e.add_argument("--reports", nargs="*", default=[])
    args = parser.parse_args()

    if args.cmd == "export":
        extra = {}
        for path in args.reports:
            p = Path(path)
            if p.exists():
                extra[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        export(Path(args.out), extra)
        return 0
    if args.cmd == "validate":
        result = validate(args.strict, None if args.expect_live is None else args.expect_live == "true", args.preflight, args.deep)
    elif args.cmd == "publish":
        result = publish()
    else:
        result = refill(args.max)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if args.cmd == "validate" and not result["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
