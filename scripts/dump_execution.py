#!/usr/bin/env python3
"""Dump failed nodes from the latest Daily Publisher execution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402


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


def main() -> None:
    eid = sys.argv[1] if len(sys.argv) > 1 else "38"
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
    st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
    d = detail.get("data", detail)
    print("status", d.get("status"))
    arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
    root = resolve_flat(arr, arr[0])
    run_data = (root.get("resultData") or {}).get("runData") or {}
    for name, runs in run_data.items():
        for nr in runs if isinstance(runs, list) else [runs]:
            err = (nr or {}).get("error")
            main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
            summary = {
                "node": name,
                "error": (err.get("message") if isinstance(err, dict) else err) if err else None,
            }
            if main and isinstance(main[0].get("json"), dict):
                j = main[0]["json"]
                summary["keys"] = sorted(j.keys())[:20]
                for k in ("product_id", "filename", "request_url", "ai_provider", "gemini_model", "error", "message"):
                    if k in j:
                        summary[k] = str(j[k])[:240]
                if j.get("content"):
                    summary["has_content"] = True
                if j.get("candidates"):
                    summary["has_candidates"] = True
                if j.get("vision_base64"):
                    summary["vision_b64_len"] = len(str(j["vision_base64"]))
            if summary.get("error") or name in {
                "Generate AI Content",
                "Gemini Vision",
                "Build Provider Payload",
                "Prepare Vision Still",
                "Pick Vision File",
                "Build AI Job",
            }:
                print(json.dumps(summary, indent=2)[:1200])

    # Also list sub-executions if present
    st, subs = client.json("GET", f"/rest/executions?filter={{\"parentExecutionId\":\"{eid}\"}}&limit=10")
    print("subs_status", st)
    print("subs", str(subs)[:800])


if __name__ == "__main__":
    main()
