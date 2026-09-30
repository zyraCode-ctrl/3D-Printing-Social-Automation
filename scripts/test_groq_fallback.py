#!/usr/bin/env python3
"""Offline test of the Gemini→Groq fallback code nodes in 03 AI Content Generator (no API calls)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "03-ai-content.json"
CONTENT = {
    "vision_notes": "gold flame print",
    "instagram": {"caption": "c", "hashtags": ["#a"], "cta": "x"},
    "facebook": {"caption": "c", "hashtags": ["#a"], "cta": "x"},
    "pinterest": {"title": "t", "description": "d", "keywords": ["k"], "hashtags": ["#a"]},
    "youtube": {"title": "t", "description": "d", "tags": ["t"], "hashtags": ["#shorts"]},
}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": json.dumps(CONTENT)}]}}]}
GEMINI_503 = {"error": {"message": "Service unavailable"}}
GROQ_OK = {"model": "qwen/qwen3.8-27b", "choices": [{"message": {"content": "<think>x</think>" + json.dumps(CONTENT)}}]}
GROQ_401 = {"error": {"message": "Invalid API Key"}}
BASE = {"product_id": 1, "gemini_model": "gemini-3.6-flash", "groq_model": "qwen/qwen3.8-27b", "groq_request_body": {"model": "qwen/qwen3.8-27b"}}

HARNESS = """
const [checkCode, normCode, input, groqRaw] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const run = (code, json, refs) => new Function('$json', '$', code)(json, (n) => ({ first: () => ({ json: refs[n] }) }));
try {
  const checked = run(checkCode, input, {})[0].json;
  const normIn = checked.use_groq ? { ...checked, groq_raw: groqRaw } : checked;
  const out = run(normCode, normIn, {})[0].json;
  console.log(JSON.stringify({ use_groq: checked.use_groq, provider: out.ai_provider_used, model: out.ai_model_used, reason: out.ai_fallback_reason, platforms: Object.keys(out.content).sort(), leaked: ['groq_request_body', 'gemini_raw', 'groq_raw'].filter((k) => k in out) }));
} catch (e) { console.log(JSON.stringify({ error: e.message })); }
"""


def main() -> int:
    node_bin = shutil.which("node")
    if not node_bin:
        print("SKIP node not installed")
        return 0
    nodes = {n["name"]: n for n in json.loads(WF.read_text(encoding="utf-8"))["nodes"]}
    check = nodes["Check Gemini Output"]["parameters"]["jsCode"]
    norm = nodes["Normalize AI JSON"]["parameters"]["jsCode"]
    cases = {
        "gemini_ok": ({**BASE, "gemini_raw": GEMINI_OK}, None, lambda r: r.get("provider") == "gemini" and not r.get("use_groq")),
        "gemini_503_groq_ok": ({**BASE, "gemini_raw": GEMINI_503}, GROQ_OK, lambda r: r.get("provider") == "groq" and r.get("reason") == "Service unavailable" and not r.get("leaked")),
        "both_fail": ({**BASE, "gemini_raw": GEMINI_503}, GROQ_401, lambda r: "Groq fallback failed" in r.get("error", "")),
        "fallback_disabled": ({**BASE, "groq_request_body": None, "gemini_raw": GEMINI_503}, None, lambda r: "Groq fallback disabled" in r.get("error", "")),
    }
    failed = False
    for name, (job, groq_raw, ok) in cases.items():
        proc = subprocess.run([node_bin, "-e", HARNESS], input=json.dumps([check, norm, job, groq_raw]), capture_output=True, text=True)
        result = json.loads(proc.stdout.strip() or "{}")
        passed = ok(result)
        failed |= not passed
        print("PASS" if passed else "FAIL", name, json.dumps(result))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
