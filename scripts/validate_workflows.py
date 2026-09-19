#!/usr/bin/env python3
"""Validate n8n workflow JSON files without starting Docker."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "n8n" / "workflows"
REQUIRED = [
    "id",
    "name",
    "nodes",
    "connections",
    "settings",
]


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    doc = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED:
        if key not in doc:
            errors.append(f"{path.name}: missing {key}")
    names = [node.get("name") for node in doc.get("nodes", [])]
    if len(names) != len(set(names)):
        errors.append(f"{path.name}: duplicate node names")
    for node in doc.get("nodes", []):
        for field in ("id", "name", "type", "typeVersion", "position"):
            if field not in node:
                errors.append(f"{path.name}: node missing {field}")
    known = set(names)
    for source, spec in doc.get("connections", {}).items():
        if source not in known:
            errors.append(f"{path.name}: connection source not found: {source}")
        for group in spec.get("main", []):
            for link in group:
                if link.get("node") not in known:
                    errors.append(f"{path.name}: connection target not found: {link.get('node')}")
    return errors


def validate_production_ai(ai_path: Path, daily_path: Path) -> list[str]:
    errors: list[str] = []
    ai = json.loads(ai_path.read_text(encoding="utf-8"))
    daily = json.loads(daily_path.read_text(encoding="utf-8"))
    ai_blob = json.dumps(ai)
    daily_blob = json.dumps(daily)
    if "googlePalmApi" not in ai_blob or "Gemini Vision" not in ai_blob:
        errors.append(f"{ai_path.name}: production AI must call Gemini via googlePalmApi")
    if "generativelanguage.googleapis.com" not in ai_blob and "request_url" not in ai_blob:
        errors.append(f"{ai_path.name}: Gemini generateContent URL is missing")
    if "gemini-3.6-flash" not in ai_blob:
        errors.append(f"{ai_path.name}: vision model gemini-3.6-flash is missing")
    for banned in ("openAiApi", "api.openai.com", "/ai/mock", "OpenAI Vision", "openai_body"):
        if banned in ai_blob:
            errors.append(f"{ai_path.name}: production AI still contains {banned}")
    if "/ai/mock" in daily_blob:
        errors.append(f"{daily_path.name}: daily publisher still calls mock AI")
    if "/drive/public-list" not in daily_blob:
        errors.append(f"{daily_path.name}: daily publisher must list the public Drive folder via tracking-api")
    if "n8n-nodes-base.googleDrive" in daily_blob:
        errors.append(f"{daily_path.name}: daily publisher must not use Google Drive OAuth nodes for dry-run media")
    if "Build Preview Payload" not in daily_blob:
        errors.append(f"{daily_path.name}: Build Preview Payload node is required for safe Save Preview JSON")
    save_preview = next((n for n in daily.get("nodes", []) if n.get("name") == "Save Preview"), None)
    if not save_preview:
        errors.append(f"{daily_path.name}: Save Preview node is missing")
    else:
        params = save_preview.get("parameters") or {}
        body = str(params.get("body") or params.get("jsonBody") or "")
        if params.get("contentType") != "raw":
            errors.append(f"{daily_path.name}: Save Preview must use raw JSON body content type")
        if "JSON.stringify($json.previewBody)" not in body.replace(" ", ""):
            # allow spaced variant
            if "previewBody" not in body or "JSON.stringify" not in body:
                errors.append(f"{daily_path.name}: Save Preview must JSON.stringify($json.previewBody) as raw body")
        if "specifyBody" in params and params.get("specifyBody") == "json" and "jsonBody" in params:
            errors.append(f"{daily_path.name}: Save Preview must not use jsonBody field")
    if "Generate AI Content" not in daily_blob:
        errors.append(f"{daily_path.name}: daily publisher must call the AI subworkflow")
    names = {node.get("name") for node in ai.get("nodes", [])}
    if "Gemini Vision" not in names:
        errors.append(f"{ai_path.name}: Gemini Vision node is missing")
    if "OpenAI Vision" in names:
        errors.append(f"{ai_path.name}: OpenAI Vision node must be removed")
    ig_path = ROOT / "04-instagram.json"
    ig_blob = ig_path.read_text(encoding="utf-8") if ig_path.exists() else ""
    if "facebookGraphApi" not in ig_blob:
        errors.append("04-instagram.json: Instagram publisher must use facebookGraphApi")
    if "media_publish" not in ig_blob:
        errors.append("04-instagram.json: Instagram two-step media_publish is missing")
    fb_path = ROOT / "05-facebook.json"
    fb_blob = fb_path.read_text(encoding="utf-8") if fb_path.exists() else ""
    if "facebookGraphApi" not in fb_blob:
        errors.append("05-facebook.json: Facebook publisher must use facebookGraphApi")
    if not (ROOT / "09-meta-auth-probe.json").exists():
        errors.append("09-meta-auth-probe.json is missing")
    return errors


def main() -> None:
    files = sorted(ROOT.glob("*.json"))
    if not files:
        raise SystemExit("No workflow JSON files found. Run scripts/generate_workflows.py first.")
    errors: list[str] = []
    for path in files:
        file_errors = validate(path)
        errors.extend(file_errors)
        status = "OK" if not file_errors else "FAIL"
        print(f"{status} {path.name}")
    ai_path = ROOT / "03-ai-content.json"
    daily_path = ROOT / "01-daily-publisher.json"
    if ai_path.exists() and daily_path.exists():
        ai_errors = validate_production_ai(ai_path, daily_path)
        errors.extend(ai_errors)
        print("OK production AI uses Gemini" if not ai_errors else "FAIL production AI checks")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(files)} workflow files.")


if __name__ == "__main__":
    main()
