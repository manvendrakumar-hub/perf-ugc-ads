---
name: github-repos
description: GitHub repos for the UGC ads project (private continuity + public template) and gh CLI setup
metadata: 
  node_type: memory
  type: reference
  originSessionId: ba3f6ae6-9dfa-4f1c-bba7-bf8ebabe9f10
---

Pushed 2026-06-02. GitHub account **manvendrakumar-hub** (gh authed, repo scope). Relates to [[ugc-bot-automation]].

- **PRIVATE (continuity / new-machine):** https://github.com/manvendrakumar-hub/perf-ugc-ads — full real values: KNOWLEDGE_BASE.md (all IDs/recipe), both skills as `.skill` zips, pipeline/ with real config, Avatars/ PNGs, product images, fonts. `.secrets/` gitignored (no keys/tokens committed). Clone this on the new machine, then re-auth per KNOWLEDGE_BASE.md / RUNBOOK.
- **PUBLIC (generic template):** https://github.com/manvendrakumar-hub/ugc-ads-automation-template — fully scrubbed (verified zero IDs/keys/emails/brand/assets). Generic skills + pipeline (gauth.py, sheet.py, placeholder config) + README/RUNBOOK with architecture & gotchas. MIT.

**Tooling:** `gh` CLI installed (no admin) at `~/.local/gh_2.93.0_macOS_arm64/bin/gh` (no symlink — use full path; clear quarantine if blocked). Local project at `Perf UGC Ads/` is the private repo (origin = perf-ugc-ads). Public template lives in a sibling dir `VS Code Projects/ugc-ads-automation-template/`.

**Rule:** never commit `.secrets/`. When adding a new video Style, update the private skill AND push a genericized version to the public template. `Ads/<PID>/` empty subdirs aren't tracked (mp4 gitignored) — add .gitkeep if structure-in-repo matters.
