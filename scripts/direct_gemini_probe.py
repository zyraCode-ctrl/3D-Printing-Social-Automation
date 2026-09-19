#!/usr/bin/env python3
"""Direct Gemini generateContent probe using n8n credential API key (never prints the key)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
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

MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.0-flash",
]
VERSIONS = ["v1beta", "v1"]


def post_json(url: str, payload: dict, timeout: int = 90) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body[:400]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body[:400]


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

    st, detail = client.json("GET", f"/rest/credentials/{CRED_ID}?includeData=true")
    cred = detail.get("data", detail) if isinstance(detail, dict) else detail
    data = (cred or {}).get("data") or {}
    api_key = data.get("apiKey") or ""
    host = str(data.get("host") or "https://generativelanguage.googleapis.com").rstrip("/")
    if not api_key:
        raise SystemExit("Gemini credential has no API key")
    print("host", host)
    print("apiKey_len", len(api_key))

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": 'Reply with JSON only: {"ok": true}'},
                    {"inlineData": {"mimeType": "image/jpeg", "data": TINY_JPEG_B64}},
                ],
            }
        ],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }

    winners = []
    for ver in VERSIONS:
        for model in MODELS:
            url = f"{host}/{ver}/models/{model}:generateContent?key={api_key}"
            safe_url = f"{host}/{ver}/models/{model}:generateContent?key=REDACTED"
            code, resp = post_json(url, body)
            ok = False
            detail_msg = ""
            if isinstance(resp, dict):
                if resp.get("candidates"):
                    ok = True
                    detail_msg = "candidates"
                elif resp.get("error"):
                    err = resp["error"]
                    detail_msg = f"{err.get('status') or code}: {err.get('message')}"
                else:
                    detail_msg = str(resp)[:200]
            else:
                detail_msg = str(resp)[:200]
            row = {"version": ver, "model": model, "http": code, "ok": ok, "detail": detail_msg[:280]}
            print(json.dumps(row))
            if ok:
                winners.append(f"{ver}/{model}")
    print("WINNERS", winners)


if __name__ == "__main__":
    main()
