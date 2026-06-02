---
name: ugc-ads-system
description: Structure and constraints of the UGC ads generation system being built in the Perf UGC Ads project
metadata: 
  node_type: memory
  type: project
  originSessionId: ba3f6ae6-9dfa-4f1c-bba7-bf8ebabe9f10
---

Building a scalable UGC ad generation system (user is at Lenskart, eyewear). Phase 1 = single-ad "editing" process; bulk process comes later (PID = Product ID will be the entry point for bulk).

**Skill architecture** — `ugc-ads` skill is the router (holds the hardcoded ASK-BEFORE-CREATE rule, SLCT framework, Higgsfield production reality). It routes to two iterable type files:
- `product-first-ugc.md` — ad is 100% about the product. Model: **Higgsfield Marketing Studio** (Avatar + Product).
- `yapping-ugc.md` — creator rambles on a relatable story, then pivots to product out of nowhere. Model: **Seedance 2.0** (reference-driven, consistent identity, start/end-frame chaining).

**Type taxonomy (A = Product-First, B = Yapping).** Product-First has THREE production formats sharing the same voice/script rules + SLCT output + approval gate, differing only in how they're shot/edited:
- **A.1 Talking Head** — 🔒 LOCKED (validated PID 131309). Creator straight-to-camera; MS Avatar+Product, single generation. Full recipe in [[higgsfield-ms-generation-recipe]] and the A.1 section of product-first-ugc.md.
- **A.2 Split Screen Edit** — 🔒 LOCKED (validated PID 135440). Music-driven product-flex montage in stacked split panels (2-split studio / 3-split outdoor), NO talking. Engine: **Seedance 2.0, image refs only**. Full recipe in [[seedance-split-screen-recipe]].
- **A.3 Product Modelling** — 🔒 LOCKED (validated PID 140632 John Jacobs sunglasses). Cinematic beauty showcase of the product worn on the face; replicates Pinterest refs. 3 sub-formats: **A3.1** indoor multi-frame try-on, **A3.2** outdoor cinematic jump-cuts (single flex), **A3.3** studio tight portrait. Engine: **Seedance 2.0, image refs, FULL-FRAME** (not split). Recipe + gotchas in [[seedance-split-screen-recipe]].
A.2/A.3 each get locked only after their first validated render.

**Output format (both types):** numbered ≤15s segments, each = SPOKEN (VO) + ON-SCREEN VISUAL (SLCT: Subject→Lighting/Look→Camera→Technical) + optional caption.

**Hard constraint:** every Higgsfield video model caps at 15s/generation. Default ad = 15s = 1 segment. 30/60s = segment-and-stitch (~38 words per 15s segment or speech auto-speeds-up; ~150 words for 60s). Keep identity consistent across segments.

**Sync:** the `ugc-ads` skill is packaged as `.skill` (zip) in two places kept in sync — project `Claude skills /` folder and Desktop `Claude Skills /Video Prompting/`. Re-zip both when files change. The two type files are living docs — update based on performance feedback.
