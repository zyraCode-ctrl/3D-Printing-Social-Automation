#!/usr/bin/env python3
"""Call live 03 AI Content Generator with a real Drive vision still (DRY_RUN)."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_workflows import N8n, load_env, workflow_update_payload  # noqa: E402

TRACKING = "http://127.0.0.1:8081"
AI_WF = "3dprAiContent003"
NAME = "96 Gemini Vision Drive Test"


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


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 180) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    env = load_env()
    cfg = http_json("GET", f"{TRACKING}/config")
    print(
        "config",
        {
            "dry_run": cfg.get("dry_run"),
            "gemini_model": cfg.get("gemini_model"),
            "gemini_host": cfg.get("gemini_host"),
        },
    )
    if cfg.get("dry_run") is not True:
        raise SystemExit("DRY_RUN must remain true")

    listed = http_json(
        "POST",
        f"{TRACKING}/drive/public-list",
        {"folder_id": cfg.get("google_drive_folder_id")},
    )
    files = listed.get("files") or []
    chosen = next((f for f in files if str(f.get("name")).lower() == "004.mp4"), None) or files[0]
    downloaded = http_json(
        "POST",
        f"{TRACKING}/drive/public-download",
        {"file_id": chosen["id"], "filename": chosen["name"]},
        timeout=180,
    )
    if not downloaded.get("ok"):
        raise SystemExit(f"download failed: {downloaded}")
    product_id = "".join(ch for ch in Path(chosen["name"]).stem if ch.isdigit()) or Path(chosen["name"]).stem
    vision = http_json(
        "POST",
        f"{TRACKING}/media/prepare-vision",
        {"local_path": downloaded["local_path"], "media_kind": "video", "product_id": product_id},
        timeout=180,
    )
    if not vision.get("base64"):
        raise SystemExit(vision)
    job = {
        "product_id": product_id,
        "filename": chosen["name"],
        "file_id": chosen["id"],
        "media_type": "video",
        "vision_base64": vision["base64"],
        "vision_mime": vision.get("mime_type") or "image/jpeg",
        "vision_source": vision.get("source"),
        "local_path": downloaded["local_path"],
    }
    print(
        "media",
        {
            "filename": job["filename"],
            "product_id": job["product_id"],
            "vision_b64_len": len(job["vision_base64"]),
            "source": job["vision_source"],
        },
    )

    js = "const job = " + json.dumps(job) + ";\nreturn [{ json: job }];\n"
    workflow = {
        "name": NAME,
        "active": False,
        "nodes": [
            {
                "id": "w1",
                "name": "Run Manually",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
                "parameters": {},
            },
            {
                "id": "w2",
                "name": "Load Drive Vision Job",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [240, 0],
                "parameters": {"jsCode": js},
            },
            {
                "id": "w3",
                "name": "Call AI Content",
                "type": "n8n-nodes-base.executeWorkflow",
                "typeVersion": 1.3,
                "position": [500, 0],
                "parameters": {
                    "source": "database",
                    "workflowId": {
                        "__rl": True,
                        "value": AI_WF,
                        "mode": "id",
                        "cachedResultName": "03 AI Content Generator",
                    },
                    "options": {"waitForSubWorkflow": True},
                },
            },
        ],
        "connections": {
            "Run Manually": {"main": [[{"node": "Load Drive Vision Job", "type": "main", "index": 0}]]},
            "Load Drive Vision Job": {"main": [[{"node": "Call AI Content", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1"},
    }

    client = N8n(f"http://127.0.0.1:{env.get('N8N_PORT', '5678')}")
    st, _ = client.json(
        "POST",
        "/rest/login",
        {
            "emailOrLdapLoginId": env.get("N8N_OWNER_EMAIL", "admin@localhost.local"),
            "password": env.get("N8N_OWNER_PASSWORD", ""),
        },
    )
    st, existing = client.json("GET", "/rest/workflows")
    items = (existing.get("data") if isinstance(existing, dict) else existing) or []
    found = next((i.get("id") for i in items if isinstance(i, dict) and i.get("name") == NAME), None)
    if found:
        st, full = client.json("GET", f"/rest/workflows/{found}")
        current = full.get("data", full) if isinstance(full, dict) else full
        st, body = client.json(
            "PATCH",
            f"/rest/workflows/{found}",
            workflow_update_payload(workflow, current if isinstance(current, dict) else {}),
        )
        wid = found
        print("patch", st)
    else:
        st, body = client.json("POST", "/rest/workflows", workflow)
        wid = body.get("id") if isinstance(body, dict) else None
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            wid = body["data"].get("id", wid)
        print("create", st, wid)

    st, run = client.json(
        "POST", f"/rest/workflows/{wid}/run", {"triggerToStartFrom": {"name": "Run Manually"}}
    )
    eid = (run.get("data") or {}).get("executionId")
    print("execution", eid)
    result = {"ok": False, "execution_id": eid}
    for _ in range(180):
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
        for node_name, runs in run_data.items():
            for nr in runs if isinstance(runs, list) else [runs]:
                err = (nr or {}).get("error")
                if err:
                    result["failed_node"] = node_name
                    result["error"] = str(err.get("message") if isinstance(err, dict) else err)[:500]
                    if isinstance(err, dict) and err.get("description"):
                        result["error_detail"] = str(err.get("description"))[:500]
                main = ((((nr or {}).get("data") or {}).get("main") or [[]])[0] or [])
                if main and isinstance(main[0].get("json"), dict):
                    j = main[0]["json"]
                    if j.get("content"):
                        content = j["content"]
                        result.update(
                            {
                                "ok": True,
                                "product_id": j.get("product_id"),
                                "filename": j.get("filename"),
                                "ai_provider_used": j.get("ai_provider_used"),
                                "gemini_model_used": j.get("gemini_model_used"),
                                "vision_notes": str(j.get("vision_notes") or "")[:300],
                                "instagram_caption": str((content.get("instagram") or {}).get("caption") or "")[:220],
                                "platforms": sorted(
                                    k
                                    for k in ("instagram", "facebook", "pinterest", "youtube")
                                    if content.get(k)
                                ),
                            }
                        )
        break

    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
