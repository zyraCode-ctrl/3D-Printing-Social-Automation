#!/usr/bin/env python3
"""Run 09 Meta Auth Probe (read-only me/accounts). Never publishes; never prints tokens."""

from __future__ import annotations

import sys

from verify_pinterest_dry_run import N8n, load_env, summarize_probe, track, wait_exec

PLATFORMS = ("instagram", "facebook", "pinterest", "youtube")


def main() -> int:
    env = load_env()
    client = N8n()
    st, _ = client.json(
        "POST",
        "/rest/login",
        {"emailOrLdapLoginId": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"]},
    )
    print("login", st, flush=True)
    if st not in {200, 201}:
        return 1

    cfg = track("/config")
    ready = track("/meta/readiness")
    print("dry_run", cfg.get("dry_run"), flush=True)
    print("page_id_set", ready.get("facebook_page_id_set"), "ig_id_set", ready.get("instagram_business_account_id_set"), flush=True)
    print("graph_version", ready.get("meta_graph_version"), flush=True)
    if cfg.get("dry_run") is not True:
        return 1

    st, creds = client.json("GET", "/rest/credentials")
    items = creds.get("data", creds) if isinstance(creds, dict) else creds
    for item in items or []:
        if isinstance(item, dict) and item.get("type") == "facebookGraphApi":
            print("credential", item.get("name"), item.get("type"), flush=True)

    st, wfs = client.json("GET", "/rest/workflows")
    wf_items = wfs.get("data", wfs) if isinstance(wfs, dict) else wfs
    by_name = {i.get("name"): i.get("id") for i in (wf_items or []) if isinstance(i, dict)}
    for name in ("04 Instagram Publisher", "05 Facebook Publisher", "09 Meta Auth Probe"):
        print("workflow", name, bool(by_name.get(name)), flush=True)
    probe_id = by_name.get("09 Meta Auth Probe")
    if not probe_id:
        return 1

    st, run = client.json("POST", f"/rest/workflows/{probe_id}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    exec_id = (data or {}).get("executionId") or (data or {}).get("id")
    print("probe_exec", exec_id, flush=True)
    if not exec_id:
        return 1
    ex = wait_exec(client, str(exec_id), 180)
    print("probe_status", ex.get("status"), flush=True)
    summary = summarize_probe(ex) or {}
    print("token_type", summary.get("token_type"), "owner", summary.get("token_owner"), flush=True)
    for page in summary.get("user_pages") or []:
        print("user_page", page.get("id"), page.get("name"), "ig", page.get("ig"), flush=True)
    print("configured_page_id", summary.get("configured_page_id"), "configured_ig", summary.get("configured_ig_user_id"), flush=True)
    print("graph_ok", summary.get("graph_ok"), "ids_match", summary.get("ids_match"), flush=True)
    print("error", summary.get("error"), flush=True)
    for page in summary.get("pages_found") or []:
        print("page", page.get("id"), page.get("name"), "ig", page.get("ig"), flush=True)
    print("discovered_ig_user_id", summary.get("discovered_ig_user_id"), flush=True)
    print("page_details", summary.get("page_details"), flush=True)
    meta_ok = bool(summary.get("graph_ok") and summary.get("ids_match"))

    if "--daily" not in sys.argv:
        return 0 if meta_ok else 2
    daily_id = by_name.get("01 Daily Publisher")
    for platform in PLATFORMS:
        check = track(f"/products/1/can-publish?platform={platform}")
        print("can_publish", platform, check.get("allowed"), flush=True)
    st, run = client.json("POST", f"/rest/workflows/{daily_id}/run", {"triggerToStartFrom": {"name": "Run Manually"}})
    data = run.get("data") if isinstance(run.get("data"), dict) else run
    daily_exec = (data or {}).get("executionId") or (data or {}).get("id")
    print("daily_exec", daily_exec, flush=True)
    if not daily_exec:
        return 1
    daily_ex = wait_exec(client, str(daily_exec), 600)
    print("daily_status", daily_ex.get("status"), flush=True)
    prod = track("/products/1")
    published = False
    for platform in PLATFORMS:
        status = prod.get(f"{platform}_status")
        post_id = prod.get(f"{platform}_post_id")
        print("product1", platform, status, "post_id", post_id, "error", prod.get(f"{platform}_error"), flush=True)
        published = published or status == "published" or bool(post_id)
    print("overall", prod.get("overall_status"), flush=True)
    if published:
        print("FAIL something was published", flush=True)
        return 1
    return 0 if meta_ok else 2


if __name__ == "__main__":
    sys.exit(main())
