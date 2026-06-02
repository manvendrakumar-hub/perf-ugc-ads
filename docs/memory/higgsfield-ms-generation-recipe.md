---
name: higgsfield-ms-generation-recipe
description: Working recipe + gotchas for generating Marketing Studio UGC videos (avatar + product) via the Higgsfield MCP tools
metadata: 
  node_type: memory
  type: reference
  originSessionId: ba3f6ae6-9dfa-4f1c-bba7-bf8ebabe9f10
---

How to generate a Product-First Marketing Studio video with a custom avatar + product (learned 2026-06-01, Vincent Chase PID 131309). This is the **A.1 Talking Head** recipe — 🔒 LOCKED. Relates to [[ugc-ads-system]] and [[higgsfield-avatars]]. (A.2 Split Screen Edit and A.3 Product Modelling are not yet locked.)

**Product setup:** Auto URL scrape (`show_marketing_studio action=fetch type=product url=...`) FAILS for Lenskart ("No product images passed validation" — site blocks scraper, returns 403). Workaround: download product images locally with browser headers (`curl -A <browser UA> -e https://www.lenskart.com/`), then `media_upload` (presigned PUT) → `media_confirm` → `show_marketing_studio action=create type=product` with `medias:[{value:<media_id>, type:"media_input", url:<cdn_url>, role:"image"}]`.

**Avatar setup:** `show_marketing_studio action=create type=avatar` with `avatars:[{name, medias:[{value:<image_job_id>, type:"image_job"}]}]` (max 4 per call). Returns avatar entity id.

**Generation (the key part):** `generate_video` with:
- `model: "marketing_studio_video"`
- `prompt`: brief + the EXACT spoken VO line (server auto-expands into a full shot breakdown and lip-syncs the VO verbatim; Hinglish in Latin script works, prompt_language stays "en")
- `product_ids: ["<product uuid>"]`
- `avatars: [{"id":"<avatar uuid>","type":"custom"}]`  ← MUST be object form, not a string
- `aspect_ratio:"9:16"`, `generate_audio:true`

**GOTCHAS:**
- `get_cost:true` preflight FALSELY reports product_ids/avatars/mode as "not supported / omitted" — IGNORE it. The real (non-preflight) call binds them correctly (confirmed in job params: avatars + products populated).
- `mode`/preset (e.g. "Product Review") is NOT accepted via MCP — defaults to `mode:"ugc"`. Preset choice must be done in the Higgsfield UI if needed.
- `folder_id` expects a UUID; a Lenskart PID number like `131309` is rejected. Can't target a named folder by number via API.
- `ad_reference` (type) is for cloning an uploaded reference VIDEO — not for avatar+product binding.
- All Higgsfield video models cap at 15s. Cost ≈ 75 credits per 15s MS video. Render can take many minutes when queue is busy.

**Poll:** `job_status(jobId, sync=true)` (waits ~25s/call); download `result_url` when status=completed.
