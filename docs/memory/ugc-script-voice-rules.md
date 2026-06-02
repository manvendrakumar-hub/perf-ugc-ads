---
name: ugc-script-voice-rules
description: Locked creative scripting & brand-voice rules for Lenskart UGC ads (validated on PID 131309)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ba3f6ae6-9dfa-4f1c-bba7-bf8ebabe9f10
---

Confirmed creative rules for UGC ad scripts (Hinglish, Lenskart). Locked into the `ugc-ads` skill (product-first-ugc.md). Part of the CREATIVE workflow; see [[ugc-ads-system]], [[higgsfield-avatars]], [[higgsfield-ms-generation-recipe]]. (Ops/automation lives separately in [[ugc-bot-automation]].)

- **Never "sasta" or "budget"** — always "affordable," "premium quality," "premium." Premium positioning.
- **Brand = "Lens Kart"** (two words) in VO — Higgsfield TTS mispronounces "Lenskart" as "Leshkart." The pronunciation problem is ENGLISH words, not Hindi (Hindi renders fine). Phonetically respell / avoid tricky English words ("look" came out wrong).
- **No full product name / spec dump** — short, Gen-Z, fun ("ye black polarized frames", not the full SKU + specs).
- **Always add a relatable, random-but-believable use-case** (harsh sun, bike glare, hide late-night tired eyes, etc.).
- **Keep:** good English usage, strong hook, clear app + virtual try-on CTA.
- **Output:** spoken VO + on-screen visual (SLCT); Hinglish Roman script; 9:16; ~38 words per 15s.

**Process — SCRIPT APPROVAL GATE:** during scripting/iteration, always show the script to the user and get approval BEFORE generating video. (Per-row `Count` = number of videos, `Style` = which UGC style.)

**Why:** premium brand positioning + correct on-screen pronunciation; user vets scripts before spending generation credits.
