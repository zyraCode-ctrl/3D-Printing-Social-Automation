#!/usr/bin/env python3
"""Confirm DRY_RUN duplicate protection still blocks social publishing."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8081"


def req(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = req("GET", "/health")
    assert health["ok"] is True
    config = req("GET", "/config")
    print("dry_run", config["dry_run"], "ai_provider", config["ai_provider"], "use_sample_media", config["use_sample_media"])
    assert config["dry_run"] is True
    assert config["ai_provider"] == "gemini"
    assert config.get("gemini_model") == "gemini-3.6-flash"
    check = req("GET", "/products/1/can-publish?platform=instagram")
    print("instagram can-publish", check)
    assert check.get("dry_run") is True or check.get("allowed") is False
    print("DRY_RUN still blocks social publishing.")


if __name__ == "__main__":
    main()
