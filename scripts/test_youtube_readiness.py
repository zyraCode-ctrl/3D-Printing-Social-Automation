#!/usr/bin/env python3
"""Check YouTube Shorts readiness (no upload, no secrets printed)."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8081"


def main() -> None:
    with urllib.request.urlopen(BASE + "/youtube/readiness", timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(
        json.dumps(
            {
                "dry_run": data.get("dry_run"),
                "youtube_format": data.get("youtube_format"),
                "publish_blocked_by_dry_run": data.get("publish_blocked_by_dry_run"),
                "long_form_disabled": data.get("long_form_disabled"),
                "oauth_client_id_env_set": data.get("oauth_client_id_env_set"),
                "oauth_client_secret_env_set": data.get("oauth_client_secret_env_set"),
                "upload_allowed": data.get("upload_allowed"),
                "oauth_redirect_uri": data.get("oauth_redirect_uri"),
                "required_scopes": data.get("required_scopes"),
            },
            indent=2,
        )
    )
    assert data.get("dry_run") is True
    assert data.get("youtube_format") == "shorts"
    assert data.get("publish_blocked_by_dry_run") is True
    assert data.get("upload_allowed") is False
    assert data.get("long_form_disabled") is True
    print("YouTube Shorts readiness OK (no upload).")


if __name__ == "__main__":
    main()
