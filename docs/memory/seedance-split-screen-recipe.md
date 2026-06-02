---
name: seedance-split-screen-recipe
description: Working recipe + gotchas for generating A.2 Split-Screen product-flex UGC videos via Seedance 2.0 (Higgsfield MCP)
metadata: 
  node_type: memory
  type: reference
  originSessionId: 08eebcd1-1d1d-44cb-a314-dbcd5602c613
---

How to generate **A.2 Split-Screen Edit** videos (learned 2026-06-02, validated on PID 135440 John Jacobs rimless). This is the LOCKED A.2 path. Relates to [[ugc-ads-system]], [[higgsfield-ms-generation-recipe]] (the A.1 path), [[ugc-bot-automation]].

**What A.2 is:** a MUSIC-DRIVEN product-flex montage in a stacked split-screen layout — NO talking / NO VO / NO lip-sync (the big difference from A.1). 2-split = studio beauty (model wearing frames TOP / product rotating in-hand BOTTOM). 3-split = outdoor lifestyle (model walking TOP / POV hand holding frames MID / wide tracking BOTTOM).

**Engine: Seedance 2.0 (`seedance_2_0`), IMAGE references ONLY:**
- `medias`: `{role:"image", value:<model image_job or media_id>}` + `{role:"image", value:<product image media_id>}`.
- **Describe the split IN THE PROMPT** ("Vertical 9:16 video split into TWO/THREE equal stacked horizontal panels, all visible the whole time. TOP PANEL: … MIDDLE/BOTTOM PANEL: … Keep face identical to reference, product identical to product image").
- **3-split clean-start fix:** add "panels are SEPARATE shots locked from the VERY FIRST FRAME; no person/object spans/crosses between panels" — else the opening frame bleeds one subject across bands.
- Params: `aspect_ratio:"9:16"`, `resolution:"720p"`, `mode:"std"`, `duration:15`. ≈ **67.5 credits/clip** (preflight with `get_cost:true`; 480p+`mode:"fast"` ≈ 15 cr for cheap layout tests).

**CRITICAL GOTCHAS (do not re-learn):**
- Seedance via this MCP takes **IMAGE refs only**. A **`video` reference** (to copy a reference edit) **FAILS** (job errors, no reason). An **`audio` reference** (to bake in music) **also FAILS**. Image-only works.
- ⇒ **Music = POST step.** Generate silent, stitch the track in post (project `Music/` e.g. Sticky Floor.mp3). Higgsfield can't synthesize/attach licensed music here. (Audio-capable models Veo3/Kling can't do the split or lock identity.)
- Server may return a **preset_recommendation** (e.g. "IN THE DARK") — re-fire with `declined_preset_id:<that id>` to generate literally.
- Server force-sets `generate_audio:true` on Seedance; harmless for image-only.
- 720p/std renders can sit minutes on a busy queue; failed jobs are NOT charged.

**Models (new fashion identities):** mint via **Nano Banana Pro** (`nano_banana_pro` → routes to nano_banana_2, 1k), **bare-faced** 3:4 studio so Seedance places the real frames. Can seed from face/body refs: upload ref → pass as `image` role to generate_image, prompt "NEW distinct individual inspired by the reference aesthetic." Brighter/fairer skin needs explicit strong prompting + a reference (defaults to medium tan otherwise). Reusable library: project `Ads/_models/` (JJ-A2_male_model_LOCKED, JJ-A2_female_model_LOCKED, lib_female_01..03).

**Poll/download:** `job_status(jobId, sync=true)`; completed → `results.rawUrl`. Locals in `Ads/A2_<pid>_<slug>/raw_higgsfield/`.
