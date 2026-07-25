# Codex session memory — 2026-07-25

This is the durable handoff for Codex work completed through 2026-07-25. Read it with the
root-level `AGENTS.md`, `CODEX_HANDOFF.md`, and `KT.md`; those remain the authoritative
architecture and historical-decision documents.

## Sources read
- `AGENTS.md`
- `KT.md`
- `CODEX_HANDOFF.md`
- `docs/memory/MEMORY.md`
- `docs/memory/codex-session-memory-2026-07-21.md`
- `docs/memory/github-repos.md`
- `.agents/skills/session-handoff/SKILL.md`
- GitHub publish and browser-control skill instructions

## Decisions locked + what shipped
- The presentation website is now a standalone public repository:
  `https://github.com/manvendrakumar-hub/mannys-ugc-system`.
- `MANNY's UGC SYSTEM/` remains inside the local project folder but is an independent nested
  Git checkout on `main`, with `origin` pointing only to the new public repository.
- The existing production URL remains `https://manny-ugc-systems.vercel.app`.
- Automatic production deployment now lives in the standalone repository at
  `MANNY's UGC SYSTEM/.github/workflows/deploy.yml`; its first run completed successfully.
  Vercel credentials are encrypted GitHub repository secrets.
- The Vercel GitHub App did not have permission to connect the new repository natively.
  GitHub Actions is the active deployment connection and does not expose credentials.
- `perf-ugc-ads` no longer tracks the website files or the obsolete parent-level deployment
  workflow. Commit `122b383` was pushed to both `main` and `agent/ugc-systems-site`.
- The original large source videos remain local and ignored; optimized browser media and the
  PM/TH code snapshots linked by the site are tracked in the public repository.

## Key files for next session
- `MANNY's UGC SYSTEM/README.md` — standalone development and deployment instructions.
- `MANNY's UGC SYSTEM/.github/workflows/deploy.yml` — active production deployment workflow.
- `MANNY's UGC SYSTEM/.gitignore` — excludes original source media and local Vercel metadata.
- `.gitignore` — ignores the nested standalone website checkout from `perf-ugc-ads`.

## Running state
- Background processes: none.
- Dev servers / ports: none.
- Production: `https://manny-ugc-systems.vercel.app` returned HTTP 200 after deployment.

## Verification
- `git -C "MANNY's UGC SYSTEM" status --short --branch` — clean `main...origin/main`.
- `gh repo view manvendrakumar-hub/mannys-ugc-system --json url,visibility` — public repo.
- `gh run view 30154242757 --repo manvendrakumar-hub/mannys-ugc-system` — successful deploy.
- `curl -I https://manny-ugc-systems.vercel.app/` — HTTP 200.
- `git ls-tree -r origin/main -- "MANNY's UGC SYSTEM"` from the parent repo — no entries.

## Deferred + open questions
- Deferred: native Vercel Git integration — the Vercel GitHub App must be granted access to
  `mannys-ugc-system` in GitHub settings; automatic production deployment already works
  through GitHub Actions.
- Open: none.

## Immediate next work
1. Make all future website changes and commits from inside `MANNY's UGC SYSTEM/`.
