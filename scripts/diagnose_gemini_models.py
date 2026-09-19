#!/usr/bin/env python3
"""Diagnose Gemini models available to the n8n Google Gemini credential (no secrets printed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402

WF_ID = "3dprGeminiDiagT98"
WF_NAME = "98 Gemini Model Diagnose"


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

    # Fix missing host on Gemini credential without changing the API key.
    st, detail = client.json("GET", "/rest/credentials/SEaxVC4Mj623hZwO?includeData=true")
    cred = detail.get("data", detail) if isinstance(detail, dict) else detail
    data = dict(cred.get("data") or {})
    if not data.get("host"):
        data["host"] = "https://generativelanguage.googleapis.com"
        payload = {
            "name": cred.get("name") or "Google Gemini account",
            "type": "googlePalmApi",
            "data": data,
        }
        st, body = client.json("PATCH", "/rest/credentials/SEaxVC4Mj623hZwO", payload)
        if st not in {200, 201}:
            st, body = client.json("PUT", "/rest/credentials/SEaxVC4Mj623hZwO", payload)
        print("credential_host_fix", st)
    else:
        print("credential_host_ok", data.get("host"))

    workflow = {
        "id": WF_ID,
        "name": WF_NAME,
        "active": False,
        "nodes": [
            {
                "id": "d1",
                "name": "Run Manually",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "d2",
                "name": "List Models",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.5,
                "position": [260, 0],
                "parameters": {
                    "method": "GET",
                    "url": "https://generativelanguage.googleapis.com/v1beta/models",
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googlePalmApi",
                    "options": {"timeout": 60000},
                },
                "credentials": {
                    "googlePalmApi": {"id": "SEaxVC4Mj623hZwO", "name": "Google Gemini account"}
                },
            },
            {
                "id": "d3",
                "name": "Summarize Models",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [520, 0],
                "parameters": {
                    "jsCode": """
const models = ($json.models || []).map((m) => m.name || m).filter(Boolean);
const flash = models.filter((n) => String(n).toLowerCase().includes('flash'));
const preferred = [
  'models/gemini-2.5-flash',
  'models/gemini-2.5-flash-lite',
  'models/gemini-2.0-flash',
  'models/gemini-2.0-flash-001',
  'models/gemini-1.5-flash',
  'models/gemini-1.5-flash-latest',
  'models/gemini-3.6-flash',
  'models/gemini-flash-latest',
];
const availablePreferred = preferred.filter((p) => models.includes(p) || models.includes(p.replace(/^models\\//,'')));
return [{ json: { count: models.length, flash, availablePreferred, all: models } }];
""".strip()
                    + "\n"
                },
            },
        ],
        "connections": {
            "Run Manually": {"main": [[{"node": "List Models", "type": "main", "index": 0}]]},
            "List Models": {"main": [[{"node": "Summarize Models", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }

    st, existing = client.json("GET", "/rest/workflows")
    items = (existing.get("data") if isinstance(existing, dict) else existing) or []
    found = None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("name") == WF_NAME:
                found = item.get("id")
                break
    if found:
        st, body = client.json("PUT", f"/rest/workflows/{found}", workflow)
        wid = found
        print("updated diag", st)
    else:
        st, body = client.json("POST", "/rest/workflows", workflow)
        wid = body.get("id") if isinstance(body, dict) else WF_ID
        if isinstance(body, dict) and isinstance(body.get("data"), dict) and body["data"].get("id"):
            wid = body["data"]["id"]
        print("created diag", st, wid)

    st, run = client.json("POST", f"/rest/workflows/{wid}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
    print("run", st, run)
    eid = (run.get("data") or {}).get("executionId")
    import time

    for _ in range(40):
        st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
        d = detail.get("data", detail)
        status = d.get("status")
        if status in {"success", "error", "crashed", "canceled"}:
            print("status", status)
            if status != "success":
                print("fail", str(d.get("data"))[:500])
                raise SystemExit("model list failed")
            arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")

            def resolve(x, depth=0):
                if depth > 80:
                    return x
                if isinstance(x, str) and x.isdigit():
                    i = int(x)
                    if isinstance(arr, list) and i < len(arr):
                        return resolve(arr[i], depth + 1)
                if isinstance(x, list):
                    return [resolve(v, depth + 1) for v in x]
                if isinstance(x, dict):
                    return {k: resolve(v, depth + 1) for k, v in x.items()}
                return x

            root = resolve(arr[0])
            runs = ((root.get("resultData") or {}).get("runData") or {}).get("Summarize Models") or []
            for nr in runs if isinstance(runs, list) else [runs]:
                main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
                if main:
                    print(json.dumps(main[0].get("json"), indent=2)[:4000])
            break
        time.sleep(1)
    else:
        raise SystemExit("timeout")

    client.json("DELETE", f"/rest/workflows/{wid}")
    print("cleaned", wid)


if __name__ == "__main__":
    main()
