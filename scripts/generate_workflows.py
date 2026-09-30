#!/usr/bin/env python3
"""Create importable n8n 2.39 workflow JSON files."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "n8n" / "workflows"

WF = {
    "daily": "3dprDailyPub0001",
    "admin": "3dprAdminCtl0002",
    "ai": "3dprAiContent003",
    "instagram": "3dprInstagram004",
    "facebook": "3dprFacebook005",
    "pinterest": "3dprPinterest06",
    "youtube": "3dprYouTube0007",
    "error": "3dprErrorLog008",
    "pinterest_probe": "3dprPinAuthProbe11",
    "groq_probe": "3dprGroqAuthProbe12",
    "live_reel": "3dprLiveReel00013",
    "live_pin": "3dprLivePinVid014",
    "live_fb": "3dprLiveFbReel015",
    "queue_prep": "3dprQueuePrep016",
}

TRACKING = "http://tracking-api:8081"
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "googleDriveOAuth2Api", "name": "Google Drive account"}}
GEMINI_CRED = {"googlePalmApi": {"id": "googlePalmApi", "name": "Google Gemini account"}}
META_CRED = {"facebookGraphApi": {"id": "facebookGraphApi", "name": "Facebook Graph account"}}
PINTEREST_CRED = {"oAuth2Api": {"id": "oAuth2Api", "name": "Pinterest account"}}
GROQ_CRED = {"httpHeaderAuth": {"id": "httpHeaderAuth", "name": "Groq account"}}
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
NOT_EMPTY = {"type": "string", "operation": "notEmpty", "singleValue": True}


def nid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "n8n:" + ":".join(parts)))


def node(workflow: str, name: str, type_name: str, type_version: float | int, parameters: dict, position: list[int], **extra) -> dict:
    data = {
        "id": nid(workflow, name),
        "name": name,
        "type": type_name,
        "typeVersion": type_version,
        "position": position,
        "parameters": parameters,
    }
    data.update(extra)
    return data


def sticky(workflow: str, name: str, content: str, position: list[int], width: int = 300, height: int = 260, color: int = 6) -> dict:
    return node(
        workflow,
        name,
        "n8n-nodes-base.stickyNote",
        1,
        {"content": content, "width": width, "height": height, "color": color},
        position,
    )


def http_get(workflow: str, name: str, url: str, position: list[int], **extra) -> dict:
    return node(
        workflow,
        name,
        "n8n-nodes-base.httpRequest",
        4.5,
        {"method": "GET", "url": url, "options": {"timeout": 60000}},
        position,
        **extra,
    )


def http_post_json(workflow: str, name: str, url: str, json_body: str, position: list[int], **extra) -> dict:
    params = {
        "method": "POST",
        "url": url,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": json_body,
        "options": {"timeout": 120000},
    }
    return node(workflow, name, "n8n-nodes-base.httpRequest", 4.5, params, position, **extra)


def http_post_json_object(workflow: str, name: str, url: str, object_expression: str, position: list[int], **extra) -> dict:
    """POST a JS object via raw JSON string body so n8n does not validate jsonBody as a JSON literal."""
    params = {
        "method": "POST",
        "url": url,
        "sendBody": True,
        "contentType": "raw",
        "rawContentType": "application/json",
        "body": f"={{{{ JSON.stringify({object_expression}) }}}}",
        "options": {"timeout": 120000},
    }
    return node(workflow, name, "n8n-nodes-base.httpRequest", 4.5, params, position, **extra)


def code(workflow: str, name: str, js: str, position: list[int]) -> dict:
    return node(workflow, name, "n8n-nodes-base.code", 2, {"jsCode": js.strip() + "\n"}, position)


def iff(workflow: str, name: str, left: str, operator: dict, right, position: list[int]) -> dict:
    condition = {
        "id": nid(workflow, name, "cond"),
        "leftValue": left,
        "rightValue": right,
        "operator": operator,
    }
    return node(
        workflow,
        name,
        "n8n-nodes-base.if",
        2.3,
        {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [condition],
                "combinator": "and",
            },
            "options": {},
        },
        position,
    )


def switch_bool(workflow: str, name: str, left: str, true_key: str, false_key: str, position: list[int]) -> dict:
    def cond(value_name: str, op: str) -> dict:
        return {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [
                    {
                        "id": nid(workflow, name, value_name),
                        "leftValue": left,
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": op, "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "renameOutput": True,
            "outputKey": value_name,
        }

    return node(
        workflow,
        name,
        "n8n-nodes-base.switch",
        3.4,
        {"rules": {"values": [cond(true_key, "true"), cond(false_key, "false")]}, "options": {"fallbackOutput": "extra"}},
        position,
    )


def switch_equals(workflow: str, name: str, left: str, rules: list[tuple[str, str]], position: list[int]) -> dict:
    values = []
    for key, right in rules:
        values.append(
            {
                "conditions": {
                    "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose", "version": 2},
                    "conditions": [
                        {
                            "id": nid(workflow, name, key),
                            "leftValue": left,
                            "rightValue": right,
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                    "combinator": "and",
                },
                "renameOutput": True,
                "outputKey": key,
            }
        )
    return node(
        workflow,
        name,
        "n8n-nodes-base.switch",
        3.4,
        {"rules": {"values": values}, "options": {"fallbackOutput": "extra"}},
        position,
    )


def execute_sub(workflow: str, name: str, target_id: str, target_name: str, position: list[int], *, continue_on_error: bool = False) -> dict:
    data = node(
        workflow,
        name,
        "n8n-nodes-base.executeWorkflow",
        1.3,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": target_id, "mode": "id", "cachedResultName": target_name},
            "options": {"waitForSubWorkflow": True},
        },
        position,
    )
    if continue_on_error:
        data["onError"] = "continueRegularOutput"
    return data


def trigger_sub(workflow: str, position: list[int]) -> dict:
    return node(
        workflow,
        "When Called by Another Workflow",
        "n8n-nodes-base.executeWorkflowTrigger",
        1.2,
        {"inputSource": "passthrough"},
        position,
    )


def noop(workflow: str, name: str, position: list[int]) -> dict:
    return node(workflow, name, "n8n-nodes-base.noOp", 1, {}, position)


def connections(pairs: list[tuple]) -> dict:
    graph: dict = {}
    for item in pairs:
        if len(item) == 2:
            src, dest = item
            src_index = 0
        else:
            src, dest, src_index = item
        graph.setdefault(src, {"main": []})
        mains = graph[src]["main"]
        while len(mains) <= src_index:
            mains.append([])
        mains[src_index].append({"node": dest, "type": "main", "index": 0})
    return graph


def workflow(name: str, wf_id: str, nodes: list[dict], pairs: list[tuple], extra_settings: dict | None = None) -> dict:
    settings = {
        "executionOrder": "v1",
        "timezone": "Asia/Kolkata",
        "callerPolicy": "workflowsFromSameOwner",
        "availableInMCP": False,
        "errorWorkflow": WF["error"],
    }
    if extra_settings:
        settings.update(extra_settings)
    return {
        "id": wf_id,
        "name": name,
        "active": False,
        "isArchived": False,
        "nodes": nodes,
        "connections": connections(pairs),
        "settings": settings,
        "pinData": {},
        "versionId": nid("version", wf_id),
        "meta": {"templateCredsSetupCompleted": False},
        "tags": [],
    }


TRUE = {"type": "boolean", "operation": "true", "singleValue": True}
EQ_STR = {"type": "string", "operation": "equals"}


def error_workflow() -> dict:
    nodes = [
        sticky("error", "Note", "## Error Logger\nCatches failed executions and writes them to SQLite via the tracking API.", [-280, -160], 280, 180, 3),
        node("error", "Error Trigger", "n8n-nodes-base.errorTrigger", 1, {}, [0, 0]),
        http_post_json(
            "error",
            "Log Error",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'error', event: 'workflow_error', product_id: $json.execution?.id ? undefined : $json.product_id, message: $json.execution?.error?.message || $json.message || 'Workflow failed', details: $json }) }}",
            [260, 0],
        ),
    ]
    return workflow("08 Error Logger", WF["error"], nodes, [("Error Trigger", "Log Error")], {"errorWorkflow": ""})


def ai_workflow() -> dict:
    nodes = [
        sticky(
            "ai",
            "Note",
            "## Vision AI (Gemini free tier)\nInspects the Google Drive product image (or a video frame).\n\n**Provider:** Google Gemini via n8n credential **Google Gemini account** (`googlePalmApi`).\n**Model:** `gemini-3.6-flash` (vision, Google AI Studio free tier), with free-tier fallbacks if Google returns high-demand/404.\n\n**Fallback:** if every Gemini model fails, the same prompt + schema + image go to **Groq** (`GROQ_MODEL`, default `qwen/qwen3.8-27b`) in one call via n8n credential **Groq account** (Header Auth). Disable with `AI_FALLBACK_PROVIDER=none`.\n\nChatGPT Pro is not used. OpenAI API is not used. No mock AI.\nEnglish only. USA, Canada, UK, Australia. No invented specs. No website URL.",
            [-420, -280],
            400,
            360,
            5,
        ),
        trigger_sub("ai", [0, 0]),
        http_get("ai", "Load Prompts", f"{TRACKING}/config", [240, 0]),
        code(
            "ai",
            "Build Provider Payload",
            """
const job = $('When Called by Another Workflow').first().json;
const config = $json;
if (!job.vision_base64) {
  throw new Error('No media was passed to the AI step. Download the Google Drive file first.');
}
const provider = String(config.ai_provider || 'gemini').toLowerCase();
const prompts = config.prompts || {};
const platformGuide = [prompts.instagram, prompts.facebook, prompts.pinterest, prompts.youtube].filter(Boolean).join('\\n\\n');
const schema = [
  'Analyze the attached product media. Write English only (international English for USA, Canada, UK, Australia).',
  'Use natural terms like desk setup, home office, or workspace only when they fit what is visible.',
  'Do not invent specifications, materials, sizes, prices, print times, shipping, stock, or brand names.',
  'Do not include a website, URL, or link.',
  'Each platform must have distinct wording and non-identical hashtag sets.',
  'Instagram caption must include clean line breaks (use \\n\\n between short paragraphs), at most 1-2 emojis, 5-8 hashtags, and a strong non-spammy CTA.',
  'Facebook caption should be a bit longer than Instagram, 4-6 hashtags (may share a few core tags but not the full identical list), and a natural CTA.',
  'Pinterest needs SEO title, SEO description, 5-8 keyword phrases, and 3-5 hashtags.',
  'YouTube in this project means YouTube Shorts only (never long-form). Provide a short attention-grabbing Shorts title (~70 chars max), a concise 2-4 line Shorts description, 3-6 lowercase hashtags including #shorts, and 5-10 YouTube tags/keywords.',
  platformGuide,
  'Return JSON only with this exact shape:',
  '{',
  '  "vision_notes": "what is actually visible",',
  '  "instagram": {"caption": "", "hashtags": [], "cta": ""},',
  '  "facebook": {"caption": "", "hashtags": [], "cta": ""},',
  '  "pinterest": {"title": "", "description": "", "keywords": [], "hashtags": []},',
  '  "youtube": {"title": "", "description": "", "tags": [], "hashtags": []}',
  '}',
  'Product ID ' + job.product_id + '. Filename ' + job.filename + '. Media type ' + job.media_type + '. If media is video, treat YouTube copy as a Short.'
].join('\\n');
const systemPrompt = prompts.system || 'You are a social copywriter for a 3D printing store. Write natural international English for USA, Canada, UK, and Australia. Analyze only what you see. Never invent specs, prices, or shipping. Never add a URL. YouTube means YouTube Shorts only.';
const mime = job.vision_mime || 'image/jpeg';
let request_url = '';
let request_body = {};
let gemini_model = '';
let gemini_fallback_models = [];
if (provider === 'gemini') {
  const host = String(config.gemini_host || 'https://generativelanguage.googleapis.com').replace(/\\/$/, '');
  gemini_model = config.gemini_model || 'gemini-3.6-flash';
  gemini_fallback_models = ['gemini-flash-latest', 'gemini-3.8-flash', 'gemini-3.5-flash'].filter((m) => m !== gemini_model);
  request_url = host + '/v1beta/models/' + gemini_model + ':generateContent';
  request_body = {
    systemInstruction: { parts: [{ text: systemPrompt }] },
    contents: [{
      role: 'user',
      parts: [
        { text: schema },
        { inlineData: { mimeType: mime, data: job.vision_base64 } }
      ]
    }],
    generationConfig: {
      responseMimeType: 'application/json',
      temperature: 0.7
    }
  };
}
const fallbackProvider = String(config.ai_fallback_provider || 'groq').toLowerCase();
const groq_model = config.groq_model || 'qwen/qwen3.8-27b';
const groq_request_body = fallbackProvider === 'groq' ? {
  model: groq_model,
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: [
      { type: 'text', text: schema },
      { type: 'image_url', image_url: { url: 'data:' + mime + ';base64,' + job.vision_base64 } }
    ] }
  ],
  response_format: { type: 'json_object' },
  temperature: 0.7,
  max_completion_tokens: 2048,
  ...(groq_model.startsWith('qwen/') ? { reasoning_effort: 'none' } : {}),
} : null;
const payload = { ...job, config, ai_provider: provider, request_url, request_body, gemini_model, gemini_fallback_models, gemini_host: String(config.gemini_host || 'https://generativelanguage.googleapis.com').replace(/\\/$/, ''), ai_fallback_provider: fallbackProvider, groq_model, groq_request_body };
delete payload.vision_base64;
return [{ json: payload }];
""",
            [500, 0],
        ),
        switch_equals("ai", "Provider Switch", "={{ $json.ai_provider }}", [("gemini", "gemini")], [760, 0]),
        node(
            "ai",
            "Gemini Vision",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": "={{ $json.request_url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "googlePalmApi",
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($json.request_body) }}",
                "options": {"timeout": 120000},
            },
            [1020, -80],
            credentials=GEMINI_CRED,
            retryOnFail=True,
            maxTries=4,
            waitBetweenTries=5000,
            onError="continueRegularOutput",
        ),
        code(
            "ai",
            "Evaluate Gemini Result",
            """
const job = $('Build Provider Payload').first().json;
const raw = $json;
const hasCandidates = !!(raw && raw.candidates && raw.candidates[0]);
if (hasCandidates) {
  return [{ json: { ...job, gemini_raw: raw, need_fallback: false, gemini_model_used: job.gemini_model } }];
}
const fallbacks = job.gemini_fallback_models || [];
const next = fallbacks[0];
const detail = (raw && raw.error && (raw.error.message || raw.error.status))
  || (raw && raw.message)
  || (raw && raw.description)
  || JSON.stringify(raw || {}).slice(0, 300);
if (!next) {
  return [{ json: { ...job, gemini_raw: raw, need_fallback: false, gemini_primary_error: String(detail).slice(0, 300) } }];
}
return [{ json: {
  ...job,
  gemini_raw: raw,
  need_fallback: true,
  gemini_primary_error: String(detail).slice(0, 300),
  gemini_model_used: next,
  request_url: String(job.gemini_host || 'https://generativelanguage.googleapis.com').replace(/\\/$/, '') + '/v1beta/models/' + next + ':generateContent'
} }];
""",
            [1260, -80],
        ),
        switch_bool("ai", "Need Gemini Fallback?", "={{ $json.need_fallback }}", "yes", "no", [1500, -80]),
        node(
            "ai",
            "Gemini Vision Fallback",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": "={{ $json.request_url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "googlePalmApi",
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($json.request_body) }}",
                "options": {"timeout": 120000},
            },
            [1740, -200],
            credentials=GEMINI_CRED,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            onError="continueRegularOutput",
        ),
        code(
            "ai",
            "Attach Fallback Raw",
            """
const job = $('Evaluate Gemini Result').first().json;
return [{ json: { ...job, gemini_raw: $json } }];
""",
            [1980, -200],
        ),
        node(
            "ai",
            "Stop Unknown Provider",
            "n8n-nodes-base.stopAndError",
            1,
            {
                "errorType": "errorMessage",
                "errorMessage": "Unknown AI provider. The production path uses Google Gemini free tier through n8n. OpenAI API is not used. Mock AI is not used.",
            },
            [1020, 160],
        ),
        code(
            "ai",
            "Check Gemini Output",
            """
const job = $json;
const raw = job.gemini_raw || {};
const ok = Boolean(raw.candidates && raw.candidates[0] && raw.candidates[0].content);
const err = raw.error || {};
const detail = ok ? null : String(err.description || err.message || err.status || raw.message || job.gemini_primary_error || JSON.stringify(raw).slice(0, 300)).slice(0, 300);
return [{ json: { ...job, gemini_ok: ok, gemini_error: detail, use_groq: !ok && Boolean(job.groq_request_body) } }];
""",
            [2220, -80],
        ),
        switch_bool("ai", "Use Groq Fallback?", "={{ $json.use_groq }}", "yes", "no", [2460, -80]),
        node(
            "ai",
            "Groq Vision Fallback",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": GROQ_CHAT_URL,
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($json.groq_request_body) }}",
                "options": {"timeout": 120000},
            },
            [2700, -200],
            credentials=GROQ_CRED,
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=5000,
            onError="continueRegularOutput",
        ),
        code(
            "ai",
            "Attach Groq Raw",
            """
const job = $('Check Gemini Output').first().json;
return [{ json: { ...job, groq_raw: $json } }];
""",
            [2940, -200],
        ),
        code(
            "ai",
            "Normalize AI JSON",
            """
const job = $json;
let text = '';
let provider = 'gemini';
let modelUsed = job.gemini_model_used || job.gemini_model || 'gemini-3.6-flash';
if (job.groq_raw) {
  const g = job.groq_raw;
  const gErr = g.error ? String(g.error.description || g.error.message || JSON.stringify(g.error)) : null;
  if (gErr) {
    throw new Error('Gemini failed (' + (job.gemini_error || 'unknown') + ') and Groq fallback failed: ' + gErr + '. Check Credentials → Groq account.');
  }
  text = (((g.choices || [])[0] || {}).message || {}).content || '';
  provider = 'groq';
  modelUsed = g.model || job.groq_model;
  if (!text) throw new Error('Groq returned no content after Gemini failed (' + (job.gemini_error || 'unknown') + ').');
} else {
  if (!job.gemini_ok) {
    throw new Error('Gemini error: ' + (job.gemini_error || 'no content') + (job.groq_request_body ? '' : ' (Groq fallback disabled: AI_FALLBACK_PROVIDER=none)'));
  }
  const raw = job.gemini_raw;
  text = raw.candidates[0].content.parts ? raw.candidates[0].content.parts.map((part) => part.text || '').join('') : '';
  if (!text) {
    throw new Error('Gemini returned no content. Open Credentials → Google Gemini account and paste a free Google AI Studio API key.');
  }
}
text = String(text).replace(/<think>[\\s\\S]*?<\\/think>/gi, '').trim().replace(/^```json\\s*/i, '').replace(/```$/i, '').trim();
let content;
try { content = JSON.parse(text); }
catch (e) { throw new Error(provider + ' did not return valid JSON: ' + e.message); }
if (!content.instagram || !content.facebook || !content.pinterest || !content.youtube) {
  throw new Error(provider + ' JSON is missing a platform block. Refusing to invent copy.');
}
const fallbackReason = provider === 'groq' ? job.gemini_error : null;
for (const key of ['request_body', 'groq_request_body', 'vision_base64', 'gemini_raw', 'groq_raw', 'gemini_fallback_models', 'need_fallback', 'use_groq', 'gemini_ok']) {
  delete job[key];
}
return [{ json: {
  ...job,
  content,
  ai_provider_used: provider,
  ai_model_used: modelUsed,
  gemini_model_used: provider === 'gemini' ? modelUsed : null,
  ai_fallback_reason: fallbackReason,
  vision_notes: content.vision_notes
} }];
""",
            [3180, -80],
        ),
    ]
    pairs = [
        ("When Called by Another Workflow", "Load Prompts"),
        ("Load Prompts", "Build Provider Payload"),
        ("Build Provider Payload", "Provider Switch"),
        ("Provider Switch", "Gemini Vision", 0),
        ("Provider Switch", "Stop Unknown Provider", 1),
        ("Gemini Vision", "Evaluate Gemini Result"),
        ("Evaluate Gemini Result", "Need Gemini Fallback?"),
        ("Need Gemini Fallback?", "Gemini Vision Fallback", 0),
        ("Need Gemini Fallback?", "Check Gemini Output", 1),
        ("Gemini Vision Fallback", "Attach Fallback Raw"),
        ("Attach Fallback Raw", "Check Gemini Output"),
        ("Check Gemini Output", "Use Groq Fallback?"),
        ("Use Groq Fallback?", "Groq Vision Fallback", 0),
        ("Use Groq Fallback?", "Normalize AI JSON", 1),
        ("Groq Vision Fallback", "Attach Groq Raw"),
        ("Attach Groq Raw", "Normalize AI JSON"),
    ]
    return workflow("03 AI Content Generator", WF["ai"], nodes, pairs)

def platform_workflow(key: str, wf_id: str, title: str, note: str, publish_url: str, publish_body: str, skip_reason_field: str) -> dict:
    nodes = [
        sticky(key, "Note", note, [-340, -200], 320, 300, 4),
        trigger_sub(key, [0, 0]),
        http_get(
            key,
            "Duplicate Check",
            f"={{{{ '{TRACKING}/products/' + $json.product_id + '/can-publish?platform={key}' }}}}",
            [240, 0],
        ),
        iff(key, "Allowed to Publish?", "={{ $json.allowed }}", TRUE, True, [500, 0]),
        code(
            key,
            "Blocked Result",
            f"""
const job = $('When Called by Another Workflow').first().json;
const check = $json;
return [{{ json: {{
  product_id: job.product_id,
  platform: '{key}',
  status: check.dry_run ? 'dry_run_skipped' : (check.status === 'published' ? 'published' : 'skipped'),
  skipped: true,
  reason: check.reason,
  post_id: check.post_id || null,
  job
}} }}];
""",
            [760, 180],
        ),
        http_post_json(
            key,
            "Publish Official API",
            publish_url,
            publish_body,
            [760, -40],
            onError="continueRegularOutput",
        ),
        code(
            key,
            "Interpret Result",
            f"""
const job = $('When Called by Another Workflow').first().json;
const response = $json;
const err = response.error || response.error_message || response.message;
const failed = Boolean(response.error) || (response.error && response.error.message);
let postId = response.id || response.post_id || (response.permalink_url ? String(response.id) : null);
if (response.creation_id) postId = response.creation_id;
if (response.data && response.data.id) postId = response.data.id;
if ({skip_reason_field}) {{
  return [{{ json: {{ product_id: job.product_id, platform: '{key}', status: 'skipped', skipped: true, reason: 'Media type not supported on this platform', job }} }}];
}}
if (failed || (!postId && response.error)) {{
  return [{{ json: {{ product_id: job.product_id, platform: '{key}', status: 'failed', error_message: err || JSON.stringify(response), job }} }}];
}}
if (!postId && response.status !== 'published') {{
  // Graph-style publish can return an id on success; if the body looks empty, treat as failure with the raw payload.
  const looksOk = response.id || response.permalink || response.videoId || (response.headers && false);
  if (!looksOk) {{
    return [{{ json: {{ product_id: job.product_id, platform: '{key}', status: 'failed', error_message: err || ('No post id in response: ' + JSON.stringify(response).slice(0, 500)), job }} }}];
  }}
}}
return [{{ json: {{ product_id: job.product_id, platform: '{key}', status: 'published', post_id: postId, job }} }}];
""",
            [1020, -40],
        ),
        http_post_json(
            key,
            "Store Platform Result",
            f"={{{{ '{TRACKING}/products/' + $json.product_id + '/platform-result' }}}}",
            "={{ JSON.stringify({ platform: $json.platform, status: $json.status === 'dry_run_skipped' ? 'pending' : ($json.status === 'skipped' ? 'skipped' : $json.status), post_id: $json.post_id || null, error_message: $json.error_message || $json.reason || null }) }}",
            [1280, 40],
        ),
    ]
    pairs = [
        ("When Called by Another Workflow", "Duplicate Check"),
        ("Duplicate Check", "Allowed to Publish?"),
        ("Allowed to Publish?", "Publish Official API", 0),
        ("Allowed to Publish?", "Blocked Result", 1),
        ("Publish Official API", "Interpret Result"),
        ("Interpret Result", "Store Platform Result"),
        ("Blocked Result", "Store Platform Result"),
    ]
    return workflow(title, wf_id, nodes, pairs)


def instagram_workflow() -> dict:
    note = """## Instagram (official Meta Graph API)

Uses Facebook Login + Instagram professional account linked to a Page.

Flow (only when DRY_RUN=false):
1. Create media container `POST /{ig-user-id}/media`
2. Publish container `POST /{ig-user-id}/media_publish`

Requires:
- n8n credential **Facebook Graph account** (Page access token)
- `INSTAGRAM_BUSINESS_ACCOUNT_ID` and `META_GRAPH_VERSION` in `.env`
- Publicly reachable media URL (Drive share / tunnel) for live posts

`DRY_RUN=true` stops at Duplicate Check — nothing is posted.
"""
    nodes = [
        sticky("instagram", "Note", note, [-360, -240], 360, 340, 4),
        trigger_sub("instagram", [0, 0]),
        http_get(
            "instagram",
            "Duplicate Check",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/can-publish?platform=instagram' }}",
            [240, 0],
        ),
        iff("instagram", "Allowed to Publish?", "={{ $json.allowed }}", TRUE, True, [500, 0]),
        code(
            "instagram",
            "Blocked Result",
            """
const job = $('When Called by Another Workflow').first().json;
const check = $json;
return [{ json: {
  product_id: job.product_id,
  platform: 'instagram',
  status: check.dry_run ? 'dry_run_skipped' : (check.status === 'published' ? 'published' : 'skipped'),
  skipped: true,
  reason: check.reason,
  post_id: check.post_id || null
} }];
""",
            [760, 220],
        ),
        http_get("instagram", "Load Config", f"{TRACKING}/config", [760, -120]),
        http_get(
            "instagram",
            "Load Preview",
            "={{ '" + TRACKING + "/previews/' + $('When Called by Another Workflow').first().json.product_id }}",
            [980, -120],
        ),
        code(
            "instagram",
            "Prepare Instagram Job",
            """
const job = $('When Called by Another Workflow').first().json;
const config = $('Load Config').first().json;
const preview = $json;
const content = (preview && preview.content) || job.content || {};
const ig = content.instagram || {};
if (!config.instagram_business_account_id) {
  throw new Error('INSTAGRAM_BUSINESS_ACCOUNT_ID is missing in .env / tracking config.');
}
const caption = [ig.caption, (ig.hashtags || []).join(' '), ig.cta].filter(Boolean).join('\\n\\n');
const driveId = preview.drive_file_id || job.drive_file_id || null;
const publicUrl = job.public_media_url
  || (driveId ? ('https://drive.google.com/uc?export=download&id=' + driveId) : null);
if (!publicUrl) {
  throw new Error('No public_media_url / drive_file_id available for Instagram Graph publishing.');
}
const isImage = String(preview.media_type || job.media_type || '') === 'image'
  || Boolean(job.image_file && !job.video_file);
const version = config.meta_graph_version || 'v22.0';
const igUser = config.instagram_business_account_id;
const containerBody = isImage
  ? { image_url: publicUrl, caption }
  : { media_type: 'REELS', video_url: publicUrl, caption };
return [{ json: {
  product_id: job.product_id,
  platform: 'instagram',
  config,
  preview,
  content,
  caption,
  public_media_url: publicUrl,
  drive_file_id: driveId,
  is_image: isImage,
  container_url: 'https://graph.facebook.com/' + version + '/' + igUser + '/media',
  publish_url: 'https://graph.facebook.com/' + version + '/' + igUser + '/media_publish',
  container_body: containerBody
} }];
""",
            [1220, -120],
        ),
        node(
            "instagram",
            "Create Media Container",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": "={{ $json.container_url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "facebookGraphApi",
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($json.container_body) }}",
                "options": {"timeout": 180000},
            },
            [1480, -120],
            credentials=META_CRED,
            onError="continueRegularOutput",
        ),
        code(
            "instagram",
            "Build Publish Body",
            """
const prepared = $('Prepare Instagram Job').first().json;
const created = $json;
if (created.error) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'instagram',
    status: 'failed',
    error_message: created.error.message || JSON.stringify(created.error),
    skip_publish: true
  } }];
}
const creationId = created.id || created.creation_id;
if (!creationId) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'instagram',
    status: 'failed',
    error_message: 'Instagram container create returned no id: ' + JSON.stringify(created).slice(0, 400),
    skip_publish: true
  } }];
}
return [{ json: {
  ...prepared,
  creation_id: creationId,
  skip_publish: false,
  publish_body: { creation_id: creationId }
} }];
""",
            [1720, -120],
        ),
        iff("instagram", "Container OK?", "={{ !$json.skip_publish }}", TRUE, True, [1960, -120]),
        node(
            "instagram",
            "Publish Media Container",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": "={{ $json.publish_url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "facebookGraphApi",
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($json.publish_body) }}",
                "options": {"timeout": 180000},
            },
            [2200, -200],
            credentials=META_CRED,
            onError="continueRegularOutput",
        ),
        code(
            "instagram",
            "Interpret Result",
            """
const prepared = $('Prepare Instagram Job').first().json;
const built = $('Build Publish Body').first().json;
const response = $json;
if (built.skip_publish) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'instagram',
    status: 'failed',
    error_message: built.error_message || 'container create failed'
  } }];
}
if (response.error) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'instagram',
    status: 'failed',
    error_message: response.error.message || JSON.stringify(response.error)
  } }];
}
const postId = response.id || response.post_id || null;
if (!postId) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'instagram',
    status: 'failed',
    error_message: 'No Instagram media id in publish response: ' + JSON.stringify(response).slice(0, 400)
  } }];
}
return [{ json: {
  product_id: prepared.product_id,
  platform: 'instagram',
  status: 'published',
  post_id: String(postId)
} }];
""",
            [2440, -120],
        ),
        http_post_json(
            "instagram",
            "Store Platform Result",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/platform-result' }}",
            "={{ JSON.stringify({ platform: $json.platform, status: $json.status === 'dry_run_skipped' ? 'pending' : ($json.status === 'skipped' ? 'skipped' : $json.status), post_id: $json.post_id || null, error_message: $json.error_message || $json.reason || null }) }}",
            [2680, 40],
        ),
    ]
    pairs = [
        ("When Called by Another Workflow", "Duplicate Check"),
        ("Duplicate Check", "Allowed to Publish?"),
        ("Allowed to Publish?", "Load Config", 0),
        ("Allowed to Publish?", "Blocked Result", 1),
        ("Load Config", "Load Preview"),
        ("Load Preview", "Prepare Instagram Job"),
        ("Prepare Instagram Job", "Create Media Container"),
        ("Create Media Container", "Build Publish Body"),
        ("Build Publish Body", "Container OK?"),
        ("Container OK?", "Publish Media Container", 0),
        ("Container OK?", "Interpret Result", 1),
        ("Publish Media Container", "Interpret Result"),
        ("Interpret Result", "Store Platform Result"),
        ("Blocked Result", "Store Platform Result"),
    ]
    return workflow("04 Instagram Publisher", WF["instagram"], nodes, pairs)


PAGE_TOKEN_HEADER = {"name": "Authorization", "value": "={{ 'OAuth ' + ($('Get Page Token').first().json.access_token || 'missing') }}"}


def page_token_guard_nodes(wf: str, version_expr: str, page_id_expr: str, position: list[int]) -> list[dict]:
    """Get Page Token → Verify Page Identity → Page Guard (guard_ok only if the token acts as the configured Page)."""
    x, y = position
    graph = "'https://graph.facebook.com/' + (" + version_expr + " || 'v22.0')"
    return [
        node(
            wf,
            "Get Page Token",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "={{ " + graph + " + '/' + " + page_id_expr + " + '?fields=id,name,access_token' }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "facebookGraphApi",
                "options": {"timeout": 60000},
            },
            [x, y],
            credentials=META_CRED,
            onError="continueRegularOutput",
        ),
        node(
            wf,
            "Verify Page Identity",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "={{ " + graph + " + '/me?fields=id,name' }}",
                "sendHeaders": True,
                "headerParameters": {"parameters": [PAGE_TOKEN_HEADER]},
                "options": {"timeout": 60000},
            },
            [x + 180, y],
            onError="continueRegularOutput",
        ),
        code(
            wf,
            "Page Guard",
            """
const expected = String(__PAGE_ID__ || '');
const page = $('Get Page Token').first().json;
const me = $json;
const errText = (r) => r && r.error ? String(r.error.description || r.error.message || JSON.stringify(r.error)).slice(0, 300) : null;
let error = null;
if (!expected) error = 'FACEBOOK_PAGE_ID is not configured';
else if (errText(page)) error = 'Cannot read Page ' + expected + ': ' + errText(page);
else if (String(page.id) !== expected) error = 'Page lookup returned ' + page.id + ', expected ' + expected;
else if (!page.access_token) error = 'No Page access token for ' + expected + ' (grant pages_show_list / pages_manage_posts for this Page)';
else if (errText(me)) error = 'Page token check failed: ' + errText(me);
else if (String(me.id) !== expected) error = 'Token acts as ' + me.name + ' (' + me.id + '), not Page ' + expected;
return [{ json: { guard_ok: !error, error, page_id: expected, page_name: page.name || null } }];
""".replace("__PAGE_ID__", page_id_expr),
            [x + 360, y],
        ),
    ]


def facebook_workflow() -> dict:
    note = """## Facebook Page (official Meta Graph API)

Publishes to a Page:
- Images: `POST /{page-id}/photos`
- Videos: `POST /{page-id}/videos`

Page-only guard: fetches the Page token for `FACEBOOK_PAGE_ID`, checks `GET /me` with that
token returns the same Page id, posts with the Page token, then verifies the post `from.id`.
Never posts as a personal profile.

Requires:
- n8n credential **Facebook Graph account** (user or Page token that can read the Page `access_token`, with `pages_manage_posts`)
- `FACEBOOK_PAGE_ID` and `META_GRAPH_VERSION` in `.env`

`DRY_RUN=true` stops at Duplicate Check — nothing is posted.
"""
    nodes = [
        sticky("facebook", "Note", note, [-360, -240], 360, 320, 4),
        trigger_sub("facebook", [0, 0]),
        http_get(
            "facebook",
            "Duplicate Check",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/can-publish?platform=facebook' }}",
            [240, 0],
        ),
        iff("facebook", "Allowed to Publish?", "={{ $json.allowed }}", TRUE, True, [500, 0]),
        code(
            "facebook",
            "Blocked Result",
            """
const job = $('When Called by Another Workflow').first().json;
const check = $json;
return [{ json: {
  product_id: job.product_id,
  platform: 'facebook',
  status: check.dry_run ? 'dry_run_skipped' : (check.status === 'published' ? 'published' : 'skipped'),
  skipped: true,
  reason: check.reason,
  post_id: check.post_id || null
} }];
""",
            [760, 220],
        ),
        http_get("facebook", "Load Config", f"{TRACKING}/config", [760, -120]),
        http_get(
            "facebook",
            "Load Preview",
            "={{ '" + TRACKING + "/previews/' + $('When Called by Another Workflow').first().json.product_id }}",
            [980, -120],
        ),
        code(
            "facebook",
            "Prepare Facebook Job",
            """
const job = $('When Called by Another Workflow').first().json;
const config = $('Load Config').first().json;
const preview = $json;
const content = (preview && preview.content) || job.content || {};
const fb = content.facebook || {};
if (!config.facebook_page_id) {
  throw new Error('FACEBOOK_PAGE_ID is missing in .env / tracking config.');
}
const message = [fb.caption, (fb.hashtags || []).join(' '), fb.cta].filter(Boolean).join('\\n\\n');
const driveId = preview.drive_file_id || job.drive_file_id || null;
const publicUrl = job.public_media_url
  || (driveId ? ('https://drive.google.com/uc?export=download&id=' + driveId) : null);
if (!publicUrl) {
  throw new Error('No public_media_url / drive_file_id available for Facebook Graph publishing.');
}
const isVideo = String(preview.media_type || job.media_type || '') === 'video'
  || Boolean(job.video_file && !job.image_file)
  || String(preview.media_type || '') === 'both';
const version = config.meta_graph_version || 'v22.0';
const pageId = config.facebook_page_id;
const edge = isVideo ? 'videos' : 'photos';
const body = isVideo
  ? { description: message, file_url: publicUrl }
  : { caption: message, url: publicUrl };
return [{ json: {
  product_id: job.product_id,
  platform: 'facebook',
  config,
  preview,
  content,
  public_media_url: publicUrl,
  drive_file_id: driveId,
  publish_url: 'https://graph.facebook.com/' + version + '/' + pageId + '/' + edge,
  publish_body: body
} }];
""",
            [1220, -120],
        ),
        *page_token_guard_nodes(
            "facebook",
            "$('Prepare Facebook Job').first().json.config.meta_graph_version",
            "$('Prepare Facebook Job').first().json.config.facebook_page_id",
            [1340, -120],
        ),
        iff("facebook", "Page Verified?", "={{ $json.guard_ok }}", TRUE, True, [1900, -120]),
        node(
            "facebook",
            "Publish Official API",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "POST",
                "url": "={{ $('Prepare Facebook Job').first().json.publish_url }}",
                "sendHeaders": True,
                "headerParameters": {"parameters": [PAGE_TOKEN_HEADER]},
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify($('Prepare Facebook Job').first().json.publish_body) }}",
                "options": {"timeout": 180000},
            },
            [2120, -200],
            onError="continueRegularOutput",
        ),
        node(
            "facebook",
            "Verify Post Owner",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "={{ 'https://graph.facebook.com/' + $('Prepare Facebook Job').first().json.config.meta_graph_version + '/' + ($json.post_id || $json.id || 'missing') + '?fields=id,from{id,name},permalink_url' }}",
                "sendHeaders": True,
                "headerParameters": {"parameters": [PAGE_TOKEN_HEADER]},
                "options": {"timeout": 60000},
            },
            [2340, -200],
            onError="continueRegularOutput",
        ),
        code(
            "facebook",
            "Interpret Result",
            """
const prepared = $('Prepare Facebook Job').first().json;
const guard = $('Page Guard').first().json;
const pageId = String(prepared.config.facebook_page_id);
const base = { product_id: prepared.product_id, platform: 'facebook' };
const errText = (r) => r && r.error ? String(r.error.description || r.error.message || JSON.stringify(r.error)).slice(0, 400) : null;
if (!guard.guard_ok) return [{ json: { ...base, status: 'failed', error_message: 'Not posted: ' + guard.error } }];
let response = {};
let owner = {};
try { response = $('Publish Official API').first().json; } catch (e) {}
try { owner = $('Verify Post Owner').first().json; } catch (e) {}
const postId = response.post_id || response.id || null;
if (errText(response) || !postId) {
  return [{ json: { ...base, status: 'failed', error_message: errText(response) || ('No Facebook post id in response: ' + JSON.stringify(response).slice(0, 400)) } }];
}
const ownerId = owner.from ? String(owner.from.id) : null;
if (ownerId && ownerId !== pageId) {
  return [{ json: { ...base, status: 'failed', post_id: String(postId), error_message: 'Posted as ' + owner.from.name + ' (' + ownerId + '), not Page ' + pageId + '. Delete it manually.' } }];
}
return [{ json: { ...base, status: 'published', post_id: String(postId), owner_verified: ownerId === pageId, permalink_url: owner.permalink_url || null } }];
""",
            [2560, -120],
        ),
        http_post_json(
            "facebook",
            "Store Platform Result",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/platform-result' }}",
            "={{ JSON.stringify({ platform: $json.platform, status: $json.status === 'dry_run_skipped' ? 'pending' : ($json.status === 'skipped' ? 'skipped' : $json.status), post_id: $json.post_id || null, error_message: $json.error_message || $json.reason || null }) }}",
            [1960, 40],
        ),
    ]
    pairs = [
        ("When Called by Another Workflow", "Duplicate Check"),
        ("Duplicate Check", "Allowed to Publish?"),
        ("Allowed to Publish?", "Load Config", 0),
        ("Allowed to Publish?", "Blocked Result", 1),
        ("Load Config", "Load Preview"),
        ("Load Preview", "Prepare Facebook Job"),
        ("Prepare Facebook Job", "Get Page Token"),
        ("Get Page Token", "Verify Page Identity"),
        ("Verify Page Identity", "Page Guard"),
        ("Page Guard", "Page Verified?"),
        ("Page Verified?", "Publish Official API", 0),
        ("Page Verified?", "Interpret Result", 1),
        ("Publish Official API", "Verify Post Owner"),
        ("Verify Post Owner", "Interpret Result"),
        ("Interpret Result", "Store Platform Result"),
        ("Blocked Result", "Store Platform Result"),
    ]
    return workflow("05 Facebook Publisher", WF["facebook"], nodes, pairs)


def pinterest_workflow() -> dict:
    note = """## Pinterest (official API v5)

Creates **image Pins** only, using `media_source.source_type = image_url` or `image_base64`.

Video products are skipped on purpose. Do not assume video Pin upload works without the media-upload dance.

Set `PINTEREST_BOARD_ID` and attach **Pinterest account** (OAuth2 API) to the HTTP node.
Keep `DRY_RUN=true` — Duplicate Check blocks Pin create.
"""
    url = "https://api.pinterest.com/v5/pins"
    body = "={{ JSON.stringify({ board_id: $json.config.pinterest_board_id, title: $json.content.pinterest.title, description: $json.content.pinterest.description, alt_text: $json.content.pinterest.title, media_source: { source_type: 'image_url', url: $json.public_media_url } }) }}"
    wf = platform_workflow("pinterest", WF["pinterest"], "06 Pinterest Publisher", note, url, body, "$('When Called by Another Workflow').first().json.media_type === 'video'")
    for n in wf["nodes"]:
        if n["name"] == "Publish Official API":
            n["parameters"]["authentication"] = "genericCredentialType"
            n["parameters"]["genericAuthType"] = "oAuth2Api"
            n["credentials"] = dict(PINTEREST_CRED)
    return wf


def youtube_workflow() -> dict:
    note = """## YouTube Shorts only (official YouTube Data API v3)

This automation publishes **YouTube Shorts only** — never long-form videos.

- Video products from Google Drive are treated as Shorts.
- Image-only products are skipped.
- Default privacy is **private** for testing (`YOUTUBE_PRIVACY_STATUS=private`).
- Description/hashtags include `#Shorts` for Shorts discovery.
- Attach **YouTube OAuth2 API** credentials before any live run.
- `DRY_RUN=true` stops at Duplicate Check — nothing is uploaded.
"""
    nodes = [
        sticky("youtube", "Note", note, [-380, -260], 380, 360, 4),
        trigger_sub("youtube", [0, 0]),
        http_get(
            "youtube",
            "Duplicate Check",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/can-publish?platform=youtube' }}",
            [240, 0],
        ),
        iff("youtube", "Allowed to Publish?", "={{ $json.allowed }}", TRUE, True, [500, 0]),
        code(
            "youtube",
            "Blocked Result",
            """
const job = $('When Called by Another Workflow').first().json;
const check = $json;
return [{ json: {
  product_id: job.product_id,
  platform: 'youtube',
  status: check.dry_run ? 'dry_run_skipped' : (check.status === 'published' ? 'published' : 'skipped'),
  skipped: true,
  reason: check.reason,
  post_id: check.post_id || null
} }];
""",
            [760, 220],
        ),
        http_get("youtube", "Load Config", f"{TRACKING}/config", [760, -120]),
        http_get(
            "youtube",
            "Load Preview",
            "={{ '" + TRACKING + "/previews/' + $('When Called by Another Workflow').first().json.product_id }}",
            [980, -120],
        ),
        code(
            "youtube",
            "Prepare Shorts Job",
            """
const job = $('When Called by Another Workflow').first().json;
const config = $('Load Config').first().json;
const preview = $json;
const mediaType = String(preview.media_type || job.media_type || '');
if (mediaType === 'image') {
  return [{ json: {
    product_id: job.product_id,
    platform: 'youtube',
    status: 'skipped',
    skipped: true,
    reason: 'YouTube Shorts require video media. Image-only products are skipped.',
    skip_upload: true
  } }];
}
const content = (preview && preview.content) || job.content || {};
const yt = content.youtube || {};
let title = String(yt.title || '').trim();
if (title.length > 70) title = title.slice(0, 67).trim() + '...';
let description = String(yt.description || '').trim();
const hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.map(String) : [];
const tags = Array.isArray(yt.tags) ? yt.tags.map(String) : [];
const lowerTags = hashtags.map((h) => h.toLowerCase());
if (!lowerTags.some((h) => h.replace(/^#/, '') === 'shorts')) {
  hashtags.push('#shorts');
}
if (!/\\b#?shorts\\b/i.test(description)) {
  description = (description ? description + '\\n\\n' : '') + '#Shorts';
}
const tagLine = hashtags.join(' ');
if (tagLine && !description.includes(tagLine)) {
  description = description + '\\n' + tagLine;
}
return [{ json: {
  product_id: job.product_id,
  platform: 'youtube',
  skip_upload: false,
  shorts: true,
  title,
  description,
  tags,
  hashtags,
  privacyStatus: config.youtube_privacy_status || 'private',
  filename: preview.filename || job.filename || null,
  drive_file_id: preview.drive_file_id || job.drive_file_id || null,
  local_path: preview.local_path || job.local_path || null,
  content
} }];
""",
            [1220, -120],
        ),
        iff("youtube", "Upload Short?", "={{ !$json.skip_upload }}", TRUE, True, [1460, -120]),
        node(
            "youtube",
            "Read Short Binary",
            "n8n-nodes-base.readBinaryFile",
            1,
            {
                "filePath": "={{ $json.local_path }}",
                "dataPropertyName": "data",
            },
            [1700, -200],
            onError="continueRegularOutput",
        ),
        node(
            "youtube",
            "Upload YouTube Short",
            "n8n-nodes-base.youTube",
            1,
            {
                "resource": "video",
                "operation": "upload",
                "title": "={{ $('Prepare Shorts Job').item.json.title }}",
                "regionCode": "US",
                "categoryId": "28",
                "binaryProperty": "data",
                "options": {
                    "description": "={{ $('Prepare Shorts Job').item.json.description }}",
                    "privacyStatus": "={{ $('Prepare Shorts Job').item.json.privacyStatus || 'private' }}",
                    "tags": "={{ ($('Prepare Shorts Job').item.json.tags || []).join(',') }}",
                },
            },
            [1940, -200],
            credentials={"youTubeOAuth2Api": {"id": "youTubeOAuth2Api", "name": "YouTube account"}},
            onError="continueRegularOutput",
        ),
        code(
            "youtube",
            "Interpret Result",
            """
const prepared = $('Prepare Shorts Job').first().json;
if (prepared.skip_upload) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'youtube',
    status: 'skipped',
    skipped: true,
    reason: prepared.reason || 'YouTube Shorts require video media'
  } }];
}
if (!prepared.local_path) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'youtube',
    status: 'failed',
    error_message: 'Missing local_path for Shorts video binary (product media from Drive).'
  } }];
}
const response = $json;
const errMsg = (response.error && response.error.message) || response.message || '';
const postId = response.id || response.videoId || response.uploadId || null;
if (response.error || !postId) {
  let message = errMsg || JSON.stringify(response).slice(0, 500);
  const lower = String(message).toLowerCase();
  if (lower.includes('invalid_grant') || lower.includes('unauthorized') || lower.includes('login required')) {
    message = 'YouTube OAuth is missing or expired. Open n8n → Credentials → YouTube account → Sign in with Google. ' + message;
  } else if (lower.includes('quota')) {
    message = 'YouTube API quota exceeded. Retry tomorrow or request quota increase. ' + message;
  } else if (lower.includes('youtubesignuprequired') || lower.includes('channel not found')) {
    message = 'YouTube channel may be missing on this Google account. ' + message;
  }
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'youtube',
    status: 'failed',
    error_message: message,
    shorts: true
  } }];
}
return [{ json: {
  product_id: prepared.product_id,
  platform: 'youtube',
  status: 'published',
  post_id: String(postId),
  shorts: true
} }];
""",
            [2180, -120],
        ),
        http_post_json(
            "youtube",
            "Store Platform Result",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/platform-result' }}",
            "={{ JSON.stringify({ platform: 'youtube', status: $json.status === 'dry_run_skipped' ? 'pending' : $json.status, post_id: $json.post_id || null, error_message: $json.error_message || $json.reason || null }) }}",
            [2420, 40],
        ),
    ]
    pairs = [
        ("When Called by Another Workflow", "Duplicate Check"),
        ("Duplicate Check", "Allowed to Publish?"),
        ("Allowed to Publish?", "Load Config", 0),
        ("Allowed to Publish?", "Blocked Result", 1),
        ("Load Config", "Load Preview"),
        ("Load Preview", "Prepare Shorts Job"),
        ("Prepare Shorts Job", "Upload Short?"),
        ("Upload Short?", "Read Short Binary", 0),
        ("Upload Short?", "Interpret Result", 1),
        ("Read Short Binary", "Upload YouTube Short"),
        ("Upload YouTube Short", "Interpret Result"),
        ("Interpret Result", "Store Platform Result"),
        ("Blocked Result", "Store Platform Result"),
    ]
    return workflow("07 YouTube Shorts Publisher", WF["youtube"], nodes, pairs)


def queue_preparer_workflow() -> dict:
    nodes = [
        sticky(
            "daily",
            "Overview",
            "## Content Queue Preparer\nPrepares ONE product per run: public Google Drive folder → download media → Gemini vision AI (Groq fallback) → saved preview marked `prepared` in the queue.\n\nStarted by the tracking-api scheduler whenever fewer than `queue_size` (default 3) products are ready, and by the Daily Publisher when the queue is empty.\n\nNever publishes anything.",
            [-440, -40],
            320,
            340,
            6,
        ),
        node("daily", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 200]),
        trigger_sub("daily", [0, 400]),
        http_get("daily", "Load Config", f"{TRACKING}/config", [280, 160]),
        iff("daily", "Drive Folder Configured?", "={{ $('Load Config').first().json.google_drive_folder_id }}", NOT_EMPTY, "", [760, 160]),
        node(
            "daily",
            "Stop Missing Folder ID",
            "n8n-nodes-base.stopAndError",
            1,
            {
                "errorType": "errorMessage",
                "errorMessage": "GOOGLE_DRIVE_FOLDER_ID is empty. Paste the folder ID from the Drive URL into .env, restart Compose, then connect Google Drive OAuth in n8n.",
            },
            [1000, 360],
        ),
        http_post_json(
            "daily",
            "List Google Drive Folder",
            f"{TRACKING}/drive/public-list",
            "={{ JSON.stringify({ folder_id: $('Load Config').first().json.google_drive_folder_id }) }}",
            [1000, 40],
        ),
        code(
            "daily",
            "Normalize Drive List",
            """
const payload = $json;
const files = (payload.files || []).map((item) => ({
  name: item.name,
  id: item.id || item.drive_file_id,
  drive_file_id: item.drive_file_id || item.id,
  mimeType: item.mimeType,
  thumbnailLink: item.thumbnailLink,
  webViewLink: item.webViewLink,
})).filter((file) => file.name && file.drive_file_id);
if (!files.length) {
  throw new Error('Google Drive returned no files from the public folder. Confirm sharing is Anyone with the link and GOOGLE_DRIVE_FOLDER_ID is correct.');
}
return [{ json: { files, drive_access_mode: payload.access_mode || 'public', drive_list_method: payload.method } }];
""",
            [1240, 40],
        ),
        http_post_json(
            "daily",
            "Select Next Product",
            f"{TRACKING}/queue/select-to-prepare",
            "={{ JSON.stringify({ files: $json.files || [] }) }}",
            [1480, 40],
        ),
        iff("daily", "Needs AI Content?", "={{ $json.found === true && $json.reused !== true }}", TRUE, True, [1720, 40]),
        code(
            "daily",
            "Nothing To Prepare",
            """
const s = $json;
return [{ json: {
  prepared: s.reused === true,
  reused: s.reused === true,
  product_id: s.product_id || null,
  reason_code: s.reason_code || (s.reused ? 'reused_saved_content' : null),
  reason: s.reason || (s.reused ? 'Reused saved content for Product ' + s.product_id : null),
  queue: s.queue || []
} }];
""",
            [1960, 280],
        ),
        code(
            "daily",
            "Pick Vision File",
            """
const selected = $('Select Next Product').first().json;
const config = $('Load Config').first().json;
const vision = selected.image_file || selected.video_file;
if (!vision || !vision.drive_file_id) {
  throw new Error('Product ' + selected.product_id + ' has no Google Drive file ID. Check the filename pattern ProductID.ext.');
}
return [{ json: {
  ...selected,
  config,
  vision_file: vision,
  filename: vision.filename,
  drive_file_id: vision.drive_file_id,
  local_path: '/data/media/' + vision.filename
} }];
""",
            [2200, -80],
        ),
        http_post_json(
            "daily",
            "Download Drive Media",
            f"{TRACKING}/drive/public-download",
            "={{ JSON.stringify({ file_id: $json.drive_file_id, filename: $json.filename, folder_id: $('Load Config').first().json.google_drive_folder_id }) }}",
            [2440, -80],
        ),
        code(
            "daily",
            "Save Media to Disk",
            """
const picked = $('Pick Vision File').first().json;
const downloaded = $json;
if (!downloaded.ok || !downloaded.local_path) {
  throw new Error('Public Drive download failed: ' + JSON.stringify(downloaded).slice(0, 400));
}
return [{ json: { ...picked, local_path: downloaded.local_path, download_bytes: downloaded.bytes, drive_access_mode: downloaded.access_mode || 'public' } }];
""",
            [2680, -80],
        ),
        http_post_json(
            "daily",
            "Prepare Vision Still",
            f"{TRACKING}/media/prepare-vision",
            "={{ JSON.stringify({ local_path: $json.local_path, media_kind: $json.vision_file.media_kind, product_id: $json.product_id }) }}",
            [2920, -80],
        ),
        code(
            "daily",
            "Build AI Job",
            """
const selected = $('Pick Vision File').first().json;
const vision = $json;
if (!vision.base64) {
  throw new Error('Could not prepare a still image for AI vision: ' + JSON.stringify(vision).slice(0, 400));
}
return [{ json: {
  ...selected,
  vision_base64: vision.base64,
  vision_mime: vision.mime_type || 'image/jpeg',
  vision_source: vision.source,
  local_path: selected.local_path
} }];
""",
            [3160, -80],
        ),
        execute_sub("daily", "Generate AI Content", WF["ai"], "03 AI Content Generator", [3400, -80]),
        code(
            "daily",
            "Build Preview Payload",
            """
const ai = $('Generate AI Content').first().json;
const src = ai || $json;
const picked = $('Pick Vision File').first().json;
const config = $('Load Config').first().json;
if (src.error && !src.content) {
  throw new Error('AI step failed before preview save: ' + String(src.error));
}
if (!src.content) {
  throw new Error('Generate AI Content returned no content object. Refusing to save preview.');
}
const dryRun = !!(src.config && typeof src.config.dry_run !== 'undefined'
  ? src.config.dry_run
  : config.dry_run);
const productId = src.product_id || picked.product_id;
const previewBody = {
  product_id: productId,
  filename: src.filename || picked.filename || null,
  media_type: src.media_type || picked.media_type || null,
  drive_file_id: src.drive_file_id || picked.drive_file_id || null,
  google_drive_folder_id: (src.config && src.config.google_drive_folder_id)
    || config.google_drive_folder_id
    || null,
  local_path: src.local_path || picked.local_path || null,
  vision_notes: src.vision_notes || null,
  vision_source: src.vision_source || null,
  ai_provider_used: src.ai_provider_used || null,
  ai_model_used: src.ai_model_used || null,
  gemini_model_used: src.gemini_model_used || null,
  ai_fallback_reason: src.ai_fallback_reason || null,
  dry_run: dryRun,
  queue: true,
  content: src.content,
};
return [{ json: { ...src, product_id: productId, dry_run: dryRun, previewBody } }];
""",
            [3520, -80],
        ),
        http_post_json_object(
            "daily",
            "Save Preview",
            f"{TRACKING}/previews",
            "$json.previewBody",
            [3640, -80],
        ),
        code(
            "daily",
            "Prepared Summary",
            """
const saved = $json;
const ai = $('Generate AI Content').first().json;
return [{ json: {
  prepared: true,
  reused: false,
  product_id: saved.product_id,
  filename: saved.filename,
  ai_provider_used: ai.ai_provider_used || null,
  ai_model_used: ai.ai_model_used || null,
  ai_fallback_reason: ai.ai_fallback_reason || null
} }];
""",
            [3880, -80],
        ),
        sticky("daily", "Drive", "## Google Drive (public folder)\nLists/downloads via the shared folder link.\nFolder ID comes from `GOOGLE_DRIVE_FOLDER_ID`.\nDoes **not** use n8n Google Drive OAuth for media (that path returned SERVICE_DISABLED 403 even when OAuth showed connected).", [1000, 220], 320, 240, 1),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("When Called by Another Workflow", "Load Config"),
        ("Load Config", "Drive Folder Configured?"),
        ("Drive Folder Configured?", "List Google Drive Folder", 0),
        ("Drive Folder Configured?", "Stop Missing Folder ID", 1),
        ("List Google Drive Folder", "Normalize Drive List"),
        ("Normalize Drive List", "Select Next Product"),
        ("Select Next Product", "Needs AI Content?"),
        ("Needs AI Content?", "Pick Vision File", 0),
        ("Needs AI Content?", "Nothing To Prepare", 1),
        ("Pick Vision File", "Download Drive Media"),
        ("Download Drive Media", "Save Media to Disk"),
        ("Save Media to Disk", "Prepare Vision Still"),
        ("Prepare Vision Still", "Build AI Job"),
        ("Build AI Job", "Generate AI Content"),
        ("Generate AI Content", "Build Preview Payload"),
        ("Build Preview Payload", "Save Preview"),
        ("Save Preview", "Prepared Summary"),
    ]
    return workflow("16 Content Queue Preparer", WF["queue_prep"], nodes, pairs)


def daily_workflow() -> dict:
    job = "$('Build Publish Job').first().json"
    nodes = [
        sticky(
            "daily",
            "Overview",
            "## Daily Publisher\nPublishes exactly ONE product: the head of the prepared content queue.\n\nStarted by the tracking-api scheduler at the time chosen on the dashboard (`config/schedule.json`, Asia/Kolkata). No cron is hard-coded here.\n\nIf the queue is empty it runs **16 Content Queue Preparer** first. Stops before social posting while `DRY_RUN=true`.",
            [-440, -40],
            320,
            340,
            6,
        ),
        node("daily", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 200]),
        trigger_sub("daily", [0, 400]),
        http_get("daily", "Load Config", f"{TRACKING}/config", [280, 160]),
        http_post_json(
            "daily",
            "Log Daily Start",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'daily_execution', message: 'Daily publisher started', details: { dry_run: $json.dry_run, timezone: $json.timezone, publish_time: $json.publish_time, ai_provider: $json.ai_provider } }) }}",
            [520, 160],
        ),
        http_post_json("daily", "Claim Queue Head", f"{TRACKING}/queue/claim", "={{ JSON.stringify({}) }}", [760, 160]),
        iff("daily", "Queue Head Ready?", "={{ $json.found }}", TRUE, True, [1000, 160]),
        iff("daily", "Queue Empty?", "={{ $json.reason_code }}", EQ_STR, "queue_empty", [1240, 360]),
        execute_sub("daily", "Prepare Content Now", WF["queue_prep"], "16 Content Queue Preparer", [1480, 360]),
        http_post_json("daily", "Claim After Prepare", f"{TRACKING}/queue/claim", "={{ JSON.stringify({}) }}", [1720, 360]),
        iff("daily", "Product Found?", "={{ $json.found }}", TRUE, True, [1960, 360]),
        http_post_json(
            "daily",
            "Log No Product",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'no_product', message: $json.reason || 'No product to process', details: $json }) }}",
            [2200, 560],
        ),
        noop("daily", "Idle", [2440, 560]),
        code(
            "daily",
            "Build Publish Job",
            """
const job = $json;
if (!job.product_id || !job.content) {
  throw new Error('Queue head has no saved content: ' + JSON.stringify(job).slice(0, 300));
}
return [{ json: job }];
""",
            [2200, 160],
        ),
        http_post_json(
            "daily",
            "Mark Processing",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/processing' }}",
            "={{ JSON.stringify({}) }}",
            [2440, 160],
        ),
        code("daily", "Publish Payload", f"return [{{ json: {job} }}];", [2680, 160]),
        iff("daily", "DRY RUN?", "={{ $('Load Config').first().json.dry_run }}", TRUE, True, [2920, 160]),
        code(
            "daily",
            "Build Dry Run Log",
            f"""
const src = {job};
const logBody = {{
  level: 'info',
  event: 'dry_run_preview',
  product_id: src.product_id,
  message: 'DRY_RUN used the prepared queue content and skipped all social publishing',
  details: {{
    product_id: src.product_id,
    ai_provider_used: src.ai_provider_used,
    ai_model_used: src.ai_model_used,
    ai_fallback_reason: src.ai_fallback_reason,
    vision_notes: src.vision_notes,
  }},
}};
return [{{ json: {{ ...src, logBody }} }}];
""",
            [3160, 0],
        ),
        http_post_json_object("daily", "Log Dry Run Preview", f"{TRACKING}/logs", "$json.logBody", [3400, 0]),
        http_post_json(
            "daily",
            "Finalize Dry Run",
            "={{ '" + TRACKING + "/products/' + " + job + ".product_id + '/finalize' }}",
            "={{ JSON.stringify({}) }}",
            [3640, 0],
        ),
        execute_sub("daily", "Publish Instagram", WF["instagram"], "04 Instagram Publisher", [3160, 280], continue_on_error=True),
        execute_sub("daily", "Publish Facebook", WF["facebook"], "05 Facebook Publisher", [3400, 280], continue_on_error=True),
        execute_sub("daily", "Publish Pinterest", WF["pinterest"], "06 Pinterest Publisher", [3640, 280], continue_on_error=True),
        execute_sub("daily", "Publish YouTube", WF["youtube"], "07 YouTube Shorts Publisher", [3880, 280], continue_on_error=True),
        http_post_json(
            "daily",
            "Finalize Product",
            "={{ '" + TRACKING + "/products/' + " + job + ".product_id + '/finalize' }}",
            "={{ JSON.stringify({}) }}",
            [4120, 280],
        ),
        http_post_json(
            "daily",
            "Log Final Status",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'final_product_status', product_id: $json.product_id, message: 'Product ' + $json.product_id + ' status ' + $json.overall_status, details: $json }) }}",
            [4360, 280],
        ),
        sticky("daily", "Safety", "## DRY_RUN\nSocial publish nodes are not called until you set `DRY_RUN=false`.\nDuplicate protection: the tracking API hands out one queue head per local day in live mode, and each platform publisher re-checks `can-publish`.", [2920, -240], 320, 180, 3),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("When Called by Another Workflow", "Load Config"),
        ("Load Config", "Log Daily Start"),
        ("Log Daily Start", "Claim Queue Head"),
        ("Claim Queue Head", "Queue Head Ready?"),
        ("Queue Head Ready?", "Build Publish Job", 0),
        ("Queue Head Ready?", "Queue Empty?", 1),
        ("Queue Empty?", "Prepare Content Now", 0),
        ("Queue Empty?", "Log No Product", 1),
        ("Prepare Content Now", "Claim After Prepare"),
        ("Claim After Prepare", "Product Found?"),
        ("Product Found?", "Build Publish Job", 0),
        ("Product Found?", "Log No Product", 1),
        ("Log No Product", "Idle"),
        ("Build Publish Job", "Mark Processing"),
        ("Mark Processing", "Publish Payload"),
        ("Publish Payload", "DRY RUN?"),
        ("DRY RUN?", "Build Dry Run Log", 0),
        ("DRY RUN?", "Publish Instagram", 1),
        ("Build Dry Run Log", "Log Dry Run Preview"),
        ("Log Dry Run Preview", "Finalize Dry Run"),
        ("Publish Instagram", "Publish Facebook"),
        ("Publish Facebook", "Publish Pinterest"),
        ("Publish Pinterest", "Publish YouTube"),
        ("Publish YouTube", "Finalize Product"),
        ("Finalize Product", "Log Final Status"),
    ]
    return workflow("01 Daily Publisher", WF["daily"], nodes, pairs)


def admin_workflow() -> dict:
    nodes = [
        sticky(
            "admin",
            "Note",
            "## Admin / Control\nPreview and Run Now both execute the real Daily Publisher (Google Drive + vision AI).\nSocial posting stays blocked while DRY_RUN=true.\n\nhttp://localhost:8081/admin",
            [-380, 40],
            320,
            280,
            7,
        ),
        node(
            "admin",
            "Webhook Run Now",
            "n8n-nodes-base.webhook",
            2.1,
            {"httpMethod": "POST", "path": "admin/run-now", "responseMode": "responseNode", "options": {}},
            [0, 0],
            webhookId=nid("admin", "run-now"),
        ),
        node(
            "admin",
            "Webhook Preview",
            "n8n-nodes-base.webhook",
            2.1,
            {"httpMethod": "POST", "path": "admin/preview", "responseMode": "responseNode", "options": {}},
            [0, 220],
            webhookId=nid("admin", "preview"),
        ),
        node(
            "admin",
            "Webhook Retry",
            "n8n-nodes-base.webhook",
            2.1,
            {"httpMethod": "POST", "path": "admin/retry", "responseMode": "responseNode", "options": {}},
            [0, 440],
            webhookId=nid("admin", "retry"),
        ),
        node(
            "admin",
            "Webhook Status",
            "n8n-nodes-base.webhook",
            2.1,
            {"httpMethod": "GET", "path": "admin/status", "responseMode": "responseNode", "options": {}},
            [0, 660],
            webhookId=nid("admin", "status"),
        ),
        execute_sub("admin", "Run Daily Publisher", WF["daily"], "01 Daily Publisher", [280, 0]),
        execute_sub("admin", "Preview Daily Publisher", WF["daily"], "01 Daily Publisher", [280, 220]),
        http_post_json("admin", "Find Failed Product", f"{TRACKING}/products/retry-failed", "={{ JSON.stringify({}) }}", [280, 440]),
        execute_sub("admin", "Retry Daily Publisher", WF["daily"], "01 Daily Publisher", [520, 440]),
        http_get("admin", "Read Status", f"{TRACKING}/status", [280, 660]),
        node("admin", "Respond Run Now", "n8n-nodes-base.respondToWebhook", 1.5, {"options": {"responseCode": 200}}, [560, 0]),
        node("admin", "Respond Preview", "n8n-nodes-base.respondToWebhook", 1.5, {"options": {"responseCode": 200}}, [560, 220]),
        node("admin", "Respond Retry", "n8n-nodes-base.respondToWebhook", 1.5, {"options": {"responseCode": 200}}, [760, 440]),
        node("admin", "Respond Status", "n8n-nodes-base.respondToWebhook", 1.5, {"options": {"responseCode": 200}}, [560, 660]),
    ]
    pairs = [
        ("Webhook Run Now", "Run Daily Publisher"),
        ("Run Daily Publisher", "Respond Run Now"),
        ("Webhook Preview", "Preview Daily Publisher"),
        ("Preview Daily Publisher", "Respond Preview"),
        ("Webhook Retry", "Find Failed Product"),
        ("Find Failed Product", "Retry Daily Publisher"),
        ("Retry Daily Publisher", "Respond Retry"),
        ("Webhook Status", "Read Status"),
        ("Read Status", "Respond Status"),
    ]
    return workflow("02 Admin Control", WF["admin"], nodes, pairs)


def validate(doc: dict) -> list[str]:
    errors = []
    names = [n["name"] for n in doc["nodes"]]
    if len(names) != len(set(names)):
        errors.append(f"{doc['name']}: duplicate node names")
    for src, spec in doc["connections"].items():
        if src not in names:
            errors.append(f"{doc['name']}: connection source missing {src}")
        for group in spec.get("main", []):
            for link in group:
                if link["node"] not in names:
                    errors.append(f"{doc['name']}: connection target missing {link['node']}")
    return errors


def meta_auth_probe_workflow() -> dict:
    """Manual-only Graph auth probe. Never posts. Safe while DRY_RUN=true."""
    note = """## Meta Auth Probe (Instagram + Facebook)

Manual test only. Does **not** publish.

After you paste a Page access token into **Facebook Graph account**:
1. Set `FACEBOOK_PAGE_ID` in `.env` and restart tracking-api / re-import if needed.
2. Run this workflow manually.
3. Confirm `me` (the Page) returns your Page id and Instagram business account id.

Keep `DRY_RUN=true`. Pinterest/YouTube are out of scope for this phase.
"""
    nodes = [
        sticky("meta", "Note", note, [-400, -220], 380, 320, 5),
        node("meta", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get("meta", "Load Config", f"{TRACKING}/config", [240, 0]),
        http_get("meta", "Meta Readiness", f"{TRACKING}/meta/readiness", [480, 0]),
        code(
            "meta",
            "Build Probe URLs",
            """
const config = $('Load Config').first().json;
const readiness = $json;
const version = config.meta_graph_version || 'v22.0';
const pageId = config.facebook_page_id || '';
return [{ json: {
  readiness,
  dry_run: config.dry_run,
  page_id: pageId,
  ig_user_id: config.instagram_business_account_id || '',
  me_url: 'https://graph.facebook.com/' + version + '/me?metadata=1&fields=id,name',
  accounts_url: 'https://graph.facebook.com/' + version + '/me/accounts?fields=id,name,instagram_business_account',
  page_url: 'https://graph.facebook.com/' + version + '/' + (pageId || 'me') + '?fields=id,name,username,link,instagram_business_account{id,username},access_token',
  graph_base: 'https://graph.facebook.com/' + version,
} }];
""",
            [720, 0],
        ),
    ]
    for name, url_expr, pos in (
        ("Probe Token", "={{ $('Build Probe URLs').first().json.me_url }}", [980, -80]),
        ("Probe Accounts", "={{ $('Build Probe URLs').first().json.accounts_url }}", [1100, -80]),
        ("Probe Page", "={{ $('Build Probe URLs').first().json.page_url }}", [1220, -80]),
    ):
        nodes.append(
            node(
                "meta",
                name,
                "n8n-nodes-base.httpRequest",
                4.5,
                {
                    "method": "GET",
                    "url": url_expr,
                    "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "facebookGraphApi",
                    "options": {"timeout": 60000},
                },
                pos,
                credentials=META_CRED,
                onError="continueRegularOutput",
            )
        )
    page_auth = {"name": "Authorization", "value": "={{ 'OAuth ' + ($('Probe Page').first().json.access_token || 'missing') }}"}
    for name, url_expr, pos in (
        ("Probe Page Identity", "={{ $('Build Probe URLs').first().json.graph_base + '/me?fields=id,name' }}", [1340, -200]),
        (
            "Probe Page Reels",
            "={{ $('Build Probe URLs').first().json.graph_base + '/' + $('Build Probe URLs').first().json.page_id + '/video_reels?fields=id,permalink_url,from,created_time&limit=5' }}",
            [1400, -80],
        ),
    ):
        nodes.append(
            node(
                "meta",
                name,
                "n8n-nodes-base.httpRequest",
                4.5,
                {"method": "GET", "url": url_expr, "sendHeaders": True, "headerParameters": {"parameters": [page_auth]}, "options": {"timeout": 60000}},
                pos,
                onError="continueRegularOutput",
            )
        )
    nodes.append(
        code(
            "meta",
            "Summarize Probe",
            """
const built = $('Build Probe URLs').first().json;
const me = $('Probe Token').first().json;
const page = $('Probe Page').first().json;
const pageMe = $('Probe Page Identity').first().json;
const reels = $('Probe Page Reels').first().json;
const errText = (r) => r && r.error ? (r.error.description || r.error.message || JSON.stringify(r.error)) : null;
const igFromPage = page && page.instagram_business_account ? page.instagram_business_account.id : null;
return [{ json: {
  dry_run: built.dry_run,
  readiness: built.readiness,
  token_type: (me.metadata || {}).type || null,
  token_owner: me.id ? { id: me.id, name: me.name } : null,
  user_pages: ($('Probe Accounts').first().json.data || []).map((p) => ({ id: p.id, name: p.name, ig: (p.instagram_business_account || {}).id || null })),
  graph_ok: !page.error && Boolean(page.id),
  error: errText(page) || errText(me),
  pages_found: page.id ? [{ id: page.id, name: page.name, ig: igFromPage }] : [],
  page_details: page.id ? {
    username: page.username || null,
    link: page.link || null,
    ig_username: (page.instagram_business_account || {}).username || null,
    page_token_obtained: Boolean(page.access_token),
    page_token_identity: pageMe.id ? { id: pageMe.id, name: pageMe.name } : { error: errText(pageMe) },
    page_token_is_page: String(pageMe.id || '') === String(built.page_id),
    recent_reels: (reels.data || []).map((r) => ({ id: r.id, permalink_url: r.permalink_url || null, from: r.from || null, created_time: r.created_time || null })),
    reels_error: errText(reels)
  } : null,
  configured_page_id: built.page_id || null,
  configured_ig_user_id: built.ig_user_id || null,
  discovered_ig_user_id: igFromPage,
  ids_match: Boolean(built.ig_user_id) && String(built.ig_user_id) === String(igFromPage || ''),
  note: 'No content was published. Keep DRY_RUN=true until you explicitly approve a live post.'
} }];
""",
            [1460, -80],
        )
    )
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "Meta Readiness"),
        ("Meta Readiness", "Build Probe URLs"),
        ("Build Probe URLs", "Probe Token"),
        ("Probe Token", "Probe Accounts"),
        ("Probe Accounts", "Probe Page"),
        ("Probe Page", "Probe Page Identity"),
        ("Probe Page Identity", "Probe Page Reels"),
        ("Probe Page Reels", "Summarize Probe"),
    ]
    return workflow("09 Meta Auth Probe", "3dprMetaAuthProbe09", nodes, pairs)


def youtube_auth_probe_workflow() -> dict:
    """Manual-only YouTube auth probe. Never uploads. Safe while DRY_RUN=true."""
    note = """## YouTube Shorts Auth Probe

Manual test only. Does **not** upload Shorts or change channel content.

Uses YouTube Data API `channels.list?mine=true` (read-only) with **YouTube account** OAuth.

1. Complete Google Cloud OAuth client + n8n **Sign in with Google** first.
2. Run this workflow manually.
3. Confirm a channel id/title is returned.
4. Keep `DRY_RUN=true` — publisher upload stays blocked.
"""
    yt_cred = {"youTubeOAuth2Api": {"id": "youTubeOAuth2Api", "name": "YouTube account"}}
    nodes = [
        sticky("ytprobe", "Note", note, [-400, -220], 400, 340, 4),
        node("ytprobe", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get("ytprobe", "Load Config", f"{TRACKING}/config", [240, 0]),
        http_get("ytprobe", "YouTube Readiness", f"{TRACKING}/youtube/readiness", [480, 0]),
        code(
            "ytprobe",
            "Guard Dry Run",
            """
const config = $('Load Config').first().json;
const readiness = $json;
if (config.dry_run !== true) {
  throw new Error('Refusing YouTube probe while DRY_RUN is not true.');
}
if (String(config.youtube_format || readiness.youtube_format || '') !== 'shorts') {
  throw new Error('youtube_format must be shorts');
}
return [{ json: {
  dry_run: true,
  readiness,
  privacy: config.youtube_privacy_status || 'private',
  note: 'About to call channels.list mine=true — read only, no upload.'
} }];
""",
            [720, 0],
        ),
        node(
            "ytprobe",
            "List My Channel",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "https://www.googleapis.com/youtube/v3/channels",
                "sendQuery": True,
                "queryParameters": {
                    "parameters": [
                        {"name": "part", "value": "snippet,status"},
                        {"name": "mine", "value": "true"},
                    ]
                },
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "youTubeOAuth2Api",
                "options": {"timeout": 60000},
            },
            [980, 0],
            credentials=yt_cred,
            onError="continueRegularOutput",
        ),
        code(
            "ytprobe",
            "Summarize Probe",
            """
const readiness = $('YouTube Readiness').first().json;
const raw = $json;
const err = raw.error || raw.message || null;
const items = Array.isArray(raw.items) ? raw.items : [];
const channels = items.map((ch) => ({
  id: ch.id,
  title: (ch.snippet && ch.snippet.title) || null,
  privacyStatus: (ch.status && ch.status.privacyStatus) || null,
}));
const oauthOk = !err && channels.length > 0;
return [{ json: {
  dry_run: true,
  youtube_format: readiness.youtube_format || 'shorts',
  publish_blocked_by_dry_run: true,
  upload_attempted: false,
  oauth_ok: oauthOk,
  channels_found: channels,
  error: err ? (typeof err === 'string' ? err : (err.message || JSON.stringify(err).slice(0, 400))) : null,
  readiness,
  next: oauthOk
    ? 'OAuth works. Keep DRY_RUN=true. Do not upload until explicit approval.'
    : 'OAuth not connected yet. Finish Google Cloud client + n8n Sign in with Google.',
} }];
""",
            [1220, 0],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "YouTube Readiness"),
        ("YouTube Readiness", "Guard Dry Run"),
        ("Guard Dry Run", "List My Channel"),
        ("List My Channel", "Summarize Probe"),
    ]
    return workflow("10 YouTube Shorts Auth Probe", "3dprYtAuthProbe10", nodes, pairs)


def pinterest_auth_probe_workflow() -> dict:
    """Manual-only Pinterest auth probe. Never creates Pins. Safe while DRY_RUN=true."""
    note = """## Pinterest Auth Probe

Manual test only. Does **not** create Pins or change boards.

Uses Pinterest API v5 `user_account` + `boards` (read-only) with **Pinterest account** OAuth2.

1. Complete Pinterest developer app + n8n **Connect my account** first.
2. Run this workflow manually.
3. Confirm username and at least one board id are returned.
4. Copy a board id into `PINTEREST_BOARD_ID` (later step).
5. Keep `DRY_RUN=true` — publisher Pin create stays blocked.
"""
    nodes = [
        sticky("pinprobe", "Note", note, [-400, -240], 420, 360, 4),
        node("pinprobe", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get("pinprobe", "Load Config", f"{TRACKING}/config", [240, 0]),
        http_get("pinprobe", "Pinterest Readiness", f"{TRACKING}/pinterest/readiness", [480, 0]),
        code(
            "pinprobe",
            "Guard Dry Run",
            """
const config = $('Load Config').first().json;
const readiness = $json;
if (config.dry_run !== true) {
  throw new Error('Refusing Pinterest probe while DRY_RUN is not true.');
}
return [{ json: {
  dry_run: true,
  readiness,
  board_id_configured: Boolean(String(config.pinterest_board_id || '').trim()),
  note: 'About to call user_account + boards — read only, no Pin create.'
} }];
""",
            [720, 0],
        ),
        node(
            "pinprobe",
            "Get User Account",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "https://api.pinterest.com/v5/user_account",
                "authentication": "genericCredentialType",
                "genericAuthType": "oAuth2Api",
                "options": {"timeout": 60000},
            },
            [980, -80],
            credentials=PINTEREST_CRED,
            onError="continueRegularOutput",
        ),
        node(
            "pinprobe",
            "List Boards",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "https://api.pinterest.com/v5/boards",
                "sendQuery": True,
                "queryParameters": {
                    "parameters": [
                        {"name": "page_size", "value": "25"},
                    ]
                },
                "authentication": "genericCredentialType",
                "genericAuthType": "oAuth2Api",
                "options": {"timeout": 60000},
            },
            [980, 120],
            credentials=PINTEREST_CRED,
            onError="continueRegularOutput",
        ),
        code(
            "pinprobe",
            "Summarize Probe",
            """
const readiness = $('Pinterest Readiness').first().json;
const account = $('Get User Account').first().json;
const boardsRaw = $('List Boards').first().json;
const accountErr = account.error || account.message || null;
const boardsErr = boardsRaw.error || boardsRaw.message || null;
const items = Array.isArray(boardsRaw.items) ? boardsRaw.items : [];
const boards = items.map((b) => ({
  id: b.id,
  name: b.name || null,
  privacy: b.privacy || null,
}));
const username = account.username || account.business_name || null;
const oauthOk = !accountErr && !boardsErr && Boolean(username);
return [{ json: {
  dry_run: true,
  publish_blocked_by_dry_run: true,
  pin_create_attempted: false,
  oauth_ok: oauthOk,
  username,
  account_type: account.account_type || null,
  boards_found: boards,
  boards_count: boards.length,
  error: (accountErr || boardsErr)
    ? (typeof (accountErr || boardsErr) === 'string'
        ? (accountErr || boardsErr)
        : ((accountErr || boardsErr).message || JSON.stringify(accountErr || boardsErr).slice(0, 400)))
    : null,
  readiness,
  next: oauthOk
    ? 'OAuth works. Set PINTEREST_BOARD_ID from boards_found[].id. Keep DRY_RUN=true.'
    : 'OAuth not connected yet. Finish Pinterest app + n8n Connect my account.',
} }];
""",
            [1240, 0],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "Pinterest Readiness"),
        ("Pinterest Readiness", "Guard Dry Run"),
        ("Guard Dry Run", "Get User Account"),
        ("Get User Account", "List Boards"),
        ("List Boards", "Summarize Probe"),
    ]
    return workflow("11 Pinterest Auth Probe", WF["pinterest_probe"], nodes, pairs)


def groq_auth_probe_workflow() -> dict:
    """Manual-only Groq key probe: list models + one tiny JSON call. Generates no social content."""
    note = """## Groq Auth Probe

Manual test only. Uses **Groq account** (Header Auth `Authorization: Bearer <key>`).
Lists models and sends one tiny JSON-mode request to `GROQ_MODEL`. No post, no preview.
"""

    def groq_http(name: str, params: dict, pos: list[int]) -> dict:
        return node(
            "groq",
            name,
            "n8n-nodes-base.httpRequest",
            4.5,
            {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "options": {"timeout": 60000}, **params},
            pos,
            credentials=GROQ_CRED,
            onError="continueRegularOutput",
        )

    nodes = [
        sticky("groq", "Note", note, [-400, -220], 380, 220, 5),
        node("groq", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get("groq", "Load Config", f"{TRACKING}/config", [240, 0]),
        groq_http("List Models", {"method": "GET", "url": "https://api.groq.com/openai/v1/models"}, [480, 0]),
        groq_http(
            "JSON Test Call",
            {
                "method": "POST",
                "url": GROQ_CHAT_URL,
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ JSON.stringify({ model: $('Load Config').first().json.groq_model || 'qwen/qwen3.8-27b', messages: [{ role: 'user', content: 'Return JSON only: {\"ok\": true}' }], response_format: { type: 'json_object' }, max_completion_tokens: 50, ...((($('Load Config').first().json.groq_model || 'qwen/').startsWith('qwen/')) ? { reasoning_effort: 'none' } : {}) }) }}",
            },
            [720, 0],
        ),
        code(
            "groq",
            "Summarize Probe",
            """
const config = $('Load Config').first().json;
const models = $('List Models').first().json;
const chat = $json;
const errText = (r) => r && r.error ? String(r.error.description || r.error.message || JSON.stringify(r.error)).slice(0, 300) : null;
const ids = (models.data || []).map((m) => m.id);
const wanted = config.groq_model || 'qwen/qwen3.8-27b';
const reply = (((chat.choices || [])[0] || {}).message || {}).content || null;
return [{ json: {
  dry_run: config.dry_run,
  ai_fallback_provider: config.ai_fallback_provider,
  groq_model: wanted,
  key_ok: !models.error && ids.length > 0,
  models_count: ids.length,
  model_available: ids.includes(wanted),
  json_call_ok: !chat.error && Boolean(reply),
  reply,
  models_error: errText(models),
  chat_error: errText(chat),
} }];
""",
            [960, 0],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "List Models"),
        ("List Models", "JSON Test Call"),
        ("JSON Test Call", "Summarize Probe"),
    ]
    return workflow("12 Groq Auth Probe", WF["groq_probe"], nodes, pairs)


def live_reel_test_workflow(
    product_id: int = 17,
    platforms: tuple[str, ...] = ("instagram", "facebook", "youtube"),
    title: str = "13 Live Reel Test",
    wf_id: str = WF["live_reel"],
) -> dict:
    """Manual-only, explicitly approved live test: one Reel to Instagram + Facebook Page + private YouTube Short.

    Ignores global DRY_RUN on purpose (the daily publisher keeps it), refuses products already published,
    uploads the local file directly (no public URL needed), and records results in tracking.
    """
    wf = "live"
    graph = "https://graph.facebook.com/' + $('Prepare Live Job').first().json.version + '"
    note = f"""## LIVE Reel Test (manual only)

Posts **Product {product_id}** for real:
- Instagram Reel (resumable upload + wait for FINISHED + media_publish)
- Facebook Page Reel (video_reels start/upload/finish)
- YouTube Short (privacy from `YOUTUBE_PRIVACY_STATUS`, default private)

Does not change global `DRY_RUN`. Refuses if the product is already published on any target.
"""

    def auth_header() -> dict:
        return {"name": "Authorization", "value": "={{ 'OAuth ' + $('Get Page Token').first().json.access_token }}"}

    def http(name: str, method: str, url: str, pos: list[int], *, headers: list[dict] | None = None, json_body: str | None = None,
             binary: bool = False, query: list[dict] | None = None, timeout: int = 180000) -> dict:
        params: dict = {"method": method, "url": url, "options": {"timeout": timeout}}
        if headers:
            params["sendHeaders"] = True
            params["headerParameters"] = {"parameters": headers}
        if query:
            params["sendQuery"] = True
            params["queryParameters"] = {"parameters": query}
        if json_body is not None:
            params.update({"sendBody": True, "contentType": "raw", "rawContentType": "application/json", "body": json_body})
        if binary:
            params.update({"sendBody": True, "contentType": "binaryData", "inputDataFieldName": "data"})
        return node(wf, name, "n8n-nodes-base.httpRequest", 4.5, params, pos, onError="continueRegularOutput")

    def read_video(name: str, pos: list[int]) -> dict:
        return node(
            wf,
            name,
            "n8n-nodes-base.readWriteFile",
            1,
            {"operation": "read", "fileSelector": "={{ $('Prepare Live Job').first().json.local_path }}", "options": {"dataPropertyName": "data"}},
            pos,
            onError="continueRegularOutput",
        )

    def record(name: str, result_node: str, pos: list[int]) -> dict:
        r = "$('" + result_node + "').first().json"
        return http_post_json(
            wf,
            name,
            "={{ " + r + ".skip_record ? '" + TRACKING + "/logs' : '" + TRACKING + f"/products/{product_id}/platform-result' }}}}",
            "={{ JSON.stringify(" + r + ".skip_record"
            + " ? { level: 'info', event: 'live_test_platform_not_selected', product_id: " + str(product_id) + ", platform: " + r + ".platform, message: 'Not part of this live test; tracking unchanged' }"
            + " : { platform: " + r + ".platform, status: " + r + ".status, post_id: " + r + ".post_id || null, error_message: " + r + ".error_message || null }) }}",
            pos,
            onError="continueRegularOutput",
        )

    err_fn = "const errText = (r) => r && r.error ? String(r.error.description || r.error.message || JSON.stringify(r.error)).slice(0, 400) : null;"
    oauth_upload = lambda: [auth_header(), {"name": "offset", "value": "0"}, {"name": "file_size", "value": "={{ String($('Prepare Live Job').first().json.file_size) }}"}]

    prepare_js = """
const pid = __PID__;
const config = $('Load Config').first().json;
const preview = $('Load Preview').first().json;
const record = $('Load Product').first().json;
const size = $('Media Size').first().json;
if (!preview || preview.error || !preview.content) throw new Error('No saved AI preview for Product ' + pid + '. Run a DRY_RUN first.');
if (String(preview.media_type) !== 'video') throw new Error('Product ' + pid + ' is not a video; Reels need video.');
const allowed = __ALLOWED__;
const already = {};
for (const p of ['instagram', 'facebook', 'youtube']) {
  already[p] = record[p + '_status'] === 'published' || Boolean(record[p + '_post_id']) ? (record[p + '_post_id'] || 'published') : null;
}
const todo = allowed.filter((p) => !already[p]);
if (!todo.length) {
  throw new Error('Product ' + pid + ' is already published on ' + allowed.join(', ') + '. Nothing to do.');
}
if (!size || !size.bytes) throw new Error('Local video file not found for Product ' + pid + '.');
if (!config.facebook_page_id || !config.instagram_business_account_id) throw new Error('FACEBOOK_PAGE_ID / INSTAGRAM_BUSINESS_ACCOUNT_ID missing.');
const c = preview.content;
const ig = c.instagram || {};
const fb = c.facebook || {};
const yt = c.youtube || {};
const join = (b) => [b.caption, (b.hashtags || []).join(' '), b.cta].filter(Boolean).join('\\n\\n');
let ytTitle = String(yt.title || '').trim();
if (ytTitle.length > 70) ytTitle = ytTitle.slice(0, 67).trim() + '...';
const ytTags = (yt.hashtags || []).map(String);
if (!ytTags.some((h) => h.toLowerCase().replace(/^#/, '') === 'shorts')) ytTags.push('#shorts');
let ytDesc = String(yt.description || '').trim();
if (!/#shorts/i.test(ytDesc)) ytDesc += '\\n\\n#Shorts';
const tagLine = ytTags.join(' ');
if (!ytDesc.includes(tagLine)) ytDesc += '\\n' + tagLine;
return [{ json: {
  product_id: pid,
  version: config.meta_graph_version || 'v22.0',
  page_id: config.facebook_page_id,
  ig_user_id: config.instagram_business_account_id,
  local_path: size.path,
  file_size: size.bytes,
  ig_caption: join(ig),
  fb_description: join(fb),
  yt_title: ytTitle,
  yt_description: ytDesc,
  yt_tags: (yt.tags || []).join(','),
  yt_privacy: config.youtube_privacy_status || 'private',
  do_instagram: todo.includes('instagram'),
  do_facebook: todo.includes('facebook'),
  do_youtube: todo.includes('youtube'),
  existing_post_ids: already
} }];
""".replace("__PID__", str(product_id)).replace("__ALLOWED__", json.dumps(list(platforms)))
    skip_js = """
const job = $('Prepare Live Job').first().json;
if (!job.do___P__) {
  if (job.existing_post_ids.__P__) {
    return [{ json: { product_id: job.product_id, platform: '__P__', status: 'published', post_id: job.existing_post_ids.__P__, url: null, skipped_already_published: true } }];
  }
  return [{ json: { product_id: job.product_id, platform: '__P__', status: 'not_in_this_test', skip_record: true } }];
}
"""

    def skip_guard(platform: str) -> str:
        return skip_js.replace("__P__", platform)

    nodes = [
        sticky(wf, "Note", note, [-420, -300], 400, 300, 3),
        node(wf, "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get(wf, "Load Config", f"{TRACKING}/config", [200, 0]),
        http_get(wf, "Load Preview", f"{TRACKING}/previews/{product_id}", [400, 0], onError="continueRegularOutput"),
        http_get(wf, "Load Product", f"{TRACKING}/products/{product_id}", [600, 0]),
        http_get(wf, "Media Size", "={{ '" + TRACKING + "/media/size?name=' + encodeURIComponent($('Load Preview').first().json.filename || '') }}", [800, 0], onError="continueRegularOutput"),
        code(wf, "Prepare Live Job", prepare_js, [1000, 0]),
        *page_token_guard_nodes(wf, "$('Prepare Live Job').first().json.version", "$('Prepare Live Job').first().json.page_id", [1100, -200]),
        iff(wf, "Page Verified?", "={{ $json.guard_ok }}", TRUE, True, [1250, 0]),
        node(
            wf,
            "Stop Not Page",
            "n8n-nodes-base.stopAndError",
            1,
            {"errorType": "errorMessage", "errorMessage": "={{ 'Refusing to post: ' + $json.error }}"},
            [1400, 200],
        ),
        # Instagram Reel
        http(
            "IG Create Container",
            "POST",
            "={{ '" + graph + "/' + $('Prepare Live Job').first().json.ig_user_id + '/media' }}",
            [1400, 0],
            headers=[auth_header()],
            json_body="={{ JSON.stringify({ media_type: 'REELS', upload_type: 'resumable', share_to_feed: true, caption: $('Prepare Live Job').first().json.ig_caption }) }}",
        ),
        read_video("Read Video IG", [1600, 0]),
        http(
            "IG Upload",
            "POST",
            "={{ 'https://rupload.facebook.com/ig-api-upload/' + $('Prepare Live Job').first().json.version + '/' + $('IG Create Container').first().json.id }}",
            [1800, 0],
            headers=oauth_upload(),
            binary=True,
            timeout=300000,
        ),
        http(
            "IG Check Status",
            "GET",
            "={{ '" + graph + "/' + $('IG Create Container').first().json.id + '?fields=status_code,status' }}",
            [2000, 0],
            headers=[auth_header()],
            timeout=60000,
        ),
        code(
            wf,
            "IG Status Gate",
            err_fn
            + """
const created = $('IG Create Container').first().json;
const upload = $('IG Upload').first().json;
const status = $json;
const attempt = $runIndex;
const firstErr = errText(created) || (created.id ? null : 'Container create returned no id') || errText(upload) || errText(status);
if (firstErr) return [{ json: { state: 'fail', error: firstErr } }];
const code = String(status.status_code || '');
if (code === 'FINISHED') return [{ json: { state: 'ready', attempt } }];
if (code === 'ERROR' || code === 'EXPIRED') return [{ json: { state: 'fail', error: 'Instagram processing ' + code + ': ' + (status.status || '') } }];
if (attempt >= 30) return [{ json: { state: 'fail', error: 'Instagram processing timed out (' + code + ')' } }];
return [{ json: { state: 'wait', attempt, status_code: code } }];
""",
            [2200, 0],
        ),
        iff(wf, "IG Ready?", "={{ $json.state }}", EQ_STR, "ready", [2400, 0]),
        iff(wf, "IG Keep Waiting?", "={{ $json.state }}", EQ_STR, "wait", [2400, 220]),
        node(wf, "IG Wait", "n8n-nodes-base.wait", 1.1, {"resume": "timeInterval", "amount": 10, "unit": "seconds"}, [2600, 320]),
        http(
            "IG Publish",
            "POST",
            "={{ '" + graph + "/' + $('Prepare Live Job').first().json.ig_user_id + '/media_publish' }}",
            [2600, -100],
            headers=[auth_header()],
            json_body="={{ JSON.stringify({ creation_id: $('IG Create Container').first().json.id }) }}",
        ),
        http(
            "IG Permalink",
            "GET",
            "={{ '" + graph + "/' + $json.id + '?fields=id,permalink' }}",
            [2800, -100],
            headers=[auth_header()],
            timeout=60000,
        ),
        code(
            wf,
            "IG Result",
            err_fn
            + skip_guard("instagram")
            + """
const gate = $('IG Status Gate').last().json;
let pub = null;
let link = null;
try { pub = $('IG Publish').first().json; } catch (e) {}
try { link = $('IG Permalink').first().json; } catch (e) {}
const base = { product_id: $('Prepare Live Job').first().json.product_id, platform: 'instagram' };
if (gate.state !== 'ready') return [{ json: { ...base, status: 'failed', error_message: gate.error } }];
if (!pub || pub.error || !pub.id) return [{ json: { ...base, status: 'failed', error_message: errText(pub) || 'media_publish returned no id' } }];
return [{ json: { ...base, status: 'published', post_id: pub.id, url: (link && link.permalink) || null } }];
""",
            [3000, 0],
        ),
        record("Record IG", "IG Result", [3200, 0]),
        # Facebook Page Reel
        http(
            "FB Start",
            "POST",
            "={{ '" + graph + "/' + $('Prepare Live Job').first().json.page_id + '/video_reels' }}",
            [3400, 0],
            headers=[auth_header()],
            json_body="={{ JSON.stringify({ upload_phase: 'start' }) }}",
        ),
        read_video("Read Video FB", [3600, 0]),
        http(
            "FB Upload",
            "POST",
            "={{ $('FB Start').first().json.upload_url || ('https://rupload.facebook.com/video-upload/' + $('Prepare Live Job').first().json.version + '/' + $('FB Start').first().json.video_id) }}",
            [3800, 0],
            headers=oauth_upload(),
            binary=True,
            timeout=300000,
        ),
        http(
            "FB Finish",
            "POST",
            "={{ '" + graph + "/' + $('Prepare Live Job').first().json.page_id + '/video_reels' }}",
            [4000, 0],
            headers=[auth_header()],
            query=[
                {"name": "upload_phase", "value": "finish"},
                {"name": "video_id", "value": "={{ $('FB Start').first().json.video_id }}"},
                {"name": "video_state", "value": "PUBLISHED"},
                {"name": "description", "value": "={{ $('Prepare Live Job').first().json.fb_description }}"},
            ],
        ),
        code(
            wf,
            "FB Result",
            err_fn
            + skip_guard("facebook")
            + """
const start = $('FB Start').first().json;
const upload = $('FB Upload').first().json;
const finish = $('FB Finish').first().json;
const owner = $json;
const pageId = String($('Prepare Live Job').first().json.page_id);
const base = { product_id: $('Prepare Live Job').first().json.product_id, platform: 'facebook' };
const err = errText(start) || (start.video_id ? null : 'video_reels start returned no video_id') || errText(upload) || errText(finish);
if (err || finish.success !== true) return [{ json: { ...base, status: 'failed', error_message: err || ('finish response: ' + JSON.stringify(finish).slice(0, 300)) } }];
const ownerId = owner.from ? String(owner.from.id) : null;
if (ownerId && ownerId !== pageId) {
  return [{ json: { ...base, status: 'failed', post_id: start.video_id, error_message: 'Posted as ' + owner.from.name + ' (' + ownerId + '), not Page ' + pageId } }];
}
return [{ json: { ...base, status: 'published', post_id: start.video_id, owner: owner.from || null, owner_verified: ownerId === pageId, url: 'https://www.facebook.com/reel/' + start.video_id } }];
""",
            [4200, 0],
        ),
        http(
            "FB Verify Owner",
            "GET",
            "={{ '" + graph + "/' + $('FB Start').first().json.video_id + '?fields=id,from{id,name},permalink_url' }}",
            [4100, 160],
            headers=[auth_header()],
            timeout=60000,
        ),
        record("Record FB", "FB Result", [4400, 0]),
        # YouTube Short
        read_video("Read Video YT", [4600, 0]),
        node(
            wf,
            "YouTube Upload",
            "n8n-nodes-base.youTube",
            1,
            {
                "resource": "video",
                "operation": "upload",
                "title": "={{ $('Prepare Live Job').first().json.yt_title }}",
                "regionCode": "US",
                "categoryId": "28",
                "binaryProperty": "data",
                "options": {
                    "description": "={{ $('Prepare Live Job').first().json.yt_description }}",
                    "privacyStatus": "={{ $('Prepare Live Job').first().json.yt_privacy }}",
                    "tags": "={{ $('Prepare Live Job').first().json.yt_tags }}",
                },
            },
            [4800, 0],
            credentials={"youTubeOAuth2Api": {"id": "youTubeOAuth2Api", "name": "YouTube account"}},
            onError="continueRegularOutput",
        ),
        code(
            wf,
            "YT Result",
            err_fn
            + skip_guard("youtube")
            + """
const r = $json;
const base = { product_id: $('Prepare Live Job').first().json.product_id, platform: 'youtube' };
const id = r.id || r.videoId || r.uploadId;
if (r.error || !id) return [{ json: { ...base, status: 'failed', error_message: errText(r) || ('No video id: ' + JSON.stringify(r).slice(0, 300)) } }];
return [{ json: { ...base, status: 'published', post_id: id, url: 'https://youtube.com/shorts/' + id, privacy: $('Prepare Live Job').first().json.yt_privacy } }];
""",
            [5000, 0],
        ),
        record("Record YT", "YT Result", [5200, 0]),
        iff(wf, "Do IG?", "={{ $('Prepare Live Job').first().json.do_instagram }}", TRUE, True, [1300, 160]),
        iff(wf, "Do FB?", "={{ $('Prepare Live Job').first().json.do_facebook }}", TRUE, True, [3300, 160]),
        iff(wf, "Do YT?", "={{ $('Prepare Live Job').first().json.do_youtube }}", TRUE, True, [4500, 160]),
        code(
            wf,
            "Live Summary",
            """
const pick = (n) => { const j = $(n).first().json; return { status: j.status, post_id: j.post_id || null, url: j.url || null, error: j.error_message || null }; };
return [{ json: {
  product_id: $('Prepare Live Job').first().json.product_id,
  page: $('Get Page Token').first().json.name || null,
  instagram: pick('IG Result'),
  facebook: pick('FB Result'),
  youtube: { ...pick('YT Result'), privacy: $('Prepare Live Job').first().json.yt_privacy },
  global_dry_run_unchanged: $('Load Config').first().json.dry_run
} }];
""",
            [5400, 0],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "Load Preview"),
        ("Load Preview", "Load Product"),
        ("Load Product", "Media Size"),
        ("Media Size", "Prepare Live Job"),
        ("Prepare Live Job", "Get Page Token"),
        ("Get Page Token", "Verify Page Identity"),
        ("Verify Page Identity", "Page Guard"),
        ("Page Guard", "Page Verified?"),
        ("Page Verified?", "Do IG?", 0),
        ("Page Verified?", "Stop Not Page", 1),
        ("Do IG?", "IG Create Container", 0),
        ("Do IG?", "IG Result", 1),
        ("IG Create Container", "Read Video IG"),
        ("Read Video IG", "IG Upload"),
        ("IG Upload", "IG Check Status"),
        ("IG Check Status", "IG Status Gate"),
        ("IG Status Gate", "IG Ready?"),
        ("IG Ready?", "IG Publish", 0),
        ("IG Ready?", "IG Keep Waiting?", 1),
        ("IG Keep Waiting?", "IG Wait", 0),
        ("IG Keep Waiting?", "IG Result", 1),
        ("IG Wait", "IG Check Status"),
        ("IG Publish", "IG Permalink"),
        ("IG Permalink", "IG Result"),
        ("IG Result", "Record IG"),
        ("Record IG", "Do FB?"),
        ("Do FB?", "FB Start", 0),
        ("Do FB?", "FB Result", 1),
        ("FB Start", "Read Video FB"),
        ("Read Video FB", "FB Upload"),
        ("FB Upload", "FB Finish"),
        ("FB Finish", "FB Verify Owner"),
        ("FB Verify Owner", "FB Result"),
        ("FB Result", "Record FB"),
        ("Record FB", "Do YT?"),
        ("Do YT?", "Read Video YT", 0),
        ("Do YT?", "YT Result", 1),
        ("Read Video YT", "YouTube Upload"),
        ("YouTube Upload", "YT Result"),
        ("YT Result", "Record YT"),
        ("Record YT", "Live Summary"),
    ]
    return workflow(title, wf_id, nodes, pairs)


def live_pinterest_video_workflow(product_id: int = 17) -> dict:
    """Manual-only, explicitly approved live test: one Pinterest video Pin (register → S3 upload → poll → create)."""
    wf = "livepin"
    note = f"""## LIVE Pinterest Video Pin (manual only)

Posts **Product {product_id}** as a video Pin to `PINTEREST_BOARD_ID`:
1. `POST /v5/media` (media_type video)
2. tracking-api uploads the local file to the returned S3 form
3. Poll `GET /v5/media/{{id}}` until `succeeded`
4. `POST /v5/pins` with `media_source.source_type = video_id`

Does not change global `DRY_RUN`. Refuses if already published on Pinterest.
"""

    def pin_http(name: str, method: str, url: str, pos: list[int], json_body: str | None = None) -> dict:
        params: dict = {"method": method, "url": url, "authentication": "genericCredentialType", "genericAuthType": "oAuth2Api", "options": {"timeout": 120000}}
        if json_body is not None:
            params.update({"sendBody": True, "contentType": "raw", "rawContentType": "application/json", "body": json_body})
        return node(wf, name, "n8n-nodes-base.httpRequest", 4.5, params, pos, credentials=dict(PINTEREST_CRED), onError="continueRegularOutput")

    err_fn = "const errText = (r) => r && (r.error || (r.code && r.message)) ? String((r.error && (r.error.description || r.error.message)) || r.message || JSON.stringify(r.error)).slice(0, 400) : null;"
    prepare_js = """
const pid = __PID__;
const config = $('Load Config').first().json;
const preview = $('Load Preview').first().json;
const record = $('Load Product').first().json;
if (!preview || preview.error || !preview.content) throw new Error('No saved AI preview for Product ' + pid + '.');
if (String(preview.media_type) !== 'video') throw new Error('Product ' + pid + ' is not a video.');
if (record.pinterest_status === 'published' || record.pinterest_post_id) throw new Error('Product ' + pid + ' is already published on Pinterest. Refusing duplicate.');
if (!config.pinterest_board_id) throw new Error('PINTEREST_BOARD_ID is missing.');
const p = preview.content.pinterest || {};
const tags = (p.hashtags || []).join(' ');
let description = [p.description, tags].filter(Boolean).join('\\n\\n');
if (description.length > 800) description = description.slice(0, 797) + '...';
return [{ json: {
  product_id: pid,
  board_id: config.pinterest_board_id,
  filename: preview.filename,
  title: String(p.title || '').slice(0, 100),
  description,
  alt_text: String(p.title || preview.vision_notes || '').slice(0, 500)
} }];
""".replace("__PID__", str(product_id))

    nodes = [
        sticky(wf, "Note", note, [-420, -300], 400, 300, 3),
        node(wf, "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 0]),
        http_get(wf, "Load Config", f"{TRACKING}/config", [200, 0]),
        http_get(wf, "Load Preview", f"{TRACKING}/previews/{product_id}", [400, 0], onError="continueRegularOutput"),
        http_get(wf, "Load Product", f"{TRACKING}/products/{product_id}", [600, 0]),
        code(wf, "Prepare Pin Job", prepare_js, [800, 0]),
        pin_http("Register Media", "POST", "https://api.pinterest.com/v5/media", [1000, 0], "={{ JSON.stringify({ media_type: 'video' }) }}"),
        http_post_json_object(
            wf,
            "S3 Upload",
            f"{TRACKING}/pinterest/s3-upload",
            "{ upload_url: $json.upload_url, upload_parameters: $json.upload_parameters, name: $('Prepare Pin Job').first().json.filename }",
            [1200, 0],
            onError="continueRegularOutput",
        ),
        pin_http("Check Media", "GET", "={{ 'https://api.pinterest.com/v5/media/' + $('Register Media').first().json.media_id }}", [1400, 0]),
        code(
            wf,
            "Media Gate",
            err_fn
            + """
const reg = $('Register Media').first().json;
const up = $('S3 Upload').first().json;
const media = $json;
const attempt = $runIndex;
const firstErr = errText(reg) || (reg.media_id ? null : 'Register media returned no media_id: ' + JSON.stringify(reg).slice(0, 300))
  || (up.ok ? null : 'S3 upload failed: ' + (up.error || up.status))
  || errText(media);
if (firstErr) return [{ json: { state: 'fail', error: firstErr } }];
const status = String(media.status || '');
if (status === 'succeeded') return [{ json: { state: 'ready', attempt } }];
if (status === 'failed') return [{ json: { state: 'fail', error: 'Pinterest video processing failed' } }];
if (attempt >= 30) return [{ json: { state: 'fail', error: 'Pinterest processing timed out (' + status + ')' } }];
return [{ json: { state: 'wait', attempt, status } }];
""",
            [1600, 0],
        ),
        iff(wf, "Media Ready?", "={{ $json.state }}", EQ_STR, "ready", [1800, 0]),
        iff(wf, "Keep Waiting?", "={{ $json.state }}", EQ_STR, "wait", [1800, 220]),
        node(wf, "Wait", "n8n-nodes-base.wait", 1.1, {"resume": "timeInterval", "amount": 10, "unit": "seconds"}, [2000, 320]),
        pin_http(
            "Create Pin",
            "POST",
            "https://api.pinterest.com/v5/pins",
            [2000, -100],
            "={{ JSON.stringify({ board_id: $('Prepare Pin Job').first().json.board_id, title: $('Prepare Pin Job').first().json.title, description: $('Prepare Pin Job').first().json.description, alt_text: $('Prepare Pin Job').first().json.alt_text, media_source: { source_type: 'video_id', media_id: $('Register Media').first().json.media_id, cover_image_key_frame_time: 1 } }) }}",
        ),
        code(
            wf,
            "Pin Result",
            err_fn
            + """
const gate = $('Media Gate').last().json;
let pin = null;
try { pin = $('Create Pin').first().json; } catch (e) {}
const base = { product_id: $('Prepare Pin Job').first().json.product_id, platform: 'pinterest' };
if (gate.state !== 'ready') return [{ json: { ...base, status: 'failed', error_message: gate.error } }];
if (!pin || errText(pin) || !pin.id) return [{ json: { ...base, status: 'failed', error_message: errText(pin) || ('Create Pin returned no id: ' + JSON.stringify(pin).slice(0, 300)) } }];
return [{ json: { ...base, status: 'published', post_id: pin.id, url: 'https://www.pinterest.com/pin/' + pin.id + '/' } }];
""",
            [2200, 0],
        ),
        http_post_json(
            wf,
            "Record Pinterest",
            f"{TRACKING}/products/{product_id}/platform-result",
            "={{ JSON.stringify({ platform: 'pinterest', status: $json.status, post_id: $json.post_id || null, error_message: $json.error_message || null }) }}",
            [2400, 0],
            onError="continueRegularOutput",
        ),
        code(
            wf,
            "Live Summary",
            """
const r = $('Pin Result').first().json;
return [{ json: { product_id: r.product_id, pinterest: { status: r.status, post_id: r.post_id || null, url: r.url || null, error: r.error_message || null }, global_dry_run_unchanged: $('Load Config').first().json.dry_run } }];
""",
            [2600, 0],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "Load Preview"),
        ("Load Preview", "Load Product"),
        ("Load Product", "Prepare Pin Job"),
        ("Prepare Pin Job", "Register Media"),
        ("Register Media", "S3 Upload"),
        ("S3 Upload", "Check Media"),
        ("Check Media", "Media Gate"),
        ("Media Gate", "Media Ready?"),
        ("Media Ready?", "Create Pin", 0),
        ("Media Ready?", "Keep Waiting?", 1),
        ("Keep Waiting?", "Wait", 0),
        ("Keep Waiting?", "Pin Result", 1),
        ("Wait", "Check Media"),
        ("Create Pin", "Pin Result"),
        ("Pin Result", "Record Pinterest"),
        ("Record Pinterest", "Live Summary"),
    ]
    return workflow("14 Live Pinterest Video Pin", WF["live_pin"], nodes, pairs)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    docs = [
        ("08-error-logger.json", error_workflow()),
        ("03-ai-content.json", ai_workflow()),
        ("04-instagram.json", instagram_workflow()),
        ("05-facebook.json", facebook_workflow()),
        ("06-pinterest.json", pinterest_workflow()),
        ("07-youtube.json", youtube_workflow()),
        ("09-meta-auth-probe.json", meta_auth_probe_workflow()),
        ("10-youtube-auth-probe.json", youtube_auth_probe_workflow()),
        ("11-pinterest-auth-probe.json", pinterest_auth_probe_workflow()),
        ("12-groq-auth-probe.json", groq_auth_probe_workflow()),
        ("13-live-reel-test.json", live_reel_test_workflow()),
        ("14-live-pinterest-video.json", live_pinterest_video_workflow()),
        ("15-live-facebook-reel.json", live_reel_test_workflow(16, ("facebook",), "15 Live Facebook Reel Test", WF["live_fb"])),
        ("16-queue-preparer.json", queue_preparer_workflow()),
        ("01-daily-publisher.json", daily_workflow()),
        ("02-admin-control.json", admin_workflow()),
    ]
    errors: list[str] = []
    for filename, doc in docs:
        errors.extend(validate(doc))
        (OUT / filename).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"Wrote {filename} ({len(doc['nodes'])} nodes)")
    if errors:
        raise SystemExit("Workflow validation failed:\n" + "\n".join(errors))
    print("All workflows valid.")


if __name__ == "__main__":
    main()
