#!/usr/bin/env python3
"""Run 13 Live Reel Test, 14 Live Pinterest Video Pin (--pinterest), or 15 Live Facebook Reel Test (--facebook-only).

REAL posts; explicit approval required.

Prints results only, never tokens.
"""

from __future__ import annotations

import json
import re
import sys

from dump_execution import resolve_flat
from verify_pinterest_dry_run import N8n, load_env, wait_exec

TOKEN_RE = re.compile(r"(EAA[A-Za-z0-9]+|ya29\.[A-Za-z0-9_\-\.]+|gsk_[A-Za-z0-9]+)")


def redact(value: object) -> str:
    return TOKEN_RE.sub("<redacted>", json.dumps(value, default=str, ensure_ascii=False))


def main() -> int:
    if "--i-approve-live-posting" not in sys.argv:
        print("Refusing: pass --i-approve-live-posting to create REAL posts.")
        return 1
    env = load_env()
    client = N8n()
    st, _ = client.json("POST", "/rest/login", {"emailOrLdapLoginId": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"]})
    if st not in {200, 201}:
        print("login", st)
        return 1
    if "--pinterest" in sys.argv:
        workflow_id = "3dprLivePinVid014"
    elif "--facebook-only" in sys.argv:
        workflow_id = "3dprLiveFbReel015"
    else:
        workflow_id = "3dprLiveReel00013"
    st, run = client.json("POST", f"/rest/workflows/{workflow_id}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    exec_id = (data or {}).get("executionId") or (data or {}).get("id")
    if not exec_id:
        print("run_failed", st, redact(run)[:400])
        return 1
    print("exec", exec_id, flush=True)
    ex = wait_exec(client, str(exec_id), 900)
    arr = json.loads(ex["data"])
    root = resolve_flat(arr, arr[0])
    result = root.get("resultData") or {}
    run_data = result.get("runData") or {}
    print("status", ex.get("status"), "last_node", result.get("lastNodeExecuted"))
    if result.get("error"):
        print("workflow_error", redact({k: result["error"].get(k) for k in ("message", "description")}))
    summary = run_data.get("Live Summary")
    if summary:
        print("summary", redact(summary[-1]["data"]["main"][0][0]["json"]))
        return 0
    for name, runs in run_data.items():
        err = runs[-1].get("error")
        if err:
            print("node_error", name, redact({k: err.get(k) for k in ("message", "description")})[:600])
    return 2


if __name__ == "__main__":
    sys.exit(main())
