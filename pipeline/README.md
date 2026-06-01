# UGC Ads — Bulk Pipeline (Google Sheet driven)

Two-phase, human-in-the-loop pipeline. Claude does product understanding,
scriptwriting, avatar choice, and Higgsfield generation; this `sheet.py` helper
handles all Google Sheet + Drive read/write.

## Sheet columns
`PID Name | Drive Link | Product Detail Page | Claude Script | Manny's Feedback | Status | Count | Style | Avatar | Video Output | Job ID`
- **Count** = videos per PID (blank = 1)
- **Style** = `Product-First` / `Yapping` (more later)
- **Status** = blank → `Approved` / `Hold` → `Done`
- Claude writes: Claude Script, Avatar, Video Output, Job ID

## Flow
**Phase 1 — `run scripts`:** for each row with a Drive Link + empty Claude Script →
download images, read product page, write a script into **Claude Script**.

**You:** review, optionally edit in **Manny's Feedback**, set **Status = Approved / Hold**.

**Phase 2 — `run approved`:** for each row where Status = Approved →
final script = Manny's Feedback if filled else Claude Script → Claude picks avatar →
load product into Higgsfield → generate `Count` video(s) in the chosen `Style` →
write Avatar / Video Output / Job ID back, set Status = Done.

(Phase 2 shows a summary + estimated credits and waits for your go before firing.)

## One-time setup (YOUR part)
1. console.cloud.google.com → project → enable **Google Sheets API** + **Google Drive API**
2. Create a **service account** → **Keys → Add key → JSON** → download
3. Save the key as `../.secrets/service_account.json`
4. Share the **Sheet** with the service-account email → **Editor**
5. Share the **Drive folder** (product images) with that email → **Viewer**
6. Put the **Sheet ID** + **tab name** in `config.json`
   (Sheet ID is the long token in the sheet URL: `/spreadsheets/d/<SHEET_ID>/edit`)

## Verify
```
cd pipeline
python3 sheet.py test          # prints sheet title + headers if auth works
python3 sheet.py rows          # dumps all rows as JSON (with _row numbers)
python3 sheet.py rows --status Approved
python3 sheet.py download --row 2 --dest ../Ads/<pid>
```

## Notes
- Run with the system `python3` (3.9). Libs installed: gspread, google-auth, google-api-python-client.
- Higgsfield generation is NOT in this script — it runs through Claude's MCP tools.
- Keep `.secrets/` private (never zipped/committed/uploaded).
