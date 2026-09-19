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
}

TRACKING = "http://tracking-api:8081"
DRIVE_CRED = {"googleDriveOAuth2Api": {"id": "googleDriveOAuth2Api", "name": "Google Drive account"}}
GEMINI_CRED = {"googlePalmApi": {"id": "googlePalmApi", "name": "Google Gemini account"}}
META_CRED = {"facebookGraphApi": {"id": "facebookGraphApi", "name": "Facebook Graph account"}}
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
            "## Vision AI (Gemini free tier)\nInspects the Google Drive product image (or a video frame).\n\n**Provider:** Google Gemini via n8n credential **Google Gemini account** (`googlePalmApi`).\n**Model:** `gemini-3.6-flash` (vision, Google AI Studio free tier), with free-tier fallbacks if Google returns high-demand/404.\n\nChatGPT Pro is not used. OpenAI API is not used. No mock AI.\nEnglish only. USA, Canada, UK, Australia. No invented specs. No website URL.\n\nTo add another provider later: extend **Build Provider Payload** and **Provider Switch**.",
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
const payload = { ...job, config, ai_provider: provider, request_url, request_body, gemini_model, gemini_fallback_models, gemini_host: String(config.gemini_host || 'https://generativelanguage.googleapis.com').replace(/\\/$/, '') };
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
  throw new Error('Gemini error: ' + detail);
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
            "Normalize AI JSON",
            """
const job = $json;
const raw = job.gemini_raw || $json;
if (raw.error) {
  throw new Error('Gemini error: ' + (raw.error.message || JSON.stringify(raw.error)));
}
let text = '';
if (raw.candidates && raw.candidates[0] && raw.candidates[0].content && raw.candidates[0].content.parts) {
  text = raw.candidates[0].content.parts.map((part) => part.text || '').join('');
}
if (!text && raw.text) text = raw.text;
if (!text) {
  throw new Error('Gemini returned no content. Open Credentials → Google Gemini account and paste a free Google AI Studio API key.');
}
text = String(text).trim().replace(/^```json\\s*/i, '').replace(/```$/i, '').trim();
let content;
try { content = JSON.parse(text); }
catch (e) { throw new Error('Gemini did not return valid JSON: ' + e.message); }
if (!content.instagram || !content.facebook || !content.pinterest || !content.youtube) {
  throw new Error('Gemini JSON is missing a platform block. Refusing to invent copy.');
}
const modelUsed = job.gemini_model_used || job.gemini_model || 'gemini-3.6-flash';
delete job.request_body;
delete job.vision_base64;
delete job.gemini_raw;
delete job.gemini_fallback_models;
delete job.need_fallback;
return [{ json: { ...job, content, ai_provider_used: job.ai_provider || 'gemini', gemini_model_used: modelUsed, vision_notes: content.vision_notes } }];
""",
            [2220, -80],
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
        ("Need Gemini Fallback?", "Normalize AI JSON", 1),
        ("Gemini Vision Fallback", "Attach Fallback Raw"),
        ("Attach Fallback Raw", "Normalize AI JSON"),
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


def facebook_workflow() -> dict:
    note = """## Facebook Page (official Meta Graph API)

Publishes to a Page:
- Images: `POST /{page-id}/photos`
- Videos: `POST /{page-id}/videos`

Requires:
- n8n credential **Facebook Graph account** (Page access token with `pages_manage_posts`)
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
        node(
            "facebook",
            "Publish Official API",
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
            [1480, -120],
            credentials=META_CRED,
            onError="continueRegularOutput",
        ),
        code(
            "facebook",
            "Interpret Result",
            """
const prepared = $('Prepare Facebook Job').first().json;
const response = $json;
if (response.error) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'facebook',
    status: 'failed',
    error_message: response.error.message || JSON.stringify(response.error)
  } }];
}
const postId = response.id || response.post_id || null;
if (!postId) {
  return [{ json: {
    product_id: prepared.product_id,
    platform: 'facebook',
    status: 'failed',
    error_message: 'No Facebook post id in response: ' + JSON.stringify(response).slice(0, 400)
  } }];
}
return [{ json: {
  product_id: prepared.product_id,
  platform: 'facebook',
  status: 'published',
  post_id: String(postId)
} }];
""",
            [1720, -120],
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
        ("Prepare Facebook Job", "Publish Official API"),
        ("Publish Official API", "Interpret Result"),
        ("Interpret Result", "Store Platform Result"),
        ("Blocked Result", "Store Platform Result"),
    ]
    return workflow("05 Facebook Publisher", WF["facebook"], nodes, pairs)


def pinterest_workflow() -> dict:
    note = """## Pinterest (official API v5)

Creates **image Pins** only, using `media_source.source_type = image_url` or `image_base64`.

Video products are skipped on purpose. Do not assume video Pin upload works without the media-upload dance.

Set `PINTEREST_BOARD_ID` and attach a Pinterest OAuth2 credential (generic OAuth2) to the HTTP node.
"""
    url = "https://api.pinterest.com/v5/pins"
    body = "={{ JSON.stringify({ board_id: $json.config.pinterest_board_id, title: $json.content.pinterest.title, description: $json.content.pinterest.description, alt_text: $json.content.pinterest.title, media_source: { source_type: 'image_url', url: $json.public_media_url } }) }}"
    wf = platform_workflow("pinterest", WF["pinterest"], "06 Pinterest Publisher", note, url, body, "$('When Called by Another Workflow').first().json.media_type === 'video'")
    for n in wf["nodes"]:
        if n["name"] == "Publish Official API":
            n["parameters"]["authentication"] = "genericCredentialType"
            n["parameters"]["genericAuthType"] = "oAuth2Api"
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
const postId = response.id || response.videoId || (response.snippet ? response.id : null);
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


def daily_workflow() -> dict:
    nodes = [
        sticky(
            "daily",
            "Overview",
            "## Daily Publisher\nPublic Google Drive folder → download media → Gemini vision AI → preview.\n\nStops before social posting while `DRY_RUN=true`.\n\nUses the shared folder ID from config. Does not use the n8n Google Drive OAuth node for listing/download (avoids project SERVICE_DISABLED 403).",
            [-440, -40],
            320,
            340,
            6,
        ),
        node(
            "daily",
            "Every Day 9AM Kolkata",
            "n8n-nodes-base.scheduleTrigger",
            1.4,
            {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
            [0, 0],
        ),
        node("daily", "Run Manually", "n8n-nodes-base.manualTrigger", 1, {}, [0, 200]),
        trigger_sub("daily", [0, 400]),
        http_get("daily", "Load Config", f"{TRACKING}/config", [280, 160]),
        http_post_json(
            "daily",
            "Log Daily Start",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'daily_execution', message: 'Daily publisher started', details: { dry_run: $json.dry_run, timezone: $json.timezone, folder: $json.google_drive_folder_id, ai_provider: $json.ai_provider } }) }}",
            [520, 160],
        ),
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
            f"{TRACKING}/products/select-next",
            "={{ JSON.stringify({ files: $json.files || [] }) }}",
            [1480, 40],
        ),
        iff("daily", "Product Found?", "={{ $json.found }}", TRUE, True, [1720, 40]),
        http_post_json(
            "daily",
            "Log No Product",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'no_product', message: $json.reason || 'No product to process', details: $json }) }}",
            [1960, 280],
        ),
        noop("daily", "Idle", [2200, 280]),
        http_post_json(
            "daily",
            "Mark Processing",
            "={{ '" + TRACKING + "/products/' + $json.product_id + '/processing' }}",
            "={{ JSON.stringify({}) }}",
            [1960, -80],
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
  gemini_model_used: src.gemini_model_used || null,
  dry_run: dryRun,
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
        iff("daily", "DRY RUN?", "={{ $('Load Config').first().json.dry_run }}", TRUE, True, [3880, -80]),
        code(
            "daily",
            "Build Dry Run Log",
            """
const src = $json;
const ai = $('Generate AI Content').first().json;
const picked = $('Pick Vision File').first().json;
const productId = src.product_id || ai.product_id || picked.product_id;
const logBody = {
  level: 'info',
  event: 'dry_run_preview',
  product_id: productId,
  message: 'DRY_RUN saved real AI preview and skipped all social publishing',
  details: {
    product_id: productId,
    ai_provider_used: ai.ai_provider_used,
    vision_notes: ai.vision_notes,
  },
};
return [{ json: { ...src, product_id: productId, logBody } }];
""",
            [4000, -200],
        ),
        http_post_json_object(
            "daily",
            "Log Dry Run Preview",
            f"{TRACKING}/logs",
            "$json.logBody",
            [4120, -200],
        ),
        http_post_json(
            "daily",
            "Finalize Dry Run",
            "={{ '" + TRACKING + "/products/' + $('Pick Vision File').first().json.product_id + '/finalize' }}",
            "={{ JSON.stringify({}) }}",
            [4360, -200],
        ),
        execute_sub("daily", "Publish Instagram", WF["instagram"], "04 Instagram Publisher", [4120, 80], continue_on_error=True),
        execute_sub("daily", "Publish Facebook", WF["facebook"], "05 Facebook Publisher", [4360, 80], continue_on_error=True),
        execute_sub("daily", "Publish Pinterest", WF["pinterest"], "06 Pinterest Publisher", [4600, 80], continue_on_error=True),
        execute_sub("daily", "Publish YouTube", WF["youtube"], "07 YouTube Shorts Publisher", [4840, 80], continue_on_error=True),
        http_post_json(
            "daily",
            "Finalize Product",
            "={{ '" + TRACKING + "/products/' + $('Pick Vision File').first().json.product_id + '/finalize' }}",
            "={{ JSON.stringify({}) }}",
            [5080, 80],
        ),
        http_post_json(
            "daily",
            "Log Final Status",
            f"{TRACKING}/logs",
            "={{ JSON.stringify({ level: 'info', event: 'final_product_status', product_id: $json.product_id, message: 'Product ' + $json.product_id + ' status ' + $json.overall_status, details: $json }) }}",
            [5320, 80],
        ),
        sticky("daily", "Drive", "## Google Drive (public folder)\nDry-run lists/downloads via the shared folder link.\nFolder ID comes from `GOOGLE_DRIVE_FOLDER_ID`.\nDoes **not** use n8n Google Drive OAuth for media (that path returned SERVICE_DISABLED 403 even when OAuth showed connected).", [1000, 220], 320, 240, 1),
        sticky("daily", "Safety", "## DRY_RUN\nSocial publish nodes are not called until you set `DRY_RUN=false`.", [3880, -360], 280, 140, 3),
    ]
    pairs = [
        ("Every Day 9AM Kolkata", "Load Config"),
        ("Run Manually", "Load Config"),
        ("When Called by Another Workflow", "Load Config"),
        ("Load Config", "Log Daily Start"),
        ("Log Daily Start", "Drive Folder Configured?"),
        ("Drive Folder Configured?", "List Google Drive Folder", 0),
        ("Drive Folder Configured?", "Stop Missing Folder ID", 1),
        ("List Google Drive Folder", "Normalize Drive List"),
        ("Normalize Drive List", "Select Next Product"),
        ("Select Next Product", "Product Found?"),
        ("Product Found?", "Mark Processing", 0),
        ("Product Found?", "Log No Product", 1),
        ("Log No Product", "Idle"),
        ("Mark Processing", "Pick Vision File"),
        ("Pick Vision File", "Download Drive Media"),
        ("Download Drive Media", "Save Media to Disk"),
        ("Save Media to Disk", "Prepare Vision Still"),
        ("Prepare Vision Still", "Build AI Job"),
        ("Build AI Job", "Generate AI Content"),
        ("Generate AI Content", "Build Preview Payload"),
        ("Build Preview Payload", "Save Preview"),
        ("Save Preview", "DRY RUN?"),
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
3. Confirm `me/accounts` lists your Page and Instagram business account id.

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
  accounts_url: 'https://graph.facebook.com/' + version + '/me/accounts?fields=id,name,access_token,instagram_business_account',
  page_url: pageId
    ? ('https://graph.facebook.com/' + version + '/' + pageId + '?fields=id,name,instagram_business_account')
    : '',
} }];
""",
            [720, 0],
        ),
        node(
            "meta",
            "Probe me/accounts",
            "n8n-nodes-base.httpRequest",
            4.5,
            {
                "method": "GET",
                "url": "={{ $json.accounts_url }}",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "facebookGraphApi",
                "options": {"timeout": 60000},
            },
            [980, -80],
            credentials=META_CRED,
            onError="continueRegularOutput",
        ),
        code(
            "meta",
            "Summarize Probe",
            """
const built = $('Build Probe URLs').first().json;
const accounts = $json;
const pages = accounts.data || [];
const pageMatch = pages.find((p) => String(p.id) === String(built.page_id)) || pages[0] || null;
const igFromPage = pageMatch && pageMatch.instagram_business_account
  ? pageMatch.instagram_business_account.id
  : null;
return [{ json: {
  dry_run: built.dry_run,
  readiness: built.readiness,
  graph_ok: !accounts.error && Array.isArray(pages),
  error: accounts.error ? (accounts.error.message || JSON.stringify(accounts.error)) : null,
  pages_found: pages.map((p) => ({ id: p.id, name: p.name, ig: (p.instagram_business_account || {}).id || null })),
  configured_page_id: built.page_id || null,
  configured_ig_user_id: built.ig_user_id || null,
  discovered_ig_user_id: igFromPage,
  ids_match: Boolean(built.ig_user_id) && String(built.ig_user_id) === String(igFromPage || ''),
  note: 'No content was published. Keep DRY_RUN=true until you explicitly approve a live post.'
} }];
""",
            [1240, -80],
        ),
    ]
    pairs = [
        ("Run Manually", "Load Config"),
        ("Load Config", "Meta Readiness"),
        ("Meta Readiness", "Build Probe URLs"),
        ("Build Probe URLs", "Probe me/accounts"),
        ("Probe me/accounts", "Summarize Probe"),
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
