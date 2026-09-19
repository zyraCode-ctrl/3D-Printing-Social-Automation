#!/usr/bin/env python3
"""Find a working n8n workflow update path, then probe Gemini generateContent models."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env  # noqa: E402

CRED_ID = "SEaxVC4Mj623hZwO"
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
    "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAGfAP/E"
    "ABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAI"
    "AQMBAT8Bf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Bf//Z"
)

CANDIDATES = [
    ("v1beta", "gemini-2.5-flash"),
    ("v1beta", "gemini-2.5-flash-lite"),
    ("v1beta", "gemini-flash-latest"),
    ("v1beta", "gemini-3.6-flash"),
    ("v1beta", "gemini-3.5-flash"),
    ("v1", "gemini-2.5-flash"),
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


def find_by_name(client: N8n, name: str) -> str | None:
    st, existing = client.json("GET", "/rest/workflows")
    items = (existing.get("data") if isinstance(existing, dict) else existing) or []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("name") == name:
                return item.get("id")
    return None


def replace_workflow(client: N8n, name: str, workflow: dict) -> str:
    """Delete-by-name then create. Avoids broken PUT on some n8n builds."""
    found = find_by_name(client, name)
    if found:
        st, body = client.json("DELETE", f"/rest/workflows/{found}")
        print("delete", found, st)
    payload = dict(workflow)
    payload.pop("id", None)
    payload["name"] = name
    payload["active"] = False
    st, body = client.json("POST", "/rest/workflows", payload)
    print("create", name, st)
    if st not in {200, 201}:
        print("create_fail", str(body)[:500])
        raise SystemExit("create failed")
    wid = body.get("id") if isinstance(body, dict) else None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        wid = body["data"].get("id", wid)
    if not wid and isinstance(body, dict):
        wid = body.get("data") if isinstance(body.get("data"), str) else wid
    # fallback: look up by name
    return wid or find_by_name(client, name) or ""


def run_node(client: N8n, wid: str, node_name: str) -> dict:
    st, run = client.json(
        "POST", f"/rest/workflows/{wid}/run", {"triggerToStartFrom": {"name": "Run Manually"}}
    )
    eid = (run.get("data") or {}).get("executionId")
    if not eid and isinstance(run, dict):
        eid = run.get("executionId")
    for _ in range(60):
        st, detail = client.json("GET", f"/rest/executions/{eid}?includeData=true")
        d = detail.get("data", detail)
        status = d.get("status")
        if status in {"success", "error", "crashed", "canceled"}:
            arr = json.loads(d["data"]) if isinstance(d.get("data"), str) else d.get("data")
            root = resolve_flat(arr, arr[0])
            runs = ((root.get("resultData") or {}).get("runData") or {}).get(node_name) or []
            for nr in runs if isinstance(runs, list) else [runs]:
                main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
                if main and isinstance(main[0].get("json"), dict):
                    return {"status": status, **main[0]["json"]}
            return {"status": status, "ok": False, "detail": "no_output"}
        time.sleep(0.4)
    return {"status": "timeout", "ok": False, "detail": "timeout"}


def build_probe(version: str, model: str) -> dict:
    js = (
        f"const version = {json.dumps(version)};\n"
        f"const model = {json.dumps(model)};\n"
        "const body = {\n"
        "  contents: [{\n"
        "    role: 'user',\n"
        "    parts: [\n"
        "      { text: 'Reply with JSON only: {\"ok\": true}' },\n"
        f"      {{ inlineData: {{ mimeType: 'image/jpeg', data: {json.dumps(TINY_JPEG_B64)} }} }}\n"
        "    ]\n"
        "  }],\n"
        "  generationConfig: { responseMimeType: 'application/json', temperature: 0 }\n"
        "};\n"
        "return [{ json: {\n"
        "  version, model,\n"
        "  request_url: 'https://generativelanguage.googleapis.com/' + version + '/models/' + model + ':generateContent',\n"
        "  request_body: body\n"
        "} }];\n"
    )
    return {
        "name": "97 Gemini Generate Probe",
        "active": False,
        "nodes": [
            {
                "id": "p1",
                "name": "Run Manually",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "p2",
                "name": "Build Request",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [220, 0],
                "parameters": {"jsCode": js},
            },
            {
                "id": "p3",
                "name": "Gemini Probe",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.5,
                "position": [460, 0],
                "parameters": {
                    "method": "POST",
                    "url": "={{ $json.request_url }}",
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "googlePalmApi",
                    "sendBody": True,
                    "contentType": "raw",
                    "rawContentType": "application/json",
                    "body": "={{ JSON.stringify($json.request_body) }}",
                    "options": {"timeout": 90000, "response": {"response": {"neverError": True}}},
                },
                "credentials": {
                    "googlePalmApi": {"id": CRED_ID, "name": "Google Gemini account"}
                },
                "onError": "continueRegularOutput",
            },
            {
                "id": "p4",
                "name": "Classify",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [700, 0],
                "parameters": {
                    "jsCode": (
                        "const built = $('Build Request').first().json;\n"
                        "const raw = $json;\n"
                        "let ok = false;\n"
                        "let detail = 'unknown';\n"
                        "if (raw.candidates) { ok = true; detail = 'candidates'; }\n"
                        "else if (raw.error) { detail = String(raw.error.message || raw.error.status || JSON.stringify(raw.error)).slice(0, 280); }\n"
                        "else if (raw.message) { detail = String(raw.message).slice(0, 280); }\n"
                        "else { detail = JSON.stringify(raw).slice(0, 280); }\n"
                        "return [{ json: { version: built.version, model: built.model, url: built.request_url, ok, detail } }];\n"
                    )
                },
            },
        ],
        "connections": {
            "Run Manually": {"main": [[{"node": "Build Request", "type": "main", "index": 0}]]},
            "Build Request": {"main": [[{"node": "Gemini Probe", "type": "main", "index": 0}]]},
            "Gemini Probe": {"main": [[{"node": "Classify", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }


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
    print("login", st)

    # Also try updating AI workflow the same way import does, to learn PUT requirements
    st, full = client.json("GET", "/rest/workflows/3dprAiContent003")
    print("get_ai", st, type(full).__name__, list(full.keys())[:12] if isinstance(full, dict) else None)
    ai = full.get("data", full) if isinstance(full, dict) else full
    if isinstance(ai, dict):
        print("ai_keys", sorted(ai.keys()))
        print("versionId", ai.get("versionId"))
        print("active", ai.get("active"))

    results = []
    last_wid = None
    for version, model in CANDIDATES:
        wf = build_probe(version, model)
        wid = replace_workflow(client, "97 Gemini Generate Probe", wf)
        last_wid = wid
        row = run_node(client, wid, "Classify")
        results.append(row)
        print("PROBE", json.dumps(row))
        if row.get("ok"):
            # keep probing to learn all winners, but prefer 2.5-flash
            pass

    if last_wid:
        client.json("DELETE", f"/rest/workflows/{last_wid}")
    print("WINNERS", [f"{r.get('version')}/{r.get('model')}" for r in results if r.get("ok")])
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
