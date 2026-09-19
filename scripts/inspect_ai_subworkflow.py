#!/usr/bin/env python3
"""Inspect AI subworkflow publish state and recent failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

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
    st, wf = client.json("GET", "/rest/workflows/3dprAiContent003")
    doc = wf.get("data", wf) if isinstance(wf, dict) else wf
    print(
        "ai_meta",
        {
            "active": doc.get("active"),
            "versionId": doc.get("versionId"),
            "activeVersionId": doc.get("activeVersionId"),
            "isArchived": doc.get("isArchived"),
        },
    )
    nodes = {n["name"]: n for n in doc.get("nodes", [])}
    gv = nodes.get("Gemini Vision", {})
    print("gemini_url_expr", (gv.get("parameters") or {}).get("url"))
    print("gemini_body_mode", {k: (gv.get("parameters") or {}).get(k) for k in ("contentType", "rawContentType", "specifyBody", "jsonBody", "body")})
    print("gemini_cred", gv.get("credentials"))
    blob = json.dumps(doc)
    print("has_3_6", "gemini-3.6-flash" in blob)
    print("has_2_5", "gemini-2.5-flash" in blob)

    filt = quote(json.dumps({"workflowId": "3dprAiContent003"}))
    st, ex = client.json("GET", f"/rest/executions?filter={filt}&limit=5")
    results = ((ex.get("data") or {}).get("results") if isinstance(ex, dict) else None) or []
    print("ai_exec_count_listed", len(results))
    for item in results[:5]:
        print(
            "ai_exec",
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "mode": item.get("mode"),
                "startedAt": item.get("startedAt"),
            },
        )

    # Dump latest wrapper execute failure 41 and daily 38 child lookups
    for eid in ("41", "38"):
        st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
        d = detail.get("data", detail)
        arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
        root = resolve_flat(arr, arr[0])
        run_data = (root.get("resultData") or {}).get("runData") or {}
        for name in ("Call AI Content", "Generate AI Content"):
            runs = run_data.get(name) or []
            for nr in runs if isinstance(runs, list) else [runs]:
                err = (nr or {}).get("error")
                if err:
                    print(
                        "exec",
                        eid,
                        name,
                        {
                            "message": err.get("message") if isinstance(err, dict) else err,
                            "description": (err.get("description") if isinstance(err, dict) else None),
                            "httpCode": (err.get("httpCode") if isinstance(err, dict) else None),
                            "keys": sorted(err.keys()) if isinstance(err, dict) else None,
                        },
                    )


if __name__ == "__main__":
    main()
