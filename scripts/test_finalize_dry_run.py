#!/usr/bin/env python3
"""Run the full Daily Publisher DRY_RUN path and verify Finalize Dry Run succeeds."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402

DAILY_WF = "3dprDailyPub0001"
REQUIRED_NODES = [
    "List Google Drive Folder",
    "Select Next Product",
    "Download Drive Media",
    "Prepare Vision Still",
    "Generate AI Content",
    "Save Preview",
    "Finalize Dry Run",
]


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


def node_summary(run_data: dict, name: str) -> dict:
    runs = run_data.get(name) or []
    items = runs if isinstance(runs, list) else [runs]
    for nr in items:
        err = (nr or {}).get("error")
        main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
        j = main[0].get("json") if main else None
        if err:
            return {
                "ok": False,
                "error": str(err.get("message") if isinstance(err, dict) else err)[:400],
                "description": str(err.get("description") if isinstance(err, dict) else "")[:400],
            }
        if isinstance(j, dict):
            out = {"ok": True, "keys": sorted(j.keys())[:20]}
            for k in ("product_id", "filename", "overall_status", "ok", "ai_provider_used", "vision_notes"):
                if k in j:
                    out[k] = j.get(k) if k != "vision_notes" else str(j.get(k))[:180]
            return out
    return {"ok": False, "error": "node_not_executed"}


def main() -> None:
    env = load_env()
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

    # Confirm live Finalize Dry Run URL uses Pick Vision File
    st, wf = client.json("GET", f"/rest/workflows/{DAILY_WF}")
    doc = wf.get("data", wf) if isinstance(wf, dict) else wf
    nodes = {n["name"]: n for n in doc.get("nodes", [])}
    finalize = nodes.get("Finalize Dry Run", {})
    url = (finalize.get("parameters") or {}).get("url", "")
    print("live_finalize_url", url)
    if "Pick Vision File" not in str(url):
        raise SystemExit("live Finalize Dry Run still uses stale product_id expression")

    st, run = client.json(
        "POST",
        f"/rest/workflows/{DAILY_WF}/run",
        {"triggerToStartFrom": {"name": "Run Manually"}},
    )
    eid = (run.get("data") or {}).get("executionId")
    print("execution", eid)
    result = {"ok": False, "execution_id": eid, "nodes": {}}
    for _ in range(300):
        st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
        d = detail.get("data", detail)
        status = d.get("status")
        if status not in {"success", "error", "crashed", "canceled"}:
            time.sleep(1)
            continue
        result["status"] = status
        arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
        root = resolve_flat(arr, arr[0])
        run_data = (root.get("resultData") or {}).get("runData") or {}
        for name in REQUIRED_NODES + ["Pick Vision File", "Build Preview Payload", "Log Dry Run Preview"]:
            result["nodes"][name] = node_summary(run_data, name)
        finalize = result["nodes"].get("Finalize Dry Run") or {}
        result["ok"] = status == "success" and bool(finalize.get("ok"))
        if not result["ok"]:
            # surface first failed required node
            for name in REQUIRED_NODES:
                info = result["nodes"].get(name) or {}
                if not info.get("ok"):
                    result["failed_node"] = name
                    result["error"] = info.get("error") or info.get("description")
                    break
            err = (root.get("resultData") or {}).get("error")
            if err and not result.get("error"):
                result["error"] = str(err.get("message") if isinstance(err, dict) else err)[:400]
        break
    else:
        result["error"] = "timeout"

    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
