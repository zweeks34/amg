> **Approved** 2026-09-29 08:33 · **Roadmap** [The whole roadmap](../ROADMAP.md)
>
> **Built in** `d442c26` chore: initialize repository with spec and ignore rules, `7645cf2` docs: add roadmap and fill in project conventions, `6fbd2b7` build: add pyproject with approved dependencies and pytest config, `02e500e` feat: add SQLite migrations, settings store and single-password auth, `897de0e` feat(web): add app shell, login guard, design system and design reference, `c8edd5f` docs: mark phase 0 complete in roadmap
>
> **As built:** The overall plan: stack, data model and the phases that became the roadmap. Phases 0–3 were built straight from it, without plans of their own; their commits run from `d442c26` to `b0c0f87`, and where the build differed is recorded in each phase's section of the roadmap.
>
> The plan below is as it was approved; it isn't edited afterwards.

# AMG — Build Plan

## Context
`docs/SPEC.md` describes AMG: a self-hosted, web-based manager for several cars. It compares service history (read from scanned receipts or entered by hand) against each car's manufacturer schedule. From that it shows **gaps**, **upcoming** work and a **cost forecast**, and it also tracks fuel and energy. The repo currently holds only `CLAUDE.md`, `docs/SPEC.md` and `.env` (ANTHROPIC / MATHPIX keys). It is **not a git repo yet**.

The user already runs `C:\projects\paint-decoder` on Proxmox (an app container running gunicorn+uvicorn behind an nginx container). AMG deliberately reuses that app's stack, its deploy guide and several of its modules' patterns.

## Decisions (confirmed with user)
| Topic | Decision |
|---|---|
| Stack | Python monolith: FastAPI + Jinja2 + htmx + Alpine.js, no JS build step; **SQLite via stdlib `sqlite3`** (not paint-decoder's JSON files, because AMG's data is linked tables) |
| Baseline schedule | (1) Upload the owner's manual / maintenance-guide PDF → AI extracts the schedule → user verifies; (2) fallback: AI draft from year/make/model (VIN decoded with the free NHTSA vPIC service), marked *unverified* until confirmed; generic templates to start from |
| Receipts | Free local step first (PyMuPDF text layer → Tesseract OCR), then Claude turns the text into structured line items; Claude reads the image itself when OCR is poor; **every receipt is confirmed by the user** before it counts |
| UI | "Service Interval Chart" direction, built with the `frontend-design` skill |
| Alerts | Dashboard badges + weekly email digest + ntfy push + .ics calendar feed |
| Vehicles | Gasoline, hybrid, EV (so fuel is gallons/MPG *or* kWh/mi-per-kWh) |
| Fuel entry | Quick phone form at the pump or charger (no receipt reading, no import) |
| Auth | Single password (stdlib `hashlib.scrypt`) + long-lived HMAC-signed session cookie |
| Units (assumed) | US: miles, gallons, USD; kWh for EVs |
| Claude model | One setting, `AMG_CLAUDE_MODEL`, default `claude-opus-5-5` (≈5¢ per receipt page; Sonnet 5.5 ≈2¢ and Haiku 4.5 ≈1¢ if the user switches). Structured outputs (`output_config.format` / `messages.parse`); server-side refusal fallbacks on. Read the `claude-api` skill's Python docs before writing the client |
| Roadmap | `docs/ROADMAP.md` in the repo: the phases below as checklists with "done when…" criteria, kept current as phases ship. `docs/DEPLOY-proxmox.md` gets written in Phase 3 |

## Dependencies (approving this plan approves this list; per CLAUDE.md)
Runtime: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `anthropic`, `python-dotenv`, `pymupdf`, `pytesseract`, `pillow`. Deploy: `gunicorn`. Dev: `pytest`, `httpx` (for FastAPI's TestClient).
Vendored static files, with no CDN at runtime: `htmx.min.js`, `alpine.min.js`, and OFL-licensed woff2 fonts.
Everything else is stdlib: `sqlite3`, `hashlib`, `hmac`, `smtplib`, `csv`, `zipfile`, `urllib`, `statistics`. Charts are SVG generated on the server, so there is no chart library.
Target Python ≥3.12 (the LXC runs Ubuntu 24.04's 3.12; local is 3.14).

## Layout (`src/` app, `tests/` mirrors it)
```
src/amg/
  app.py config.py db.py auth.py cli.py
  migrations/0001_init.sql …        # numbered SQL, applied by db.py at startup
  repo/      vehicles services schedules fuel documents settings
  ingest/    files (sha256 store+dedupe) pdf (PyMuPDF) ocr (Tesseract) claude (client+schemas)
             receipts (pipeline) manuals (schedule extraction) vin (NHTSA vPIC) jobs (background work)
  engine/    odometer schedule(gaps) forecast        # pure functions, heavily tested
  alerts/    run (daily) ntfy email ics
  reports/   queries csv packet
  web/       routes_*.py  templates/  static/{app.css,fonts/,vendor/}
tests/amg/…  scripts/eval_receipts.py   data/ (gitignored: amg.sqlite3, files/)   samples/ (gitignored real scans)
```

## Reuse from paint-decoder (patterns and code to port, not imports)
- `webapp/pdf_pages.py`: renders pages to a target long edge rather than a fixed DPI; chooses JPEG vs PNG per page.
- `webapp/local_analyzer.py`: `_configure_tesseract()` / `tesseract_available()`, which find the binary on PATH or in `C:\Program Files\Tesseract-OCR\`. Locally it is installed there but not on PATH.
- `webapp/analysis_jobs.py`: background work started by a request that outlives it, with stalled-job detection and "carry on". AMG keeps the job state in a `jobs` table instead of JSON files.
- `webapp/backup.py`: the "download your data" zip.
- `paintdecoder-proxmox-deploy.md`: the container setup, systemd unit, nginx timeouts and `client_max_body_size`, and the Tesseract install. It gets simpler because the whole `data/` directory is excluded from rsync.
- `paintdecoder-roadmap.md`: the spec style for ROADMAP.md (what each item is for, the data it owns, what can go wrong, what tests must pin down).

## Core design

**Data (SQLite, WAL mode).**
- `vehicles`: VIN, year/make/model/trim, powertrain gas|hybrid|ev, acquired date and odometer, in-service date.
- `odometer_readings`: from receipts, fill-ups and manual entries.
- `documents`: original files by sha256, plus page images.
- `service_events`: date, odometer, shop, total, source receipt|diy|attested, confirmed.
- `line_items`: description, parts/labor, qty, price.
- `line_item_services`: a line item ↔ service types, many-to-many (e.g. "oil & filter" → engine_oil + oil_filter).
- `service_types`: a seeded standard list, including hybrid- and EV-specific items.
- `service_aliases`: learned text → service type, so repeat shops map without calling Claude.
- `schedules` and `schedule_items`: service type, action, `interval_miles`, `interval_months`, `first_at_miles`, severe-service flag, source manual-page|ai_draft|template|user, verified.
- `fuel_logs`: odometer, quantity + unit gal|kWh, total cost, full-fill flag, home|public for charging.
- `price_book`, `jobs`, `alert_log`, `settings`.

**Receipt pipeline.**
1. Upload one or more files, or take a photo with the phone camera (`capture="environment"`); files with the same sha256 are deduplicated.
2. Get text: PyMuPDF text layer first → Tesseract.
3. Claude, with a strict JSON schema, returns shop, date, odometer, VIN/plate, line items, tax and total, plus suggested service types.
4. If OCR confidence is low, send the page image instead.
5. Review screen: scan on the left, fields on the right. Values the AI read are shown in an "imprint" style until confirmed.
6. On confirm, create the service event, record an odometer reading and learn aliases.
7. The backlog runs as background jobs; the Message Batches API at half price is an option for the bulk import.

**Schedule extraction.**
- Locate the schedule pages locally with PyMuPDF keyword and density search ("maintenance schedule", "every … miles/months", "replace", "inspect"), then send only those pages to Claude.
- Scanned manuals without text: OCR in a background job, or send the PDF directly if it is within the page limit.
- The user verifies the result item by item.
- AI draft path: the VIN is decoded, then Claude drafts a schedule from its knowledge; every item stays `verified=0`.

**Gap engine (`engine/`, pure and deterministic).**
- *Odometer model*: piecewise-linear interpolation between known readings; the future is projected from the recent miles-per-day rate.
- For each schedule item, walk its expected occurrences starting from the in-service or acquisition point (no gaps are flagged before the user owned the car).
- An occurrence is due at the earlier of miles or months (whichever comes first), and it counts as met by a matching service within a tolerance.
- Results: done / gap / overdue / due soon (thresholds configurable) / upcoming.
- The user can attest to a gap ("done, no receipt"), which creates an `attested` event.

**Forecast.**
- Place each upcoming occurrence within the horizon (12 months by default) on a date using the odometer projection.
- Estimate its cost from, in order:
  1. The median of the user's confirmed costs for that service type on this car, then on other cars, adjusted by an inflation setting.
  2. The editable price book.
  3. An AI estimate range, flagged and cached.
- Fuel and energy spend is projected from miles per day × cost per mile.
- Output is a month-by-month budget.

**Alerts.**
- A systemd timer runs `python -m amg.alerts.run` daily and records each alert in `alert_log` so the same alert is never sent twice.
- ntfy sends a push when an item changes state (due soon or overdue). ntfy and email only need outbound access, so they work without the VPN.
- A weekly email digest goes out via `smtplib` (Gmail app password in `.env`).
- `/calendar/<random-token>.ics` serves a calendar feed; it uses a token because calendar apps can't log in.

**Reports.**
- On-demand filters: vehicle, date range, service type or category, shop.
- Output as an HTML page with print styles, or a CSV download.
- Presets: full history, spend by year and category, fuel-economy trend, and a "sale packet" PDF (history plus every receipt, merged with PyMuPDF).

**UI (frontend-design; tokens to be refined in the Phase 0 design pass).**
- Palette: shop-floor gray, navy ink, safety yellow (due soon), signal red (gap), service green (done), steel.
- Fonts: Barlow Condensed for display, Public Sans for body text, IBM Plex Mono for mileage and money.
- *Signature*: the interval chart (service items × mileage, ● done → links to the receipt, ✕ gap, ◐ due soon). On phones it collapses to a "Next up" list, with the chart one tap away and scrollable sideways with a sticky item column.
- Minimum quality bar: works at phone widths, visible keyboard focus, `prefers-reduced-motion` respected.

## Phases (these become `docs/ROADMAP.md`)
0. **Foundation.** Create `.gitignore` *first* (`.env`, `data/`, `samples/`, caches), then `git init`. Add requirements, the app skeleton, SQLite + migrations, login, `cli.py set-password`, and the design system (tokens, fonts, base layout). Fill in CLAUDE.md's Stack, Commands, Layout and Gotchas. *Done when:* login works, the empty garage page renders in the chosen style at 375px and at desktop width, and pytest passes.
1. **Garage + manual records + extraction trial.** Vehicle add/edit/delete (with VIN decode), odometer readings, entry of DIY or hand-typed services, the service-type list, and a history view. Also `scripts/try_receipt.py`, run on about 10 real scans in `samples/` to check extraction quality before building the UI around it. *Done when:* two cars exist with hand-entered history, and the trial output looks usable.
2. **Receipt ingestion.** The full pipeline, the review/confirm screen, alias learning, background jobs, and bulk multi-file upload. `scripts/eval_receipts.py` reports per-field accuracy against hand-labelled samples (run by hand, costs pennies). *Done when:* the backlog imports and each receipt takes one review pass.
3. **Deploy to Proxmox.** Write `docs/DEPLOY-proxmox.md`: a new app container (2 GB RAM for OCR) plus an `amg` server block on the existing nginx container, systemd unit, rsync that excludes `data/`, and a backup/restore procedure. From here on, real data lives on the server. *Done when:* the app is reachable from the phone over NordVPN.
4. **Baseline schedules.** Templates (gas, hybrid, EV), owner's-manual PDF extraction and review, the AI-draft path, and editing. *Done when:* every car has a verified schedule.
5. **Gap engine + Interval Chart + dashboard.** The odometer model, gaps, due-soon badges, "next up", and gap attestation. *Done when:* engine tests cover whichever-comes-first, `first_at` offsets, the acquisition cutoff, tolerance, and no readings at all; the chart matches a hand-checked car.
6. **Fuel and energy log.** The pump/charger form, MPG or mi/kWh between full fills, and cost per mile; fill-ups also feed the odometer model.
7. **Forecast and budget.** Cost estimates in the order above, the price book, and the monthly budget view.
8. **Outbound alerts.** ntfy, the weekly email, the .ics feed, and the systemd timer (`--dry-run` flag).
9. **Reports and exports.** The report builder, CSV, print styles, the sale-packet PDF, and the backup zip.

Each phase ends with small conventional commits and a short check-in before the next phase starts (CLAUDE.md workflow).

## Verification
- `pytest`: the engine modules are unit-tested with fixed data. Claude calls are mocked, and routes are tested through FastAPI's TestClient against a temporary SQLite database.
- Extraction quality: `scripts/eval_receipts.py` on real samples (opt-in, costs money).
- End to end, locally with `uvicorn amg.app:app --reload`: log in, add a car by VIN, upload receipts and confirm them, upload a manual and verify the schedule. Then check that the chart shows the expected gaps, log fill-ups and check MPG, check the forecast totals, run `python -m amg.alerts.run --dry-run`, and export a CSV and the sale packet.
- UI: screenshots in Chrome at 375, 768 and 1280px widths in the frontend-design review loop.
- Deploy: the smoke-test checklist in `docs/DEPLOY-proxmox.md` (curl through nginx, a large-PDF upload, Tesseract and PyMuPDF availability).

## First actions after approval
1. `.gitignore` → `git init` → first commit of the existing docs (`.env` must never be committed).
2. Write `docs/ROADMAP.md` from this plan.
3. Update CLAUDE.md (Stack, Commands, Layout, Gotchas: Tesseract not on PATH on Windows, Python 3.12 target).
4. Start Phase 0.
