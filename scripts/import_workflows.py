#!/usr/bin/env python3
"""Wait for n8n, create the owner account if needed, import and publish workflows."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "n8n" / "workflows"
ENV_PATH = ROOT / ".env"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if v})
    return values


class N8n:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, payload: dict | None = None, extra_headers: dict | None = None) -> tuple[int, str, dict]:
        url = self.base + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        csrf = self.csrf_token()
        if csrf:
            headers["X-N8N-CSRF-TOKEN"] = csrf
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, body, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, body, dict(exc.headers)

    def csrf_token(self) -> str | None:
        for cookie in self.jar:
            if "csrf" in cookie.name.lower() or cookie.name in {"n8n-browserId"}:
                if "csrf" in cookie.name.lower():
                    return cookie.value
        return None

    def json(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list | str]:
        status, body, _headers = self.request(method, path, payload)
        if not body:
            return status, {}
        if not body.lstrip().startswith(("{", "[")):
            return status, body
        try:
            parsed: dict | list | str = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return status, parsed


def wait_http(url: str, attempts: int = 60) -> None:
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status < 500:
                    print(f"Ready: {url}")
                    return
        except Exception:
            pass
        print(f"Waiting for {url} ({i + 1}/{attempts})")
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for {url}")


def wait_n8n_api(client: "N8n", attempts: int = 90) -> None:
    """healthz can pass while REST still returns 'n8n is starting up'."""
    for i in range(attempts):
        status, body = client.json("GET", "/rest/settings")
        text = body if isinstance(body, str) else json.dumps(body)[:120]
        if status == 200 and isinstance(body, dict) and "n8n is starting up" not in text.lower():
            print(f"n8n REST ready ({i + 1})")
            return
        print(f"Waiting for n8n REST ({i + 1}/{attempts}): {status} {text}")
        time.sleep(2)
    raise SystemExit("Timed out waiting for n8n REST API")


def list_credentials(client: N8n) -> list[dict]:
    status, body = client.json("GET", "/rest/credentials")
    if status != 200:
        return []
    items = body.get("data", body) if isinstance(body, dict) else body
    return items if isinstance(items, list) else []


def ensure_credentials(client: N8n, env: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    env = env or {}
    existing = {item.get("name"): item for item in list_credentials(client) if isinstance(item, dict)}
    specs = [
        {
            "name": "Google Drive account",
            "type": "googleDriveOAuth2Api",
            "data": {"clientId": "", "clientSecret": ""},
        },
        {
            "name": "Google Gemini account",
            "type": "googlePalmApi",
            "data": {"host": "https://generativelanguage.googleapis.com", "apiKey": ""},
        },
        {
            "name": "Facebook Graph account",
            "type": "facebookGraphApi",
            "data": {"accessToken": ""},
        },
        {
            "name": "YouTube account",
            "type": "youTubeOAuth2Api",
            "data": {"clientId": "", "clientSecret": ""},
        },
    ]
    mapping: dict[str, dict[str, str]] = {}
    yt_client_id = (env.get("YOUTUBE_OAUTH_CLIENT_ID") or os.environ.get("YOUTUBE_OAUTH_CLIENT_ID") or "").strip()
    yt_client_secret = (
        env.get("YOUTUBE_OAUTH_CLIENT_SECRET") or os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET") or ""
    ).strip()
    for spec in specs:
        current = existing.get(spec["name"])
        if current and current.get("id"):
            mapping[spec["type"]] = {"id": current["id"], "name": spec["name"]}
            print(f"Credential exists: {spec['name']} ({current['id']})")
            if spec["type"] == "googlePalmApi":
                # Keep the existing API key; only ensure host is set for HTTP Request auth.
                # In CI, GEMINI_API_KEY can inject/refresh the free-tier key without interactive UI.
                st, detail = client.json("GET", f"/rest/credentials/{current['id']}?includeData=true")
                cred = detail.get("data", detail) if isinstance(detail, dict) else detail
                data = dict((cred or {}).get("data") or {})
                host = str(data.get("host") or "").rstrip("/")
                gemini_key = (env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
                changed = False
                if host != "https://generativelanguage.googleapis.com":
                    data["host"] = "https://generativelanguage.googleapis.com"
                    changed = True
                if gemini_key and data.get("apiKey") != gemini_key:
                    data["apiKey"] = gemini_key
                    changed = True
                if changed:
                    payload = {
                        "name": spec["name"],
                        "type": "googlePalmApi",
                        "data": data,
                    }
                    st, body = client.json("PATCH", f"/rest/credentials/{current['id']}", payload)
                    if st not in {200, 201}:
                        st, body = client.json("PUT", f"/rest/credentials/{current['id']}", payload)
                    print(f"Gemini credential update: {st}")
            if spec["type"] == "youTubeOAuth2Api" and (yt_client_id or yt_client_secret):
                st, detail = client.json("GET", f"/rest/credentials/{current['id']}?includeData=true")
                cred = detail.get("data", detail) if isinstance(detail, dict) else detail
                data = dict((cred or {}).get("data") or {})
                changed = False
                if yt_client_id and data.get("clientId") != yt_client_id:
                    data["clientId"] = yt_client_id
                    changed = True
                if yt_client_secret and data.get("clientSecret") != yt_client_secret:
                    data["clientSecret"] = yt_client_secret
                    changed = True
                if changed:
                    payload = {"name": spec["name"], "type": "youTubeOAuth2Api", "data": data}
                    st, body = client.json("PATCH", f"/rest/credentials/{current['id']}", payload)
                    if st not in {200, 201}:
                        st, body = client.json("PUT", f"/rest/credentials/{current['id']}", payload)
                    print(f"YouTube OAuth client fields update: {st} (Sign in with Google still required in n8n UI)")
            continue
        create_spec = dict(spec)
        if create_spec["type"] == "googlePalmApi":
            gemini_key = (env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
            if gemini_key:
                create_spec["data"] = {
                    "host": "https://generativelanguage.googleapis.com",
                    "apiKey": gemini_key,
                }
        if create_spec["type"] == "youTubeOAuth2Api" and (yt_client_id or yt_client_secret):
            create_spec["data"] = {
                "clientId": yt_client_id,
                "clientSecret": yt_client_secret,
            }
        status, body = client.json("POST", "/rest/credentials", create_spec)
        print(f"Create credential {create_spec['name']}: {status}")
        if status in {200, 201} and isinstance(body, dict):
            cred = body.get("data", body)
            cred_id = cred.get("id") if isinstance(cred, dict) else None
            if cred_id:
                mapping[create_spec["type"]] = {"id": cred_id, "name": create_spec["name"]}
        else:
            print(body)
    return mapping


def workflow_update_payload(doc: dict, current: dict) -> dict:
    """Build an n8n 2.x PUT body that includes the required versionId."""
    payload = {
        "name": doc.get("name") or current.get("name"),
        "nodes": doc.get("nodes") or current.get("nodes") or [],
        "connections": doc.get("connections") or current.get("connections") or {},
        "settings": doc.get("settings") or current.get("settings") or {"executionOrder": "v1"},
        "staticData": doc.get("staticData", current.get("staticData")),
        "pinData": doc.get("pinData", current.get("pinData") or {}),
        "versionId": current.get("versionId"),
    }
    if "active" in current:
        payload["active"] = current.get("active")
    if doc.get("meta") is not None:
        payload["meta"] = doc.get("meta")
    elif current.get("meta") is not None:
        payload["meta"] = current.get("meta")
    return payload


def attach_credentials(doc: dict, creds: dict[str, dict[str, str]]) -> dict:
    for node in doc.get("nodes", []):
        attached = node.get("credentials") or {}
        for cred_type, meta in attached.items():
            if cred_type in creds:
                meta["id"] = creds[cred_type]["id"]
                meta["name"] = creds[cred_type]["name"]
    return doc


def publish(client: N8n, workflow_id: str) -> None:
    attempts = [
        ("POST", f"/rest/workflows/{workflow_id}/publish", {"versionId": None}),
        ("POST", f"/api/v1/workflows/{workflow_id}/publish", {}),
        ("PATCH", f"/rest/workflows/{workflow_id}", {"active": True}),
        ("POST", f"/rest/workflows/{workflow_id}/activate", {}),
    ]
    for method, path, payload in attempts:
        status, body = client.json(method, path, payload)
        if status in {200, 201}:
            print(f"Published {workflow_id} via {method} {path}")
            return
        print(f"Publish attempt {method} {path} -> {status}")
    print(f"Could not auto-publish {workflow_id}. Open n8n and click Publish.")


def main() -> None:
    env = load_env()
    n8n_url = f"http://127.0.0.1:{env.get('N8N_PORT', '5678')}"
    tracking_url = f"http://127.0.0.1:{env.get('TRACKING_API_PORT', '8081')}"
    wait_http(tracking_url + "/health")
    wait_http(n8n_url + "/healthz")

    client = N8n(n8n_url)
    wait_n8n_api(client)
    email = env.get("N8N_OWNER_EMAIL", "admin@localhost.local")
    password = env.get("N8N_OWNER_PASSWORD", "")
    setup_payload = {
        "email": email,
        "firstName": env.get("N8N_OWNER_FIRST_NAME", "Store"),
        "lastName": env.get("N8N_OWNER_LAST_NAME", "Admin"),
        "password": password,
    }
    status, body = client.json("POST", "/rest/owner/setup", setup_payload)
    print(f"Owner setup: {status} {body if isinstance(body, str) else json.dumps(body)[:300]}")

    login_payloads = [
        {"email": email, "password": password},
        {"emailOrLdapLoginId": email, "password": password},
    ]
    logged_in = False
    for attempt in range(30):
        for payload in login_payloads:
            status, body = client.json("POST", "/rest/login", payload)
            print(f"Login attempt {attempt + 1}: {status}")
            if status in {200, 201} and isinstance(body, dict):
                logged_in = True
                break
        if logged_in:
            break
        time.sleep(2)
    if not logged_in:
        raise SystemExit("Could not log in to n8n. Open http://localhost:5678 and finish setup in the browser.")

    creds = ensure_credentials(client, env)

    existing_status, existing = client.json("GET", "/rest/workflows")
    existing_by_name: dict[str, str] = {}
    if existing_status == 200:
        items = existing.get("data", existing) if isinstance(existing, dict) else existing
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name") and item.get("id"):
                    existing_by_name[item["name"]] = item["id"]

    order = [
        "08-error-logger.json",
        "03-ai-content.json",
        "04-instagram.json",
        "05-facebook.json",
        "06-pinterest.json",
        "07-youtube.json",
        "09-meta-auth-probe.json",
        "10-youtube-auth-probe.json",
        "01-daily-publisher.json",
        "02-admin-control.json",
    ]
    imported: dict[str, str] = {}
    for filename in order:
        path = WORKFLOWS / filename
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc = attach_credentials(doc, creds)
        name = doc["name"]
        desired_id = doc.get("id")
        if name in existing_by_name:
            workflow_id = existing_by_name[name]
            st, full = client.json("GET", f"/rest/workflows/{workflow_id}")
            current = full.get("data", full) if isinstance(full, dict) else full
            if not isinstance(current, dict):
                print(f"Update {name}: could not load current workflow")
                continue
            payload = workflow_update_payload(doc, current)
            status, body = client.json("PATCH", f"/rest/workflows/{workflow_id}", payload)
            if status not in {200, 201}:
                status, body = client.json("PUT", f"/rest/workflows/{workflow_id}", payload)
                print(f"Updated {name}: {status} {str(body)[:400]}")
            print(f"Updated {name}: {status}")
        else:
            status, body = client.json("POST", "/rest/workflows", doc)
            print(f"Imported {name}: {status}")
            if status not in {200, 201}:
                print(body)
                continue
            workflow_id = body.get("id", desired_id) if isinstance(body, dict) else desired_id
        if isinstance(body, dict) and body.get("id"):
            workflow_id = body["id"]
        elif isinstance(body, dict) and isinstance(body.get("data"), dict) and body["data"].get("id"):
            workflow_id = body["data"]["id"]
        imported[name] = str(workflow_id)
        publish(client, str(workflow_id))

    mapping_path = ROOT / "n8n" / "imported-ids.json"
    mapping_path.write_text(json.dumps(imported, indent=2), encoding="utf-8")
    print(f"Wrote {mapping_path}")
    print("n8n: http://localhost:5678")
    print("Status: http://localhost:8081/admin")


if __name__ == "__main__":
    main()
