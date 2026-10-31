> **Approved** 2026-10-02 20:14 · **Roadmap** [Phase 4](../ROADMAP.md#phase-4--baseline-schedules)
>
> **Built in** `b6612ac` feat(db): schedule tables, `2fdf632` feat(schedules): read schedule pages and turn marks into intervals, `cb1056a` feat(schedules): templates and background reading, `228fea3` feat(web): schedule review, schedule page and editor, `8c8ebfe` docs(roadmap): tick off phase 4, with the trial findings, `a8f7056` fix(web): name the file in scan links so a cached page is never the wrong one, `9985c9a` docs(roadmap): mark phase 4 done
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 4: Baseline schedules

## Context
Phase 3 is done (`b0c0f87`). Phase 4 gives each car the manufacturer schedule its history is judged against; Phase 5's gap engine reads it.

The real test case is `samples/2016-Subaru-Outback-Maintenance-Plan.pdf`:
- **Two scanned pages.** The Epson text layer is garbled.
- **A tick table.** R/I/P marks sit in columns running from 6k to 132k miles, paired with 6 to 132 months.
- **Some rows don't apply to the Outback.** The table covers every 2016 Subaru, so some rows are for the WRX, the BRZ or manual transmissions only.
- **Some intervals are written as prose.** For example, coolant is due first at 137,500 mi or 11 years, then every 75,000 mi or 6 years.
- **Severe-service variants are in the notes.**
  - Oil every 3,000 mi or 3 months.
  - Gear oil replaced every 15k or 15 months, where normal service only inspects it.
  - Inspections every 6k or 6 months.

The design is built around this document.

## How it works for you
1. **Starting a schedule.** The car page gets a **Maintenance schedule** section. Until the car has a schedule, there are four ways to start one:
   - **Read the owner's manual.** Upload a PDF or photos, using the phone camera and "combine photos" as with receipts. An optional **Pages** field (e.g. `30-31`) skips the page search.
   - **Draft one with Claude**, from the car's year, make, model, trim and engine.
   - **Start from a template**: generic gasoline, hybrid or EV, preselected from the car's powertrain.
   - **Copy another car's schedule.**
2. **Reviewing the draft.** Every way ends in a draft on one review screen.
   - The manual pages that were read are on the left, and the items are on the right.
   - Anything still as Claude read it is drawn dashed until you change it, as with receipts.
   - Rows the manual says don't apply to this car go under **Left out**, with the reason (e.g. "Timing belt (WRX/WRX STI)") and an **Include** button.
   - **Use this schedule** confirms the whole draft in one step, as with receipts. If the car already has a schedule, the page says it will be replaced.
   - Also on the screen: **Save draft**, **Read it again** (optionally with different pages) and **Discard**.
3. **The schedule page.**
   - Items are grouped by category.
   - Each item shows where it came from: "Owner's manual p. 30", "Claude's draft — not from a manual", "Generic template" or "Added by you".
   - A **Normal / Severe service** switch shows the manual's list of severe conditions.
   - **Edit schedule** opens the same editor and saves in place.

Nothing in a draft counts. Phase 5 reads only the items you've confirmed.

## Data: migration `src/amg/migrations/0005_schedules.sql`
- **`vehicles.severe_service`**: `INTEGER NOT NULL DEFAULT 0`.
- **`schedule_drafts`**: a proposed schedule, with the same lifecycle as `receipts`.
  - Columns:
    - `vehicle_id`
    - `origin`: manual, claude, template or copy
    - `document_id`: nullable and *not* unique, since one manual can serve two cars
    - `pages_json`
    - `job_id`
    - `status`: queued, reading, read, failed, confirmed or discarded
    - `extraction_json`: never edited
    - `draft_json`
    - `warnings_json`
    - `error`
    - usage columns
    - timestamps
- **`schedule_items`**: the car's confirmed schedule.
  - Columns:
    - `vehicle_id`
    - `position`
    - `name`, as the manual words it
    - `action`: replace, inspect or perform
    - `interval_miles`, `interval_months`
    - `first_miles`, `first_months`: when the first one is due, if that differs from the interval
    - `applies`: always, normal or severe
    - `note`
    - `source`: manual, claude, template or you
    - `document_id`, `page`, `draft_id`
  - A CHECK requires at least one interval or first-due value.
- **`schedule_item_services`**: links an item to its service types, like `line_item_services`. There is one action per item, not per type.

In the roadmap, the "Data owned" line for this phase becomes these names; it currently says `schedules`. I'll also record the matching rule in Phase 5: an item is met by a confirmed service that covers *any* of its types with a sufficient action, and a replacement also counts as an inspection.

## Reading: `src/amg/ingest/manuals.py`
- **Finding the pages: `find_pages(path, pages=None)`.**
  - Typed pages win.
  - A document of 8 pages or fewer is sent whole, which covers the sample.
  - Otherwise each page's text is scored:
    - keywords: "maintenance schedule" or "maintenance interval", "whichever comes first" or "whichever occurs first", "severe", "replace", "inspect", "rotate"
    - interval patterns: `\d{1,3},\d{3} (mi|miles|km)`, `\d+ months`, `x 1,000`
  - The best pages are taken along with the pages next to them, because schedule tables run across pages. At most 12 pages are sent.
  - Pages with no text layer are OCR'd with the existing `receipts.local_text`, up to 60 of them. Beyond that, the draft fails with "Tell AMG which pages hold the schedule."
- **Sending them to Claude.**
  - It reads page images, as phase 2 does for receipts, through `claude.parse`. Effort is high and `max_tokens` is 32k.
  - Each image is labelled with its real page number, and the car's details are included so Claude can say which rows apply.
  - I'll read the claude-api skill before writing this, to size timeouts so the job stall detector (600 s) stays right.
- **Schema `ScheduleExtraction`.**
  - Top level: `printed_for`, `severe_conditions`, `uncertain`.
  - `items[]`, one entry per row and action. A row with both I and R marks becomes two entries.
  - Each item holds:
    - `name`, `page`, `service_codes`, `action`
    - `every_miles`, `every_months`, `first_miles`, `first_months`: the prose shape
    - `ticks: [{miles, months}]`: the tick-table shape
    - `severe`: this entry applies only under severe conditions
    - `note`
    - `applies_to_vehicle` and `why_not`
  - Distances are in miles.
- **Claude's draft: `draft_schedule(car, types)`.** It uses the same schema with no pages. The prompt asks for the manufacturer's schedule from Claude's own knowledge, and to say what it isn't sure of.

## Draft logic: `src/amg/ingest/schedule_drafts.py`
This is pure functions, like `ingest/drafts.py`.
- **`intervals_from_ticks(ticks)`.** Miles and months are worked out separately from the paired columns.
  - Evenly spaced from the first interval: every N.
  - Evenly spaced but starting later: first due at that point, then every N.
  - A single tick: every N, assuming the pattern repeats past the table.
  - Uneven spacing: the most common gap, plus a warning on the review screen.
- **Severe pairing.**
  - If a severe entry has the same types and action as an always-entry, that always-entry becomes normal-only. Example: oil every 6k or 6 months normally, 3k or 3 months severe.
  - A severe entry with no such twin stays severe-only. Example: gear oil replaced every 15k or 15 months.
- **Checks.** Unknown codes are dropped with a warning, as `receipts.checks` does. An item with no interval is flagged.
- **The draft itself.**
  - A `ScheduleDraft` dataclass with `to_dict` and `from_dict`.
  - `to_items(draft)` turns it into schedule items.
  - `from_items(items)` turns items back into a draft, for copying and editing.

## Templates: `src/amg/ingest/schedule_templates.py`
- Three generic, conservative schedules stored as data:
  - gasoline
  - hybrid: the gasoline items plus inverter coolant and the hybrid battery items
  - EV
- Each item is tagged with codes from the existing 45-type catalogue.
- They're labelled "Generic — not your manufacturer's", and are reviewed and confirmed like any other draft.

## Repo: `src/amg/repo/schedules.py`
All the SQL lives here.
- **Drafts:** create, claim_next, mark_read and mark_failed, requeue (with pages), get, save_draft, discard and restore, and the latest draft for a car.
- **Schedule:**
  - `items(conn, vehicle_id)`.
  - `confirm(conn, draft_id, draft)` replaces the car's items in one transaction.
  - `save_items(conn, vehicle_id, items)` updates rows by id, inserts new ones and deletes removed ones. Ids stay stable, so Phase 8's alert log can refer to them.
  - `set_severe`.
- **Copying** another car's schedule makes a draft from its items, so the two cars never share rows.

## Background reading: `src/amg/ingest/background.py`, `src/amg/repo/jobs.py`
- There's a new job kind, `read_schedule`, and `run()` dispatches on the job's kind.
- `jobs.resume` also requeues schedule drafts.
- Tests keep replacing `spawn` with `run`, so jobs run inline.

## Web
- **`src/amg/web/routes_schedules.py`**:
  - `GET /vehicles/{id}/schedule`
  - `POST /vehicles/{id}/schedule/{manual|claude|template|copy}`
  - `GET|POST /vehicles/{id}/schedule/edit`
  - `POST /vehicles/{id}/schedule/severe`
  - `GET|POST /schedule-drafts/{id}`, which saves the draft or uses it as the schedule
  - `POST /schedule-drafts/{id}/read-again`
  - `POST /schedule-drafts/{id}/discard`

  Page images reuse `/documents/{id}/pages/{n}`.
- **`src/amg/web/schedule_editor.py`**, like `line_editor.py`, with `clean_items`, `parse_items` and `rows_from_*`. It gives one error per row:
  - a row needs a name or a service type
  - an included row needs at least one service type, or Phase 5 can't match it against your services
  - it needs at least one interval or first-due value
  - numbers go through `forms.miles`, and months must be whole numbers
- **Templates:**
  - `schedule.html`
  - `schedule_draft.html`: the review screen, with reading and failed states that poll with htmx, as `receipt.html` does
  - `_schedule_editor.html`
  - `vehicle.html` gets a summary block (number of items, source, normal or severe, a link), or the four ways to start when there's no schedule.
- **`app.js`**: `scheduleEditor()` spreads `lineEditor()` so it reuses the chips, `pick`/`unpick` and `typeName`. Each row has:
  - name
  - service types
  - action
  - "Every [ mi ] or [ months ], whichever comes first"
  - first due, behind a toggle
  - applies
  - note
  - a page link
  - include or leave out

  Changing a row's interval or action marks its source as "you".
- **`app.css`**: the editor rows, designed for phones first. I'll use the frontend-design skill on the new screens and check them at 375px and at desktop width.

## Trial first, as phase 1 did
- `scripts/try_schedule.py FILE` prints Claude's reading and the draft worked out from it. `--draft "2016 Subaru Outback"` tries Claude's draft instead.
- I'll run it on the sample **before building the UI**, compare the result item by item against the page images, and record the findings in the roadmap.
- **Cost:** about 15–40¢ per run with Opus 5.5 at high effort.

## Commits
1. `feat(db): schedule tables`
2. `feat(schedules): find schedule pages, read them with Claude, turn ticks into intervals`, plus the trial script. Then the trial run on the sample.
3. `feat(schedules): templates, drafts and background reading`
4. `feat(web): schedule review, schedule page and editor`
5. `docs(roadmap): tick off phase 4`, with the data names, trial findings and Phase 5's matching rule.

## Tests
- **`tests/amg/ingest/test_manuals.py`**:
  - On a generated 40-page fixture manual, the schedule pages (23–24) are found together with the pages next to them, and the cap holds.
  - A document of 8 pages or fewer is sent whole.
  - Typed pages override the search.
  - Images are labelled with their real page numbers.
- **`tests/amg/ingest/test_schedule_drafts.py`**:
  - Ticks become intervals for each case: even, starting later, a single tick, and uneven (which warns).
  - The sample's coolant comes out as first due at 137,500 mi or 132 months, then every 75,000 mi or 72 months.
  - Severe pairing works as described above.
  - Left-out rows stay out.
  - **"Whichever comes first" survives the round trip** from draft to items, to editor rows, and back to items.
- **`tests/amg/repo/test_schedules_repo.py`**:
  - Confirming replaces the car's schedule.
  - Saving keeps item ids.
  - **Editing a copied schedule on one car leaves the other car's schedule alone.**
  - The severe switch.
- **`tests/amg/web/test_schedule_pages.py`**, with Claude mocked like the `reads` fixture in `test_receipt_pages.py`:
  - upload, then review, then use the schedule
  - Claude's draft, the template and copying
  - a form with errors keeps its rows
  - left-out rows aren't saved unless included
  - discard, and read again with typed pages
  - nothing counts until confirmed

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- The trial script on the sample matches the printed table:
  - spark plugs every 60k
  - air cleaner every 30k
  - coolant's first-due and repeat values
  - the WRX and BRZ rows left out
  - the severe items from the notes
- Locally, run `uvicorn` with a scratch database:
  - upload the sample for an Outback, review it, use it, edit it and flip the severe switch
  - try the template and Claude's draft too
  - screenshots at 375px and at desktop width
- You then deploy with `bash scripts/deploy.sh` and read your manuals on the server. Phase 4's "done when every car has a verified schedule" is yours to tick off.
