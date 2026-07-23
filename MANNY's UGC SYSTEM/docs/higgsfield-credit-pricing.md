---
name: higgsfield-credit-pricing
description: Confirmed Higgsfield credit costs per generation — verified from Higgsfield website 2026-06-30
metadata:
  type: reference
---

Confirmed credit costs directly from Higgsfield website (2026-06-30). Use these, not estimates.

**Why:** Prior session used guesses for several values (gpt_image_2, 480p/fast, Kling 3.0) that were wrong by 2–4×. Always verify unknown models with `get_cost:true` preflight.

**How to apply:** Use these numbers for spend planning, guardrail calibration, and cost-per-ad estimates.

## Confirmed credits per generation

| Step | Engine | Settings | Credits |
|---|---|---|---|
| Try-on still | gpt_image_2 | 2k / high | **7 cr** |
| A.1 Talking Head | Higgsfield MS | ugc_unboxing preset / 15s | **75 cr** |
| A.2 Split Screen | Seedance 2.0 | 720p / std / 15s | **68 cr** |
| A.2 Layout test | Seedance 2.0 | 480p / fast / 15s | **45 cr** |
| A.3 Product Modelling | Seedance 2.0 | 1080p / std / 15s | **135 cr** |
| A.3 Product Modelling | Kling 3.0 | pro / 15s | **30 cr** |

## Key implications

- **Kling 3.0 is 4.5× cheaper than Seedance 1080p** (30 cr vs 135 cr). For A.3, test Kling first — only escalate to Seedance if Kling quality is insufficient.
- **gpt_image_2 try-on still is nearly free** (7 cr). Always generate it — the IMAGE-FIRST gate costs almost nothing.
- **480p/fast layout tests save only 23 cr vs 720p/std** (45 cr vs 68 cr). Still worth using for pure panel-layout validation, but not the dramatic saving we assumed.
- **NSFW / ip_detected are uncharged** — confirmed for Seedance video generation. Retry freely.

## Cost per full ad unit

| Ad type | Steps | Total credits | ~$ (at $0.04/cr) |
|---|---|---|---|
| A.1 Talking Head | 1 MS gen | 75 cr | ~$3.00 |
| A.2 Split Screen × 2 takes | 2 × 68 cr | 136 cr | ~$5.44 |
| A.3 Seedance × 2 takes | 7 (still) + 270 (video) | 277 cr | ~$11.08 |
| A.3 Kling × 2 takes | 7 (still) + 60 (video) | 67 cr | ~$2.68 |

## Unknown — verify with get_cost:true before running

- Kling 3.0 at resolutions other than default
- Seedance at 4K or above
- Any new model added to Higgsfield after 2026-06-30
