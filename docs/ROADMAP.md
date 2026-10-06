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
| Line kinds | Labor, part, fee or other: what the line *is*, not who paid for it. No warranty kind. Work done under warranty keeps its real kind and its services, at $0 or whatever you paid; a warranty you bought (road hazard, extended) is a fee covering no services; a warranty credit against a charged line is other, negative | A battery replaced under warranty is still a battery replacement the schedule needs to see, and calling warranty lines labor would inflate labor spend in reports. Who paid can become its own field if it's ever needed |
| Claude model | `AMG_CLAUDE_MODEL`, default `claude-opus-5-5` | ≈5¢/receipt page. Sonnet 5.5 (≈2¢) or Haiku 4.5 (≈1¢) is a one-line change |
| Vehicles | Gasoline, hybrid, EV | EVs log kWh and mi/kWh instead of gallons and MPG |
| Units | Miles, US gallons, USD, kWh | |
| Fuel entry | Quick phone form at the pump or charger | |
| Alerts | Dashboard badges, ntfy push, weekly email digest, the calendar as an `.ics` file to import | Email and ntfy only need outbound access, so they reach you off the VPN. A subscribed calendar feed can't work: Google Calendar's servers can't reach a VPN-only app (phase 8) |
| Auth | One password (stdlib `hashlib.scrypt`), long-lived HMAC-signed session cookie | Keeps guests on the LAN out; you rarely see the login screen |
| UI | "Service Interval Chart" direction via the frontend-design skill | The app's core question — what did I miss? — *is* the chart |
| Hosting | New app LXC on Proxmox, new server block on the existing nginx LXC, reached over NordVPN | Mirrors paint-decoder's deployment |

**Dependencies** (approved with the plan): `fastapi`, `uvicorn[standard]`,
`jinja2`, `python-multipart`, `anthropic`, `python-dotenv`, `pymupdf`,
`pytesseract`, `pillow`; `pytest`, `httpx` for tests. (`gunicorn` was on this
list for the server; phase 3 dropped it — see there.)
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

- [x] `docs/DEPLOY-proxmox.md`, adapted from paint-decoder's guide: LXC 302 at <amg-ip> (2 GB, 16 GB disk, New York time zone), Tesseract via apt, venv, systemd unit, an `amg` site on the existing nginx LXC 300 at `amg.home.arpa` — and on `:8080` for devices that can't resolve home names over the VPN. Paint-decoder's site becomes nginx's explicit `default_server`, or adding `amg` would take over its address
- [x] **uvicorn runs its own two workers; gunicorn is gone.** Gunicorn's uvicorn worker class is deprecated, and uvicorn's own process manager now restarts dead workers. Timeouts are 300s rather than 600s, because no request waits on Claude or OCR any more
- [x] `scripts/deploy.sh` (run from WSL): rsync with `--delete` and fixed permissions, a dependency install only when `pyproject.toml` changed, the unit and the `amg` command installed from `deploy/`, a database-only snapshot before each restart (last ten kept), then a health check
- [x] **The data lives in `/var/lib/amg`**, outside the code (`AMG_DATA_DIR`, set by the unit and the `amg` command), so no deploy can reach it. The code is root-owned and read-only to the app, which removes paint-decoder's `chown` step
- [x] Backup and restore: `amg backup` / `python -m amg.cli backup` (SQLite online backup + every stored file + a README; `--no-files` for the database alone), the **Back up** page's download, and `amg restore FILE --replace`. A restore checks the zip first: only the names a backup holds, an integrity-checked database, nothing newer than the code. It moves the database it replaces aside and brings an older one up to date
- [x] `.env.example` listing every setting
- [x] Found by the rehearsal: with no API key, reading a receipt failed with "Something went wrong (TypeError)". It now says the key is missing and where to put it

**Can go wrong:** a CLI task run as root creates database files the app can't
write → the `amg` command runs tasks as the app's user, and the CLI refuses to
run as root against data that user owns. A deploy restarts the app mid-read →
the receipt shows as stopped with "Carry on reading". A migration succeeds but
damages data → the before-deploy snapshot, restored after deploying the
previous commit (the guide says why in that order). nginx and uvicorn
disagreeing about keepalive → occasional 502s, so uvicorn keeps connections
75s, longer than nginx's 60s.

**Tests pin:** a backup holds the snapshot, the files and a README, and backs up
a database older than the code; a restore into an empty directory serves the
same data; a restore refuses an existing database without `--replace`, a zip
with unexpected names, a damaged database and one from a newer AMG — each
leaving nothing behind; the CLI refuses root on the app user's data; the
download leaves no temp file. Rehearsed in WSL (Ubuntu 24.04, Python 3.12,
SQLite 3.45 — the container's versions): the deploy's rsync rules, the editable
install, the whole test suite, two workers, and a restored copy served
alongside the original.

**Done when:** the app is reachable over NordVPN from the phone, and a backup
restores cleanly into a fresh container. *Built and rehearsed in WSL
(2026-10-01); deployed to LXC 302 and checked from the phone over NordVPN, with
a backup restored into a fresh container (2026-10-02). Done.*

---

## Phase 4 — Baseline schedules

**For:** the manufacturer schedule each car is judged against.

- [x] Templates: generic gasoline, hybrid, EV — middle-of-the-road intervals, labelled as not the maker's; items only some cars have (timing belt, AWD differentials) start left out
- [x] Owner's manual (PDF or photos): a document of up to 8 pages is read whole; a longer one has its schedule pages found locally (keywords and interval patterns in the text layer, or Tesseract's reading of pages without one, up to 60), the best pages and their neighbours, at most 12; typed page numbers skip the search. Claude reads the pages as images, streamed at high effort, and returns both shapes: written intervals, and tables of marks, which become intervals by arithmetic (evenly spaced → every N; starting late → first at, then every N; uneven → flagged)
- [x] Review screen: the pages read beside every item; anything as Claude read it dashed until changed; rows the schedule gives for other models, engines or transmissions under **Left out** with the reason, one tap to include; **Use this schedule** confirms the lot, as with receipts, and says when it replaces a schedule; save, read other pages, discard
- [x] Claude's draft from year/make/model/trim/engine — the same review, labelled "not from your manual"; nothing counts until used
- [x] Normal vs severe service per car: a severe entry stands in for the normal entry it covers (oil every 6,000 normally, 3,000 severe), the rest apply under both; the schedule page switches between them and shows what the manual counts as severe
- [x] Schedules are per car: using a draft writes the car's own items, and copying another car's schedule makes a draft of its items, so an edit never leaks; editing in place keeps item ids. Every item says where it came from (manual page, Claude's draft, template, set by you) — changing an item's interval or action makes it yours
- [x] `scripts/try_schedule.py` — read a manual, or ask for Claude's draft, and print the schedule as AMG would draft it (findings below)

**Data owned:** `schedule_drafts` (a proposed schedule's reading and draft, like
`receipts`), `schedule_items` and `schedule_item_services` (each car's
schedule: one item per service and action, every interval miles and/or
months, an optional first-due point, normal / severe / both, its source),
`vehicles.severe_service`.

**Can go wrong:** a 600-page manual → find the pages locally first; never send
the whole book. A scan with no text and too many pages to OCR → ask for the
page numbers. A schedule written as a table of marks rather than "every N
miles" → the reading carries both shapes, and the marks become intervals by
arithmetic, not by Claude's sums. A schedule covering several models → rows for
other models are left out, not dropped. The AI draft is confidently wrong → it
never counts until used, and stays labelled as Claude's. A long read → streamed,
so a slow answer isn't mistaken for a stuck one.

**Tests pin:** page finding on a generated 40-page manual, the cap, typed pages
and a textless scan; marks to intervals (even, starting late, a single mark,
uneven); the sample's coolant (first at 137,500 mi / 11 years, then every
75,000 / 6); severe pairing; left-out rows stay out unless included; "whichever
comes first" survives draft → items → editor → items; editing a copied schedule
leaves the original alone; saving keeps ids; nothing counts before it's used.

**Done when:** every car has a verified schedule. *Built and checked end to end
on the sample maintenance plan (2026-10-02); deployed, and the Outback's
schedule read from its maintenance plan and in use on the server (2026-10-02).
Done.*

### Trial findings (2026-10-02)

`samples/2016-Subaru-Outback-Maintenance-Plan.pdf` — two scanned pages: a
table of R/I/P marks in 22 columns (6–132 thousand miles, paired with months)
covering every 2016 Subaru, and a page of notes carrying the severe-service
intervals. Read with `claude-opus-5-5` at high effort: **22¢, 61 s**.

- **Every row was right** against the page, including uneven marks (the BRZ's
  ATF inspected at 30 and 90, replaced at 60 and 120), the fuel filter's single
  mark at 72, and the coolant's written-out first and repeat intervals.
- **Other models were left out with the reason:** the WRX's timing belt and
  five BRZ rows. Clutch operation and manual-gearbox oil, which the table
  doesn't restrict, were kept but flagged as unlikely on a CVT Outback.
- **Severe service came out of the footnotes:** oil and filter every 3,000 mi
  or 3 months, gear and differential oil replaced every 15,000, CVT fluid every
  24,855 (40,000 km), brake fluid every 15,000, and the four inspections
  footnote 6 names every 6,000 — each paired with the normal item it replaces.

**Claude's draft for the same car, from memory: 19¢, 81 s.** The core of it
matched the manual: oil at 6,000 (3,000 severe), the 12,000 inspections, the
30,000 items, spark plugs at 60,000, the coolant's first and repeat
intervals. But it gave the CVT fluid and differential oil the wrong severe
intervals (30,000 against 24,855 and 15,000), missed the fuel filter at 72,000,
the wheel-bearing inspection and the severe fuel-line inspection, and said 6
years for the plugs where the table says 5. It named most of these itself as
the entries it was least sure of. **Decision:** the draft stays a starting
point, labelled as Claude's on every item, and the manual is the way in when
there is one.

---

## Phase 5 — Gap engine, Interval Chart, dashboard

**For:** the answer to "what have I missed and what's next?"

- [x] Odometer model (`engine/odometer.py`): a straight line between readings, with the in-service date as a reading of zero; after the last reading the recent pace (the last year of readings if they span two months, else the whole history); before the first, back along the first stretch, never below zero
- [x] Gap engine (`engine/schedule.py`): each item due at the earlier of its miles and months, **counted from when it was last done** (from new, the first time). A matching service before the *next* one falls due → done (late beyond a tenth of an interval); nothing by then → missed, and the count carries on from the missed due point; due point passed, next not yet → overdue; within 30 days or 1,000 mi → due soon; else later. Nothing is judged before you had the car
- [x] What meets what: a service covering any of the item's service types — an inspection item by anything done to the part, a replacement or procedure only by a replacement or procedure. **A multi-point or state inspection meets every inspection item**, never a replacement (your call: otherwise the dealer's checks would all read as missed)
- [x] Mark as done ("done, no receipt") → an attested service covering the item, from **Mark as done** on next up, **It was done** on a missed one, or a missed or overdue mark on the chart; it shows in the history as "Done, no receipt"; deleting it undoes it
- [x] Interval chart per car: the items that apply, grouped as the schedule is; ● done where the work was done (links to the service), ✕ missed and ▲ overdue (link to mark as done), ◐ due soon, ○ later; today's estimated odometer as the ink line. Open on wide screens; on phones next up comes first and the chart is one tap away, scrolling sideways with the item column fixed
- [x] Car page: next up (every overdue and due-soon item, then the next few, folded after six), "N missed in the past" with each one listed, today's estimated odometer
- [x] Garage: each card says what's next and counts overdue, due soon and missed

**Data owned:** none new — the engine is pure functions over the tables
above; `web/status.py` turns its answer into words and the chart.

**Can go wrong:** no odometer readings → months-only judgement, no chart, and
an item due by mileage alone says it needs a reading. Services done early →
met, and the count restarts from them. A used car → nothing judged before
acquisition ("before you had it"), and with no in-service date the count starts
when you got it. A service with no odometer → placed on the chart from the
odometer model. A long silence → one missed mark per interval that passed.

**Tests pin:** whichever comes first, both ways round; first-due offsets
(first at 7,500, then every 15,000) and "first at 11 years"; the late-service
example (done 13,500 → 19,500 missed → 25,500 done late at 27,000 → next
33,000); the tolerance edge to the day; early services restart the count;
acquisition cutoff; zero readings; what meets what, including multi-point
inspections; normal and severe; the odometer model's straight lines, pace,
in-service anchor and edge cases; **a hand-checked car** — five items, five
services, every mark of its chart and every next-up line worked out on paper
in `tests/amg/web/test_status.py` and matched exactly; marking as done.

**Done when:** the chart matches a hand-checked car. *The engine matches the
hand-checked car in the tests (2026-10-02), and run over the 14 sample receipts
it finds what they show — oil and tire rotations missed where receipts are
missing, inspections met by the dealer's multi-point checks. Checking the
Outback's chart against your full history on the server is yours.*

---

## Phase 6 — Fuel and energy

**For:** fuel economy, running cost, and better mileage estimates.

- [x] Phone form, one tap from the masthead (**Fill-up**; **Charge** when every car is electric; a choice of car when there are several): odometer, gallons or kWh, total cost with the price a gallon shown as you type, **Filled the tank** / **Charged to your usual limit**, home or public for a charge — a home charge is priced at your last home rate until you type a cost. Under **More**: "I didn't log the one before this" and a note. Past dates are fine, for back-filling
- [x] Economy from one full fill to the next (`engine/fuel.py`): partial fills in between add up, a partial before the first full fill is left out, "didn't log the one before" breaks the count, a top-off at no new miles measures nothing. Every average is miles over quantity, never a mean of each tank's figure. Cost a mile (stretches with a cost missing left out), spend, average price, and a stretch more than 40% from the median flagged *unusual, check it*
- [x] The fuel page: last tank, last 12 months, all time, cost a mile, spend, price paid; economy over time (server-drawn SVG, the average as a dashed line); the log, every fill editable and deletable. The car page gets a Fuel (Charging) block
- [x] Every fill-up is an odometer reading feeding Phase 5's model (the `odometer_points` view), checked like any other; the car page's readings list folds after six

**Decisions:** no plug-in hybrids (your call) — gas and hybrid cars fill up in
gallons, electric cars charge in kWh, and the form has no switch. No import:
the log starts at the next fill-up. Each fill keeps its own energy, so
correcting a car's powertrain later never changes old entries' units.

**Data owned:** `fuel_logs`.

**Can go wrong:** a fill-up that isn't logged → the next stretch reads high
(fuel went in that nobody wrote down); "didn't log the one before" keeps it
out, and if it's forgotten, the unusual flag catches it. A fill with no cost →
left out of cost a mile rather than counted as free. A typo'd odometer → refused
when it runs backwards, flagged as unusual when it runs too far forwards.

**Tests pin:** a hand-worked log of 13 fills in `tests/amg/engine/test_fuel.py`
— every stretch and figure worked out on paper — including partial fills
between two full fills, a missed fill on a full and on a partial, a top-off,
the miles-weighted average beating a plain mean, cost a mile with a cost
missing, the 12-month window and the unusual flag's edge; an odometer lower
than an earlier one is rejected; EV and gas cars side by side; a fill-up moving
today's estimated odometer.

**Done when:** the engine matches the hand-worked log *(it does, 2026-10-03)*,
and you log a real fill-up from your phone at the pump and it shows on the car
page and moves today's estimated odometer. *That last part is yours.*

---

## Phase 7 — Forecast and budget

**For:** how much to put aside, and when.

- [x] Each upcoming occurrence in the horizon (12 months, or two or three years) dated from the odometer projection — the gap engine's own walk, so an oil change due twice in the year is budgeted twice; one already overdue is due now
- [x] Cost estimate (`engine/forecast.py`), the first that knows: **your price** → the median of what visits that did the job cost on this car → shops' quotes on this car's receipts → the median on your other cars → Claude's range, flagged and kept. Past prices are brought up to today's at 4% a year
- [x] What a visit charged for a job: its share of the lines that did the work (a line that did several things split evenly), plus the same share of the tax, shop fees and discounts; the visit must have done all of the job (a filter bought alone isn't an oil change)
- [x] Fuel/energy projection: miles a day (`Odometer.rate()`) × the fuel page's cost a mile, month by month
- [x] Month-by-month budget per car (`/vehicles/{id}/budget`) and in total (`/budget`): put aside a month, due now, maintenance and fuel for the horizon, month bars, each month's jobs with where each price came from; the price list, where you set your own or ask Claude (a background job, one call per car, a few cents). The garage gets a line, and next up shows each job's cost

**Decisions:**

- **Your price beats your history** (this phase's change to the order above,
  which had the price book after it): otherwise an estimate from old receipts
  could never be corrected. Removing your price brings AMG's back.
- **Inflation is 4% a year**, about what the BLS index for US motor vehicle
  maintenance and repair rose from 2016 to 2025 (≈50% over the decade, 1.4%
  early on, 8% in 2023). It's `INFLATION` in `engine/forecast.py`.
- **Inspections are part of a visit:** an inspection job with nothing you've
  paid for it alone counts as $0 and isn't sent to Claude; a dealer checks
  these while doing other work.
- **Overdue work is due now, not saved for:** the put-aside figure spreads
  only what's still to come; what's overdue shows on its own as *due now*.
- **Fuel stays off the month bars** — steady and paid as you go, it would only
  flatten the months that matter — and is in each month's list instead.
- **Claude is asked only when you press the button**, for the jobs nothing
  else prices; its ranges count at their midpoint and are checked (upside
  down, nothing, or over $20,000 is refused).

**Data owned:** `price_book` — per car and per job (service types + action),
so a price outlives the schedule item that asked for it.

**Can go wrong:** work done under warranty or as goodwill is a $0 line (see
*Line kinds* above) → it would drag the median toward zero, so a visit whose
share comes to nothing isn't a price. A package line ("30,000-mile service")
→ split between the jobs it did, the inspections on it free. A receipt
history still being uploaded → false overdue jobs inflate *due now*, not the
monthly figure. Claude's thread dies mid-call (a deploy) → the page says
pricing stopped and offers to ask again. A car with no schedule → fuel only.

**Tests pin:** a hand-worked set of visits in `tests/amg/engine/test_forecast.py`
— overhead shared to the cent, a package split, a filter-only visit, a $0
goodwill visit that would have lowered the median, a discount and a credit;
the fallback order tier by tier; inflation; an occurrence beyond the horizon
excluded; oil twice in a year; a one-off; overdue now; fuel per month. The
pages: a worked car's figures, setting and removing a price, a bad price
refused on its row, asking Claude (faked) through to its range in the totals,
a stalled ask, the horizon switch, the garage line, archived cars left out.

**Done when:** the engine matches the hand-worked figures *(it does,
2026-10-03)*, and on the server the Outback's budget is priced from your
receipts, with Claude asked only for what they don't cover, and the year's
total looks believable to you. *That last part is yours.*

---

## Phase 8 — Outbound alerts

**For:** hearing about due and missed work without opening the app.

- [x] Daily systemd timer (`deploy/amg-alerts.timer`, 8:00, catching up after a boot) runs `python -m amg.alerts.run`, or `amg alerts`; `--dry-run` prints instead of sending
- [x] ntfy push when a job comes due soon or goes overdue: one push per car per run, tapping it opens the car
- [x] Weekly email digest via `smtplib` (Gmail app password), the first run of each week: overdue, due soon, missed, coming up and the year's budget per car, and receipts to check. It goes out even when nothing's due
- [x] ~~`/calendar/<token>.ics` feed; token regenerable from settings~~ → the next 12 months as an `.ics` **file**, attached to the weekly email and downloadable from the Alerts page, to import into Google Calendar. A subscribed feed can't work: Google's servers fetch it, and they can't reach a VPN-only app
- [x] Alerts page (`/alerts`): each channel's settings with a test send, the per-car switch, the calendar file, the last run and what went out

**Decisions:**

- **Alerts are per car, off until turned on, and turning on takes stock:**
  what's already due or overdue is logged as known, not pushed. Keep a car
  off while its old receipts are still going in: until they're all in, work
  that was done looks overdue.
- **What counts as the same alert:** a job (service types + action, as the
  price book keys it) and its *round*, the last service that did it. One push
  when the round comes due soon, one when it goes overdue, and none of the
  first after the second. A missed occurrence doesn't start a new round, so
  an undone job isn't pushed again; the weekly email keeps saying so. Doing
  the job starts the next round. A new schedule with the same jobs alerts
  nothing new.
- **One push per car per run**, the jobs listed in it, so a bad day doesn't
  buzz six times. Overdue is high priority.
- **The weekly email always goes**, "nothing due this week" included: an
  email that stops coming is how you'd notice the alerts had stopped.
- **The calendar's event IDs count occurrences since the car's records
  begin** (the 9th oil change), so dates passing, a job done late and the
  odometer moving a date all describe the same event. Whether Google moves an
  imported event or adds a copy on re-import is for you to see; if it copies,
  the way to refresh is a fresh calendar.
- **No new dependencies:** ntfy's JSON publish over `urllib.request`, and
  `smtplib`/`email`. Settings are `.env` (`AMG_NTFY_*`, `AMG_SMTP_*`,
  `AMG_EMAIL_TO`, `AMG_BASE_URL`); tests clear them, so no test sends for
  real whatever your `.env` says.

**Data owned:** `vehicles.alerts`, the switch; `alert_log`, every alert
claimed before it goes out, `UNIQUE (channel, subject, level)` so it goes
once, with failures given back for the next run. The last run's time and
summary are in `settings`.

**Can go wrong:** two runs at once (the timer and `amg alerts`) → the claim
lets only one send. A run that dies mid-send → its claim stays, so that
alert isn't sent twice. ntfy or Gmail unreachable, or a wrong setting → the
alert is logged as failed with the reason (on the Alerts page), the run exits
1 so systemd shows it, and the next day's run tries again. The container off
at 8:00 → the timer runs it after boot; a week whose Monday was missed gets
its email on the first run that week. A topic on ntfy.sh is readable by
anyone who knows it → a long random one. A receipt history still being
uploaded → see the switch above.

**Tests pin:** no duplicate alerts across runs (the same day, the next,
straight to overdue, a missed round, a new schedule, a claim already taken);
a done job alerting again; taking stock; one push for several jobs; a failed
push or email tried again; the email once per ISO week, late if Monday was
missed; the digest's words, its HTML escaped, the `.ics` attached; SMTP with
STARTTLS or SSL and a refused login explained; the calendar file parsing
(folded at 75 octets, escaped, CRLF) with UIDs that survive dates passing and
the job being done; the page's switch, test sends and download behind the
login.

**Done when:** on the server, with ntfy and Gmail in `.env`, **Send a test
push** reaches your phone and **Send a test email** your inbox;
`amg alerts --dry-run` lists what it would send; after the next 8:00 run
`systemctl list-timers amg-alerts` and the Alerts page show it ran; the
`.ics` imports into a Google calendar, and you've seen whether a second
import moves events or copies them; and the first Monday email arrives.
*That's yours.*

---

## Phase 9 — Reports and exports

**For:** looking back, and handing over a car's history when you sell it.

- [x] Report builder (`/reports`, footer link; each car's service history has a Report button): car, from and to dates, a service type or a whole category, and a shop (part of the name, any capitals; "own work" finds yours). Every filter set has to match, and they live in the address bar, so a report is a link
- [x] Search across receipts: what Claude read and you confirmed — shops, line descriptions, notes. Came forward onto the receipts page: search (every word must match; a line's service types and the total count too), car and year filters, and sorting, newest receipt date first by default
- [x] Output as a printable page or CSV: **Print** prints the report alone, headed with what it is ("Service history · Outback · Brakes · from Jan 2019 · printed …"); **Download CSV** is what the view shows
- [x] Presets, as the page's three views: **History** (newest first; narrowed to a service, the lines that did it, the rest counted), **Spending** (categories down, years across) and **Fuel** (month by month per car, with the trend chart a dot a month)
- [x] Sale packet (`/vehicles/{id}/sale-packet.pdf`): the car, its VIN and odometer, and every service oldest first, laid out by PyMuPDF's Story with the page each receipt starts on; then every confirmed receipt as stored, each with a bookmark
- [x] "Download your data" zip (`/reports/your-data.zip`): cars, service history, fuel, odometer, schedules and prices as CSV; every confirmed receipt named by date, shop and car; the manuals schedules were read from; a README

**Decisions:**

- **Confirmed services only, archived cars included.** A receipt waiting to
  be checked is in nobody's history; a car you've sold still has one, and its
  packet is wanted after it's gone.
- **Spending adds up to what you paid.** A line's amount goes under its
  category (the first of its service types in catalogue order, or the one
  asked for), tax under Tax, and whatever a printed total leaves over — shop
  supplies, an untagged line, a discount the invoice didn't itemise — under
  Other. A service with no total counts its lines and tax. Narrowed to a
  service, only its lines count. The table is in whole dollars, so a decade
  fits across a laptop and on paper (it prints landscape); the CSV has cents.
- **A month's fuel economy is its measured stretches,** full to full, counted
  in the month each ended: miles over quantity, never an average of tanks.
  Spent and price are every fill that month, partial ones included.
- **CSV for a spreadsheet:** UTF-8 with a byte-order mark (Excel), amounts as
  plain numbers, ISO dates, and text that would read as a formula
  ("-Oil filter") given a leading apostrophe. The History CSV is a row a
  line, the service's columns on each, and Visit # to count services once.
- **The sale packet is for a buyer:** oldest first, the work in service-type
  names, "Owner's own work" for yours; your notes left out. Scans go in as
  they are, so a name and address on a receipt show — the page says so.
  A stored file that's gone is marked "file missing" and the rest still go in.
- **Your data is a copy to read, not a backup:** nothing in it goes back
  into AMG. Back up keeps the database; the two pages point at each other.
- Money now puts a credit's minus first everywhere: -$20.00, not $-20.00.

**Data owned:** none new — reports read what earlier phases keep.

**Can go wrong:** a shop spelled three ways → the shop filter matches part of
a name, and the suggestions list each spelling once. A line covering two
categories → counted once, under the first. A decade of years → the table
scrolls inside its own box on a phone, never the page, and prints landscape.
A large packet or zip → built in the system temp directory and deleted once
sent, like a backup. A receipt history still being uploaded → reports say
only what's confirmed; make the packet again once it's all in.

**Tests pin:** filters combine correctly (car × dates × service type or
category × shop, alone and together; dates inclusive; From after To swapped;
unconfirmed services never counted; a car or service not on offer dropped);
CSV round-trips (read back, every value as the report said it, commas, quotes,
line breaks, "°" and "é" intact, guarded cells, the Amount column summing to
the report); the packet contains every confirmed receipt for the car (a
two-page PDF, a PNG and a JPG, a bookmark each, the table's page numbers
pointing at them; a receipt waiting and another car's left out; notes left
out; a missing file said). Spending's columns adding up, with a discount and a
two-category line; fuel by month not an average of tanks; the data zip's
sheets, names and README; the pages, downloads and their login.

**Done when:** on the server, each car's History report matches its car page;
Spending's yearly totals look right to you; a CSV opens in Excel or Google
Sheets with the amounts as numbers; a printed (or print-to-PDF) report reads
cleanly; the Outback's sale packet opens with a bookmark for every confirmed
receipt; and the data zip opens with its receipts sensibly named. *That's
yours.*

---

## Phase 10 — Inspections and registration

**For:** never letting a safety inspection, an emissions inspection or the
registration lapse.

- [x] Each car's page has a row for each (no emissions row on an electric car unless one's logged): when it expires in the schedule's marks and words — "Expires Oct 31 · in 26 days", "Expired Sep 30 · 5 days ago" — a form to log the next one, and its history, each record editable and deletable. Archived cars have none
- [x] AMG's guess at the expiry, always a month's end: an inspection counts from the day it was done, a registration renewal from the old expiry (or the day you renewed, if it had lapsed); how long one lasts is what your last two records show in whole years, else 12 months (24 for emissions)
- [x] An inspection in the service history — a State inspection or Emissions test line on a confirmed service — that would move the expiry later is offered: **Log it** fills the form from the receipt and links the record to it while the dates match. With nothing logged yet, only one whose sticker could still be on the car
- [x] The garage card says what's due soon or expired
- [x] Reminders: a push 30 days before, another in the last week, one the day after it expires; the weekly email's Overdue and Due soon lists; each expiry in the calendar file
- [x] Download your data gets `inspections-and-registration.csv`
- [x] The budget counts the fees: each one with a date, in the month it expires (due now once it has) and every interval after, at what you paid last time — the newest record's cost, else for an inspection its receipt line. The month list names each one; a fee with no cost is left out and links to where to add it. Reminders say what it cost

**Decisions:**

- **Not part of the maintenance schedule.** The state sets these dates, not
  the manual, and they run to the date on the sticker or card rather than
  miles and months from when work was done. AMG builds in no state's rules:
  you type the expiry, and its guess is only that.
- **A receipt never decides.** It says an inspection happened, not what the
  sticker says, so it's an offer you save, like everything Claude reads.
- **Reminders don't wait for the car's alerts switch.** The switch keeps job
  alerts quiet while old receipts are still going in; a date you typed
  yourself can't be wrong that way. A car with its alerts off is in the
  daily run and the weekly email for its dates alone ("Maintenance alerts
  are off for this car"), and turning alerts on takes stock of jobs only.
- **One push per car per run still,** dates and jobs together; with several
  in it the title is the counts ("Outback: 1 overdue, 1 due soon"), since a
  registration isn't a job. Expired says expired, not overdue.
- **Fees count with maintenance** (added after the phase shipped): in put
  aside, due now and the bars, the pages saying "maintenance and fees" and
  how much of it is fees, rather than another column. A fee is last time's
  cost as it was — the state sets it, so no 4% a year — and Claude isn't
  asked. Once a kind has a date, a schedule item for the same inspection
  drops out of the budget, so it isn't counted twice.

**Data owned:** `renewals` — a row per inspection or renewal: kind, when
done (optional), when it expires, cost, note, and the service it was logged
from. A kind's current one is the latest expiry. Alerts reuse `alert_log`:
the subject is `{car}:renewal:{kind}:{expires}` at level due or overdue, with
`:week` added for the last week's push.

**Can go wrong:** a date typed wrong → edit it; the reminders follow the new
date (a corrected date is a new round, so it can alert again). Inspected
early → the guess counts from the inspection, and the sticker is the truth.
A failed inspection on a receipt → offered until the passing one is logged.
Logging from a receipt and changing the date → no longer linked to it. A
state with no emissions testing, or none at all → leave that row untracked.

**Tests pin:** the status edges (31/30 days, 8/7, the day itself, the day
after); month ends and leap years; the guess for an early inspection, a
registration renewed on time and lapsed, an interval learned from two
records, and the defaults; when a receipt is offered and when not (already
logged, wouldn't move the expiry, a sticker long expired, waiting to be
checked, another car's); linking only while the dates match; the forms'
errors; the pushes at 30 days, the last week and expired, each once, a new
expiry alerting afresh, a first sighting in the last week pushed once; going
with the car's alerts off and its jobs not; taking stock of jobs only; the
email for each kind of car; the calendar's fixed UIDs, expired ones left out;
the export's sheet. The budget: when each fee falls (expired now, then from
today; three registrations in three years), priced from a record and from a
receipt line with no inflation, a fee with no cost left out, a schedule's
State inspection not counted twice, and a reminder's cost.

**Done when:** on the server, each car's dates are entered and read right
on its page and the garage; the Outback's registration reminder arrives as
a push and in Monday's email while its job alerts stay off (once ntfy and
Gmail work); an imported calendar shows the expiry dates; and the
Outback's budget has its fees in the right months at what you paid. *That's
yours.*

---

## Parked

- Mathpix as a third reader for the worst scans — credentials are in `.env`, but
  Tesseract + Claude should cover it; revisit if `eval_receipts.py` says otherwise.
- Importing fuel history from other apps.
- Reading fuel receipts.
