# Perf UGC Ads — Master Knowledge Base

**Purpose:** paste/clone this repo into a fresh Claude Code session (or a new machine) and use this one file to get the whole system back in line. It links the two skills, the creative rules, the automation pipeline, the auth, the IDs, and the migration checklist.

> Owner: manvendra.kumar@lenskart.com (Lenskart, product design). Built with Claude Code. Last validated end-to-end: **2026-06-02** on PID 131309.

---

## 0. What this project is
An AI pipeline to mass-produce **UGC-style ads** for Lenskart products. A Google Sheet drives it: each row is a product (PID). Claude writes the script, generates the video on Higgsfield with a registered influencer avatar, you post-produce, and the final lands in Drive + the sheet.

Two "brains," kept deliberately separate:
| Brain | Claude skill | Owns |
|---|---|---|
| **Creative** | `ugc-ads` | ad types, scripts, brand voice, avatars, generation params |
| **Automation/ops** | `ugc-bot-automation` | Sheet ↔ Drive ↔ Higgsfield plumbing, OAuth, folders |

---

## 1. Resume in a new Claude session (do this first)
1. Clone the repo; open it in Claude Code.
2. **Install the skills** into `~/.claude/skills/`: unzip the packages in `Claude skills /` (`ugc-ads.skill`, `ugc-bot-automation.skill`) — each is a zip of its `.md` files → put them in `~/.claude/skills/<name>/`. (The `seedance2-director` / `video-prompt-builder` skills are optional extras.)
3. Read this file + the skill `SKILL.md` / `RUNBOOK.md`.
4. Re-do auth (Section 5) — secrets are NOT in the repo.
5. Recreate Claude memory if desired (Section 7 lists what was stored).

---

## 2. Creative system (skill: `ugc-ads`)
Two ad types, each its own `.md`:
- **Product-First** (`product-first-ugc.md`) — 100% about the product. Model: **Higgsfield Marketing Studio** (Avatar + Product).
- **Yapping** (`yapping-ugc.md`) — creator rambles, then pivots to product. Model: **Seedance 2.0**.

**Output:** numbered ≤15s segments, each = SPOKEN (VO) + ON-SCREEN VISUAL (SLCT: Subject→Lighting→Camera→Technical). Default 15s = 1 segment; 30/60s = segment-and-stitch (~38 words per 15s or Higgsfield speeds up speech).

**🔒 Locked brand-voice rules (Lenskart, Hinglish):**
- Hinglish in **Roman script**. Hindi pronounces fine; **English words are the risk**.
- Brand = **"Lens Kart"** (two words) — "Lenskart" mis-speaks as "Leshkart". Respell/avoid tricky English words.
- **Never "sasta"/"budget"** → "affordable", "premium quality", "premium".
- **No full product name / spec dump** → short, Gen-Z, fun.
- **Always add a relatable use-case** (sun, bike glare, late-night tired eyes…).
- Keep: good English, strong hook, **app + virtual try-on CTA**.
- **SCRIPT APPROVAL GATE:** always show the script and get approval **before** generating.

**Validated example (PID 131309, Count 2):**
- female_2: *"Okay ye black polarized frames ne meri vibe hi set kar di! Dhoop ho ya late-night ki thaki aankhein, sab chhupa leti hai. Premium bhi, affordable bhi. Lens Kart app pe try-on karo, abhi!"*
- male_1: *"Bro inn black polarized frames ne game palat diya! Tez dhoop ho ya bike ki glare, sab gone. Premium quality, aur itni affordable! Lens Kart app kholo, try-on karo, trust me."*

---

## 3. Avatars (6 registered Indian-influencer, early-20s)
Source PNGs in `Avatars/` (female_1-3, male_1-3), generated with Nano Banana Pro. Registered as Higgsfield Marketing Studio custom avatars:
| Name | Avatar ID |
|---|---|
| female_1 | f3240553-ccb5-4f0d-a9c7-09434db65335 |
| female_2 | 9cbbdaca-fb05-485e-8327-6fe15e3983f0 |
| female_3 | fe6ac18e-440f-4646-91ee-c698166c5fae |
| male_1 | dcc53948-3575-4699-8064-d974f848b99d |
| male_2 | bc7e2c96-effc-4aef-939b-0da10ea9cd0e |
| male_3 | a1cef9fd-9af7-4307-8a05-db25d4a4e957 |
(Avatar IDs are per-Higgsfield-account; re-register from `Avatars/` if the account changes.)

---

## 4. Higgsfield generation recipe (Marketing Studio, Product-First)
`generate_video` with `model:"marketing_studio_video"`, `prompt:<brief + EXACT VO line>`, `product_ids:["<id>"]`, `avatars:[{"id":"<id>","type":"custom"}]`, `aspect_ratio:"9:16"`, `generate_audio:true`.
- **Gotchas:** `get_cost:true` preflight FALSELY reports product_ids/avatars as unsupported — ignore; the real call binds them. `avatars` must be objects, not strings. `mode`/preset NOT settable via API (defaults to `ugc`). All Higgsfield video models cap at 15s. ~75 credits / 15s video.
- Product setup: Lenskart URL auto-scrape FAILS (403). Download images (browser UA+Referer, or the Drive input folder) → `media_upload`→`media_confirm`→`show_marketing_studio create type=product`.

---

## 5. Automation pipeline (skill: `ugc-bot-automation`)
**Architecture (who does what):**
- **Reads** → Google Drive MCP connector `claude.ai Google Drive (2)` (as user). search_files / read_file_content (sheet→markdown) / download_file_content / create_file (folders).
- **Writes** → OAuth as user via `pipeline/gauth.py` (Drive + Sheets API). `login` / `upload --folder --files` / `setcells --sheet --row --kv "Col=Val"`.
- **Generation** → Higgsfield MCP. **Glue** → shell.

**Sheet "Ugc-bot-automation"** id `1jTywBQAUY4oI8LsccJPOJufLda47zS0wqpgCA38gIHE`, tab `Sheet1`.
Cols: `PID Name | Drive Link | Product Detail Page | Claude Script | Manny's Feedback | Status | Count | Style | Avatar | Video Output | Job ID`. Status blank→Approved/Hold→Done. Count blank=1. Style=Product-First/Yapping.

**Flow:** `run scripts` (read row → product page → write Claude Script → STOP at approval gate) → user approves → `run approved` (final script = Manny's Feedback else Claude Script → avatar → Higgsfield → download to `Ads/<PID>/raw_higgsfield/` → user post-produces into `Ads/<PID>/final/` → upload to Drive subfolder → write sheet). Always show credit summary before generating.

**Drive output parent folder:** `1L_CIGT9y_RSb4Y4TbuB-x5wC_-uahvUH` → one subfolder per PID.

**Folder structure:**
```
Ads/<PID>_<slug>/raw_higgsfield/   (bot raw outputs)
Ads/<PID>_<slug>/final/            (your post-produced finals → uploaded)
pipeline/  gauth.py  sheet.py(parked)  config.json  README.md
.secrets/  (NEVER committed)  oauth_client.json  token.json  service_account.json(parked)
.mcp.json  (Playwright; machine-specific node PATH)
```

---

## 6. Auth setup (re-do on a new machine — secrets are NOT in repo)
**GCP project:** "UGC-Automation", number `130084846397`, id `spring-market-498112-f8`. Enable **Google Drive API** + **Google Sheets API** (each, allow ~2 min propagation).
1. **Drive connector:** `/mcp` → `claude.ai Google Drive (2)` → sign in as Lenskart. (Reads.)
2. **OAuth Desktop client** (writes): APIs & Services → Credentials → OAuth client ID → Desktop → download → save as `.secrets/oauth_client.json`. Then `cd pipeline && python3 -u gauth.py login` (background; it prints `AUTHURL>>> <url>` — open in Lenskart browser, approve "unverified app" → token caches to `.secrets/token.json`).
3. **Higgsfield MCP:** `/mcp` → connect `claude.ai Higgsfield`.
4. **Playwright MCP** (optional; for fetch-blocked pages — NOT for Google): install Node, add to project `.mcp.json`, fix `env.PATH` to the new node bin. (`code --add-mcp` targets VS Code/Copilot, not Claude Code — use `.mcp.json`.)
5. Python deps: `pip3 install --user gspread google-auth google-auth-httplib2 google-auth-oauthlib google-api-python-client`.

---

## 7. Hard-won gotchas
- **Service account is BLOCKED** (Lenskart forbids sharing with external accounts). `pipeline/sheet.py` is parked; only revive if IT allowlists `ugc-bot@spring-market-498112-f8.iam.gserviceaccount.com`.
- **Connector can't upload large files** (base64 = millions of tokens) or **edit cells** → writes go through `gauth.py` (OAuth).
- **Playwright can't log into Google** (automation-browser block) → not the Drive/Sheets path.
- Enable **both** Drive + Sheets APIs in the project; wait for propagation.
- Lenskart product images **403 server fetchers** → browser UA+Referer or the Drive input folder.
- `gauth.py login` stdout is block-buffered → run with `python3 -u` in the background to capture the AUTHURL.

---

## 8. Current status & next steps
- ✅ PID **131309** (Vincent Chase VC S11740-C1 sunglasses) done end-to-end: 2 videos (female_2, male_1), uploaded to Drive, sheet row 2 = Done.
- ⏭ Next: user to provide the **next video-type/style knowledge set** (extend `Style` + add a new `*-ugc.md` to the `ugc-ads` skill). Then run more PIDs through `run scripts` → approve → `run approved`.

## Claude memory snapshot (project memory files, recreate if useful)
`ugc-ads-system`, `ugc-script-voice-rules`, `higgsfield-avatars`, `higgsfield-ms-generation-recipe` (creative) · `ugc-bot-automation` (ops). Index in `memory/MEMORY.md`.
