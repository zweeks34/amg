# AMG — Roadmap

The build plan for the Automobile Maintenance Genie, in the order it gets built.
[SPEC.md](SPEC.md) says *what* AMG is for; this file says *how it gets there* and
what "done" means for each step. Tick items off as they ship, and when a phase
teaches us something that changes a later one, edit the later one here rather
than carrying the correction around in our heads.

Each phase says what it is for, the data it owns, what can go wrong, and what
a test has to pin. Each ends with small conventional commits and a check-in
before the next begins.

---

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Stack | FastAPI + Jinja2 + htmx + Alpine.js, no JS build step | Same stack and deploy path as paint-decoder, which already runs on the home lab |
| Storage | SQLite through stdlib `sqlite3`, WAL mode, numbered SQL migrations | AMG's data is relational (vehicle → service → line item ↔ schedule item) and reports are queries. One file to back up. No multi-worker stale-file problem |
| Baseline schedule | Owner's-manual PDF → AI extraction → you verify. Fallback: AI draft from year/make/model (VIN decoded by NHTSA vPIC), *unverified* until confirmed. Templates to start from | The manual is the authority; the draft covers cars whose manual you don't have |
| Receipts | Local first (PDF text layer → Tesseract), then Claude structures the text into line items, reading the image itself when OCR is poor. **Every receipt is confirmed before it counts** | Free where it can be, accurate where it matters, and never silently wrong |
| Claude model | `AMG_CLAUDE_MODEL`, default `claude-opus-5-5` | ≈5¢/receipt page. Sonnet 5.5 (≈2¢) or Haiku 4.5 (≈1¢) is a one-line change |
| Vehicles | Gasoline, hybrid, EV | EVs log kWh and mi/kWh instead of gallons and MPG |
| Units | Miles, US gallons, USD, kWh | |
| Fuel entry | Quick phone form at the pump or charger | |
| Alerts | Dashboard badges, weekly email digest, ntfy push, `.ics` calendar feed | Email and ntfy only need outbound access, so they reach you off the VPN |
| Auth | One password (stdlib `hashlib.scrypt`), long-lived HMAC-signed session cookie | Keeps guests on the LAN out; you rarely see the login screen |
| UI | "Service Interval Chart" direction via the frontend-design skill | The app's core question — what did I miss? — *is* the chart |
| Hosting | New app LXC on Proxmox, new server block on the existing nginx LXC, reached over NordVPN | Mirrors paint-decoder's deployment |

**Dependencies** (approved with the plan): `fastapi`, `uvicorn[standard]`,
`jinja2`, `python-multipart`, `anthropic`, `python-dotenv`, `pymupdf`,
`pytesseract`, `pillow`; `gunicorn` on the server; `pytest`, `httpx` for tests.
htmx, Alpine.js and the fonts are vendored into `static/` — no CDN at runtime.
Everything else is the standard library. Adding anything beyond this list
needs asking first (CLAUDE.md).

---

## Phase 0 — Foundation

**For:** a running, logged-in, styled empty app that every later phase plugs
into.

- [x] `.gitignore` before `git init` (`.env`, `data/`, `samples/`)
- [x] `pyproject.toml` (dependencies live only there; `[dev]` and `[server]` extras); `src/` layout
- [x] `amg.config` — settings from `.env` (paths resolved per call so tests can redirect them)
- [x] `amg.db` — connection factory (WAL, foreign keys on), migration runner over `migrations/NNNN_*.sql`, a `schema_version` table
- [x] `0001_init.sql` — `settings` table (the rest arrive with the phases that own them)
- [x] `amg.auth` — scrypt password hash in `settings`, HMAC-signed session cookie, login/logout routes, a middleware guard on every page
- [x] `python -m amg.cli set-password`
- [x] Design system: tokens (colour, type scale, spacing, light + dark), self-hosted fonts, base layout, nav, empty garage page, login page, and `/design` — a reference page with the interval chart drawn from hand-written sample data
- [x] CLAUDE.md: Stack, Commands, Layout, Gotchas filled in

**Data owned:** `settings`, `schema_version`.

**Can go wrong:** two workers start at once → migrations run under one
`BEGIN IMMEDIATE`, so the second waits and finds nothing to do. A migration
fails halfway → the whole run rolls back. The session secret is generated on
first use and stored in `settings`, so there is no secret to forget to set on
the server; setting a new password signs every session out.

**Tests pin:** migrations apply in order to an empty database and are
idempotent on a second run; a wrong password is rejected; a forged or expired
cookie is rejected; every page but `/login` redirects when logged out.

**Done when:** login works, the empty garage renders in the chosen style at
375px and desktop width, `pytest` passes.

---

## Phase 1 — Garage, manual records, extraction trial

**For:** getting your cars and some history in by hand, and finding out early
whether receipt extraction is good enough to build a UI around.

- [x] Vehicles: add / edit / archive; VIN decode via NHTSA vPIC fills year/make/model/trim/powertrain
- [x] Odometer readings: manual entry; every reading keeps its source (the `odometer_points` view unions typed readings, services and the acquired mileage); a reading that runs backwards is refused
- [x] Service-type catalogue seeded (oil, filters, rotation, fluids, plugs, brakes, 12V battery, hybrid inverter coolant, EV battery coolant, …) with categories — 45 types, plus your own from `/service-types`
- [x] Service entry by hand (DIY or a receipt typed in): date, odometer, shop, line items, each line mapped to service types with an action (replace / inspect / perform)
- [x] Service history per vehicle
- [x] `scripts/try_receipt.py <file>` — local text/OCR → Claude → JSON printed, in `text`, `vision` or `both` mode. Run on all 14 scans in `samples/` (findings below)

**Data owned:** `vehicles`, `odometer_readings`, `service_types`,
`service_events`, `line_items`, `line_item_services`.

**Can go wrong:** vPIC is down or doesn't know the VIN → manual entry always
works. A car bought used has no history before purchase → store the acquired
date and odometer so later phases don't call that a gap.

**Tests pin:** VIN validation (check digit); a line item mapping to two service
types; deleting a vehicle is an archive, not a cascade.

**Done when:** two cars exist with hand-entered history, and the trial output
on real scans looks usable.

### Trial findings (2026-09-30)

All 14 receipts in `samples/` (2016–2024, five shops, one car, three of them
handwritten or phone-scanned) were read both ways with `claude-opus-5-5` at
medium effort; two were checked line by line against the paper. Two of the
receipts print a 2016 Forester's VIN and description: the shop's mistake —
the work was on the Outback.

| | Text (the PDF's own text layer, else Tesseract) | Vision (page images) |
|---|---|---|
| Date right | 11 / 14 | 14 / 14 |
| Total right | 11 / 14 | 14 / 14 |
| Odometer, where printed | 10 / 12 | 12 / 12 |
| Line amounts right | 7 / 14 | 12 / 14 — one flagged for review, one estimate's items filed as recommendations |
| Cost per receipt | 4.0¢ | 5.6¢ |
| Time per receipt | ~15 s | ~13 s |

- **The scanner's own text layer is the problem.** Epson Scan's searchable-PDF
  layer is present on 12 of the 14 receipts, and is often garbled — letters
  swapped, columns interleaved, one invoice's layer holds only its header —
  with no confidence score to tell good from bad. Text mode failed outright on
  the handwritten receipts and on that header-only page.
- **Vision read everything,** including two handwritten receipts (it took the
  $20 line as Virginia's state inspection, which is right), a warranty battery
  at $0, and six declined items on a tire invoice, kept apart as
  recommendations.
- **It caught a document type nobody planned for:** one scan is stamped "not an
  invoice — an estimate showing a deposit", yet shows full payment and the work
  done the same day.

**Decision for phase 2:** every receipt is read with vision. Local text
extraction stays, but only to make receipts searchable; it no longer decides
anything. The extra cost is about 1.6¢ a receipt.

---

## Phase 2 — Receipt ingestion

**For:** getting the backlog of scanned receipts in with one review pass each.

- [x] Upload: several files at once, PDF/PNG/JPG/GIF, phone camera capture, or several photos combined into one receipt; stored by sha256 so a re-upload is recognised; phone JPEGs turned upright from their EXIF rotation
- [x] ~~Text for search~~ — dropped. The scanner's text layer can't be trusted, and what Claude read is already stored with every receipt; searching it moves to phase 9
- [x] Claude reads every page as an image (`receipts.read_receipt(..., mode="vision")`): shop, date, odometer, VIN, line items, tax, total, suggested service types, recommendations kept apart from work done
- [x] Schema additions from the trial: **document kind** (invoice / estimate / deposit / inspection report) with the items kept as lines whatever the kind; **licence plate** — vehicles gain a plate field; **delivery date**, offered as the car's in-service date; **next-service reminder** (date and/or miles)
- [x] **You can correct anything AMG read.** On the review screen every field is editable beside the scan — car, shop, date, odometer, VIN, each line, its amount and service tags, totals, document kind — and lines move between work done and recommendations. A confirmed receipt reopens on the same screen and saving rewrites its service; deleting the service sends the receipt back to be checked
- [x] The car is a suggestion, never a decision: VIN, then plate, then VINs/plates printed on receipts already confirmed for a car, then year/make/model, then "your only car". Printed details that disagree with the car you pick are a note, never an error; the car's own details are only ever *filled* from a receipt (plate, VIN, in-service date — each a checkbox you tick), never overwritten
- [x] Both versions are kept: `extraction_json` (what Claude read, never edited) and `draft_json` (what you confirmed)
- [x] Learned aliases: when you confirm, each line's text is remembered with the service types you gave it; the next receipt printing the same words gets those types instead of Claude's suggestion, marked "from your earlier receipts"
- [x] Review screen: scan beside the fields; anything still as Claude read it is drawn dashed until you change it
- [x] Background jobs for multi-file uploads; the inbox updates as each is read; a job whose thread died (restart, deploy) shows as stopped with "Carry on reading"
- [x] `scripts/eval_receipts.py` — per-field accuracy of the original readings against your confirmed receipts (free), or `--reread` to score the current model and prompt on the same files

**Data owned:** `documents`, `receipts`, `jobs`, `service_aliases`; `vehicles.plate`.

**Can go wrong:** the shop prints another car's details (seen in the trial:
two Outback receipts carry a Forester's VIN) → the car you pick wins; the
printed details stay on the receipt as a note. A receipt spans two cars → *not
built*: confirm it under one car and type the other car's part in by hand. A
receipt without an odometer → the event is saved; the odometer model
interpolates. The same receipt scanned twice at different resolutions → hash
dedupe misses it, so the review warns on the same date + total.

**Tests pin:** dedupe; the Claude response is validated against the schema and
a malformed one becomes a review error, not a crash; nothing counts in history
until confirmed; every extracted field can be overridden, before and after
confirming, and the original read is kept; a receipt whose printed VIN belongs
to no car (or another car) can be assigned to any car, and the next receipt
with that VIN is suggested for the same one; alias learning.

**Done when:** the backlog imports and each receipt takes one review pass.
*Built and checked end to end on three real receipts (2026-09-30); the backlog
import itself is yours to run — best done once AMG is on the server (phase 3),
so the data lands where it will live.*

---

## Phase 3 — Deploy to Proxmox

**For:** your real data living on the server from here on, reachable from the
phone.

- [ ] `docs/DEPLOY-proxmox.md`, adapted from paint-decoder's guide: app LXC (2 GB RAM for OCR), Tesseract via apt, venv, systemd unit (gunicorn + uvicorn workers, raised timeout), `amg` server block on the existing nginx LXC (`client_max_body_size`, `proxy_read_timeout`)
- [ ] rsync deploy that excludes `data/` wholesale
- [ ] Backup and restore: `python -m amg.cli backup` (SQLite online backup + files) and the in-app download
- [ ] `.env.example` listing every setting

**Can go wrong:** rsync as root leaves files the app user can't write →
`chown` step in the guide. OCR on a big PDF outlives a timeout → background
jobs, and the timeouts raised as paint-decoder's are.

**Done when:** the app is reachable over NordVPN from the phone, and a backup
restores cleanly into a fresh container.

---

## Phase 4 — Baseline schedules

**For:** the manufacturer schedule each car is judged against.

- [ ] Templates: generic gasoline, hybrid, EV
- [ ] Owner's-manual PDF: locate the schedule pages locally (keywords and interval patterns), send only those pages to Claude, extract items (service type, action, interval miles/months, first-at, severe-service variant, source page)
- [ ] Review screen: every extracted item beside its page; verify, edit, drop
- [ ] AI draft from year/make/model — every item unverified until confirmed
- [ ] Normal vs severe service per vehicle
- [ ] Schedules copied per vehicle so an edit never leaks to another car

**Data owned:** `schedules`, `schedule_items`.

**Can go wrong:** a 600-page manual → find the pages locally first; never send
the whole book unless it has no text layer. A schedule written as a table of
ticks per interval rather than "every N miles" → the extraction schema carries
both shapes. The AI draft is confidently wrong → it never counts until verified.

**Tests pin:** page finding on a fixture manual; "whichever comes first"
survives the round trip; editing one car's schedule leaves another's alone.

**Done when:** every car has a verified schedule.

---

## Phase 5 — Gap engine, Interval Chart, dashboard

**For:** the answer to "what have I missed and what's next?"

- [ ] Odometer model: piecewise-linear between known readings; forward projection from the recent miles-per-day rate
- [ ] Gap engine: walk each schedule item's expected occurrences from in-service (or acquisition) forward; due at the earlier of miles and months; met by a matching service within tolerance; status done / gap / overdue / due soon / upcoming
- [ ] Attest a gap ("done, no receipt") → an attested service event
- [ ] Interval Chart per vehicle — the signature: service items × mileage, ● done (links to its receipt), ✕ gap, ◐ due soon. On phones: "Next up" list first, chart one tap away, scrolls sideways with a sticky item column
- [ ] Garage dashboard: per car, next up, gap count, due-soon badges

**Data owned:** none new — the engine is pure functions over the tables above.

**Can go wrong:** no odometer readings at all → months-only judgement and a
prompt to add one. Services done early → still met. A used car → no gaps
before acquisition.

**Tests pin:** whichever-comes-first; `first_at` offsets (first at 7,500, then
every 15,000); acquisition cutoff; tolerance edges; zero readings; a
hand-checked car's chart matches the engine output exactly.

**Done when:** the chart matches a hand-checked car.

---

## Phase 6 — Fuel and energy

**For:** fuel economy, running cost, and better mileage estimates.

- [ ] Phone form: odometer, quantity (gal or kWh), total cost, full fill?, home/public for charging
- [ ] MPG or mi/kWh between full fills (partials accumulate); cost per mile; trend
- [ ] Every fill-up is an odometer reading feeding Phase 5's model

**Data owned:** `fuel_logs`.

**Tests pin:** partial fills between two full fills; an odometer lower than the
last one is rejected; EV and gas cars side by side.

---

## Phase 7 — Forecast and budget

**For:** how much to put aside, and when.

- [ ] Each upcoming occurrence in the horizon (12 months default) dated from the odometer projection
- [ ] Cost estimate, in order: median of your confirmed costs for that service on this car, then on your other cars (inflation-adjusted) → price book → an AI estimate range, flagged and cached
- [ ] Fuel/energy projection from miles per day × cost per mile
- [ ] Month-by-month budget view per car and in total

**Data owned:** `price_book`.

**Tests pin:** the estimate fallback order; inflation adjustment; an occurrence
beyond the horizon is excluded.

---

## Phase 8 — Outbound alerts

**For:** hearing about due and missed work without opening the app.

- [ ] Daily systemd timer runs `python -m amg.alerts.run` (`--dry-run` prints instead of sending)
- [ ] ntfy push when an item becomes due soon or overdue
- [ ] Weekly email digest via `smtplib` (Gmail app password)
- [ ] `/calendar/<token>.ics` feed; token regenerable from settings

**Data owned:** `alert_log` — each alert sent once per item, occurrence, channel
and level.

**Tests pin:** no duplicate alerts across runs; the ICS feed parses; the token
rejects a wrong value.

---

## Phase 9 — Reports and exports

**For:** looking back, and handing over a car's history when you sell it.

- [ ] Report builder: vehicle, date range, service type or category, shop
- [ ] Search across receipts: what Claude read and you confirmed — shops, line descriptions, notes
- [ ] Output as a printable page or CSV
- [ ] Presets: full history, spend by year and category, fuel-economy trend
- [ ] Sale packet: history plus every receipt merged into one PDF (PyMuPDF)
- [ ] "Download your data" zip

**Tests pin:** filters combine correctly; CSV round-trips; the packet contains
every confirmed receipt for the car.

---

## Parked

- Mathpix as a third reader for the worst scans — credentials are in `.env`, but
  Tesseract + Claude should cover it; revisit if `eval_receipts.py` says otherwise.
- Importing fuel history from other apps.
- Reading fuel receipts.
