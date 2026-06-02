---
name: ugc-bot-automation
description: "State, working setup, and gotchas for the Google-Sheet-driven bulk UGC ad pipeline (ops/automation layer)"
metadata: 
  node_type: memory
  type: project
  originSessionId: ba3f6ae6-9dfa-4f1c-bba7-bf8ebabe9f10
---

Ops/automation layer for the bulk UGC pipeline. Skill: `ugc-bot-automation` (SKILL.md + RUNBOOK.md). Creative side is separate: [[ugc-ads-system]], [[ugc-script-voice-rules]], [[higgsfield-avatars]], [[higgsfield-ms-generation-recipe]]. Validated end-to-end on PID 131309 (2026-06-01).

**What works (the architecture):**
- **Reads** → Google Drive MCP connector `claude.ai Google Drive (2)` (authed as user manvendra.kumar@lenskart.com — compliant). Tools: search_files, read_file_content (sheet → markdown table), download_file_content, create_file (Drive folders).
- **Writes** → OAuth-as-user via `pipeline/gauth.py` (Desktop OAuth client `.secrets/oauth_client.json`, token `.secrets/token.json`, scopes drive+spreadsheets). Commands: login / upload --folder --files / setcells --sheet --row --kv "Col=Val". THE working write path.
- **Generation** → Higgsfield MCP (see [[higgsfield-ms-generation-recipe]]).
- **Glue** → shell (curl downloads, folder restructure).

**Sheet** "Ugc-bot-automation" id `1jTywBQAUY4oI8LsccJPOJufLda47zS0wqpgCA38gIHE`, tab Sheet1. **ONE ROW PER PID** (the row is the PID hub; Video Output = the PID's Drive folder; descriptive cols list all formats made). Cols (A→O): PID Name | Drive Link(input from teams) | Product Detail Page | Claude Script(bot) | Manny's Feedback(script-level) | Status(has a data-validation dropdown incl. Review; blank→Approved/Hold→Done) | Count(blank=1) | Style(Product-First/Yapping) | Avatar(bot, A.1) | Video Output(bot, Drive link) | Job ID(bot) | Sub-Format(A.1/A.2-2split/A.2-3split/A.3) | Model(A.2/A.3 fashion model) | Engine(Marketing Studio/Seedance 2.0) | Manny's Edit Feedback(per-edit change notes). Drive `_Models/` folder holds the reusable model library. Drive output parent folder `1L_CIGT9y_RSb4Y4TbuB-x5wC_-uahvUH` → one subfolder per PID. Local: `Ads/<PID>_<slug>/{raw_higgsfield,final}/`.

**Flow:** Phase 1 `run scripts` (read row → product page → write Claude Script → STOP at approval gate). User approves in sheet. Phase 2 `run approved` (final script = Manny's Feedback else Claude Script → pick avatar → Higgsfield → download raw → user post-produces into final/ → upload to Drive subfolder → write sheet, Status=Done). Show credit summary before generating (~75 cr / 15s MS video).

**GCP project:** "UGC-Automation", number 130084846397, id spring-market-498112-f8. Drive API + Sheets API both enabled (needed to enable each + ~couple min propagation).

**Gotchas / what we faced:**
- Service account (`ugc-bot@spring-market-498112-f8.iam.gserviceaccount.com`) BLOCKED by Lenskart Workspace policy (no external-account sharing). `pipeline/sheet.py` (SA-based) is PARKED; only revive if IT allowlists the SA.
- Connector can't upload large files (base64 → millions of tokens) and can't edit cells → that's why writes go through gauth.py OAuth.
- Playwright can NOT act as user on Google (Google blocks automated-browser logins; only headless-shell installed). Not the write path. `.mcp.json` adds Playwright to Claude Code (Node at ~/.local/node; `code --add-mcp` wrongly targets VS Code/Copilot, not Claude Code).
- gauth.py login: run `python3 -u` in background to capture the `AUTHURL>>>` it prints (stdout block-buffered).
- Lenskart product images 403 server fetchers; use browser UA+Referer or the Drive input folder.

**Migration (new high-spec machine in ~2 weeks + GitHub repos):** see RUNBOOK.md "New-machine setup". Key: `.secrets/` never committed; re-mint token via gauth.py login; re-enable APIs; re-connect MCP connectors; fix node PATH in `.mcp.json`. Folder structure is intentionally GitHub-ready.
