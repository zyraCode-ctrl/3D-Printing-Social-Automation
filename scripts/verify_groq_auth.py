#!/usr/bin/env python3
"""Run 12 Groq Auth Probe (list models + tiny JSON call). Never prints the key; generates no social content."""

from __future__ import annotations

import sys

from verify_pinterest_dry_run import N8n, load_env, summarize_probe, wait_exec


def main() -> int:
    env = load_env()
    client = N8n()
    st, _ = client.json(
        "POST",
        "/rest/login",
        {"emailOrLdapLoginId": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"]},
    )
    if st not in {200, 201}:
        print("login", st)
        return 1
    st, run = client.json("POST", "/rest/workflows/3dprGroqAuthProbe12/run", {"triggerToStartFrom": {"name": "Run Manually"}})
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    exec_id = (data or {}).get("executionId") or (data or {}).get("id")
    if not exec_id:
        print("run_failed", st)
        return 1
    ex = wait_exec(client, str(exec_id), 120)
    summary = summarize_probe(ex) or {}
    print("exec", exec_id, ex.get("status"))
    for key in ("dry_run", "ai_fallback_provider", "groq_model", "key_ok", "models_count", "model_available", "json_call_ok", "reply", "models_error", "chat_error"):
        print(key, summary.get(key))
    return 0 if summary.get("key_ok") and summary.get("json_call_ok") else 2


if __name__ == "__main__":
    sys.exit(main())
