> **Approved** 2026-10-08 07:25 · **Roadmap** [Phase 12](../ROADMAP.md#phase-12--specs-card)
>
> **Built in** `5b8f278` feat(specs): a specs card per car, typed or from your receipts, `63c7824` feat(specs): read specs from the owner's manual or photos, `b352eb7` fix(specs): wiper lengths, "e.g." examples, and the card's car name, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **Wiper boxes** are offered a blade's length from the receipt line ("26 in") before its part number, since any brand's blade of that length fits (`b352eb7`).
> - **Placeholders say "e.g.",** so an example part number on an empty box isn't taken for the car's own, and a suggestion already in its box isn't offered (`b352eb7`).
> - **`spec_reads` keeps `values_json`,** the boxes a reading fills, beside Claude's untouched `extraction_json`; a reading has no draft of its own to save. A stalled reading carries on like a schedule's (`jobs.resume`).
> - **`manuals.find_pages`** takes `scorer` and `sought` (the plan said `score` and `what`); the page-limit message no longer says "schedule pages".
> - **The card names the car** as "2019 Honda Civic EX", without the powertrain, and says nothing for a car with no year, make or model.
> - **One real reading** of a made-up two-page spec sheet: 7¢, 23 s, 15 boxes filled. With two engines printed and none named, Claude filled in the likelier oil capacity and said so under "Worth a look".
>
> The plan below is as it was approved; it isn't edited afterwards.

# Specs card

## Context
You picked idea 4: a specs card per car, so that at the parts counter you have everything to buy: oil and its filter, filters, wiper lengths, tire size, battery, bulbs and fluids. You chose all three ways to fill it:
- **you type values**
- **your receipts** show what was last fitted, with one tap to use it
- **Claude reads them** from an owner's manual or photos, and you check them beside the pages before they're saved

It ships as roadmap Phase 12: two feature commits and a docs commit.

## How it behaves for you

### The card
- **Where:** a **Specs** button in the car page's header, next to Edit car, opens `/vehicles/{id}/specs`.
- **What it shows:** the car's specs in groups, in the order you'd shop for them. Example values are in brackets:
  - **Engine oil:** oil grade (0W-20 synthetic), capacity with filter (4.4 US qt), oil filter (Subaru 15208AA15A)
  - **Filters:** engine air filter, cabin air filter
  - **Wipers:** driver's (26 in), passenger's (17 in), rear
  - **Tires and wheels:** tire size (225/65R17 102H), pressure, cold (35 psi front, 33 psi rear), lug nut torque (89 lb-ft)
  - **Battery and bulbs:** 12-volt battery (Group 35, 550 CCA), key fob battery (CR2032), headlight low beam (H11), headlight high beam (9005), fog lights, brake light
  - **Fluids:** engine coolant, transmission fluid, differential oil, brake fluid (DOT 3)
  - **Fuel and ignition:** fuel (87 octane), fuel tank (18.5 gal), spark plugs
  - **Other:** lines you add yourself, with a name and a value, such as "Trunk light: 168"
- **Electric cars** don't show oil, the engine air filter, coolant, fuel or spark plugs. A field with a value always shows, even if the car's powertrain changes.
- **Where each value came from:** a quiet tag after it, such as "outback-manual.pdf, p. 412" (the file it was read from, linked to that page) or "Set by you", as the schedule's items have.
- **Last fitted, from your receipts:** under the groups for parts, the most recent confirmed service that replaced them. For example: "Last fitted Aug 1, 2026 at Valley Honda: Oil filter 15208AA15A; 0W-20 full synthetic × 5". This is your history, so it shows whether or not the spec is filled in, and a difference between them is worth a look.
- **Empty card:** it says how to fill it, with the read and edit options below.
- **Printing:** the card prints on its own (forms and navigation hidden), headed with the car's name, year, make and model, to keep in the glovebox.

### Typing them in: **Edit specs**
- **One form** with a text box for every field, in the card's groups. Each box has an example as a placeholder.
- **"Other" lines:** add with **Add a line**, remove with **Remove**.
- **Suggestions from your receipts:** under a field, when your confirmed services offer something, a button such as **Use 15208AA15A** fills the box. AMG looks in:
  - **part numbers:** oil filter, air filters, battery, spark plugs. When there's no part number, it uses the line's description.
  - **an oil grade** in engine-oil lines: "0W20 FULL SYN" gives "0W-20"
  - **a tire size** in tire lines: "225/65R17"
  - **wiper lines:** each line is offered to each wiper box, since a receipt rarely says which blade is which
- **Saving:** a cleared box removes that spec, and anything you change becomes "Set by you".

### Reading them: **Read the owner's manual**
- **On the card page, the same uploader as the schedule:**
  - **the file:** **Choose files** or **Take a photo** (photos are read as one file). You can also pick a file AMG already has for this car, such as the manual its schedule was read from, so you don't upload it twice.
  - **Pages:** optional, as for the schedule
  - **cost:** "About 10–25¢."
- **Finding the pages:**
  - **A long manual:** AMG finds the spec pages on its own, as it does the schedule's. It searches for words such as "Specifications" and "Capacities" and for oil grades (0W-20), tire sizes (225/65R17), psi and kPa, DOT 3/4, octane and bulb wattages. It sends at most 12 pages.
  - **A short document** (8 pages or fewer, such as photos of the spec pages and the door-jamb tire sticker) is sent whole.
  - **Typed page numbers** skip the search.
- **While Claude reads** (in the background, like the schedule), the page says it's reading and updates itself when it's done.
- **Checking it:**
  - **Layout:** the pages read beside the same form as **Edit specs**.
  - **What's filled in:** every value Claude read, dashed until you change it, with the page it came from.
  - **Values you already had:** where Claude read something different, the box shows Claude's value with "Was: …" under it. Where Claude found nothing, your value stays.
  - **Worth a look:** anything Claude was unsure of, and any value meant for another engine or trim.
- **Buttons:**
  - **Use these specs** saves the lot. Values left as read keep their file and page; changed ones become yours.
  - **Read other pages**, as the schedule has
  - **Discard**
- **A reading waiting to be checked** shows on the card page until you use or discard it, as schedule drafts do.
- **If the reading fails,** the page says why (no spec pages found: type the page numbers), with **Read it again** and **Discard**.
- **What Claude is told:** read only what's printed and leave out anything the pages don't give. Never fill in from memory. When the manual gives values for several engines or trims, take the one for this car (named from its year, make, model, trim and engine) and note the others.

### Download your data
- **`specs.csv`:** car, group, spec, value, where it came from, and page
- **The `manuals/` folder:** also gets any file specs were read from

## Code

### Commit 1: `feat(specs): a specs card per car, typed or from your receipts`
- **New `src/amg/migrations/0015_specs.sql`:**
  - **`vehicle_specs` table:**
    - `id`, `vehicle_id` (→ vehicles, CASCADE)
    - `key`: a catalogue key, or `custom`
    - `label`: for custom lines
    - `value`
    - `source`: `you` or `read`
    - `document_id` (→ documents, SET NULL), `page`
    - `position`: the order of custom lines
    - `updated_at`
  - **A partial unique index** on `(vehicle_id, key) WHERE key <> 'custom'`
- **New `src/amg/engine/specs.py`** (pure, no I/O):
  - **The catalogue:**
    - `Field(key, label, group, example, powertrains, codes, pick)` for each field above
    - `GROUPS` in order, and `for_car(powertrain, keys_with_values)`
  - `candidates(field, lines) -> list[str]`, by `pick`:
    - `part`: part number, else the description
    - `grade`: a `\b\d{1,2}W-?\d{2}\b` match, written as "0W-20"
    - `tire`: a `\b\d{3}/\d{2}Z?R\d{2}\b` match
    - no duplicates
  - `last_fitted(lines) -> dict[code, Fitted]`: per service type, the lines on the newest visit that replaced it
- **New `src/amg/repo/specs.py`:**
  - `values(conn, car)`: rows, with the document's filename
  - `save(conn, car, inputs)`: replaces the car's rows in one transaction, as `schedules.save_items` does
  - `fitted_lines(conn, car, codes)`: lines on confirmed services covering those codes with action `replace`, newest first, with date, shop and event id
  - `everything(conn)`, for the export
- **New `src/amg/web/specs.py`:**
  - `card(conn, car)`: groups → rows (value, source label, field), each group with its last-fitted lines
  - `form_rows(conn, car)`: values, examples and receipt candidates
  - `parse(form)`: the inputs, and which became yours
  - `source_label()`: "{filename}, p. N" (linked to the page image), or "Set by you"
- **New `src/amg/web/routes_specs.py`:**
  - GET `/vehicles/{id}/specs`
  - GET and POST `/vehicles/{id}/specs/edit`. POST redirects to `/vehicles/{id}/specs?saved=1`.
  - registered in `app.py`
- **Templates:**
  - **New:** `specs.html` (the card), `specs_edit.html`, and `_spec_fields.html` (the field macro the review reuses). Custom lines use an Alpine list. **Use …** buttons set the box's value and fire `input`.
  - **`vehicle.html`:** the **Specs** button in `pagehead__actions`
- **`app.css`:** `.specs` (label and value columns that stack at phone width), `.specs__fitted`, and print rules (`.printhead` on; the read form and actions hidden)
- **`src/amg/reports/export.py`:** `specs.csv` and a README line

### Commit 2: `feat(specs): read specs from the owner's manual or photos`
- **New `src/amg/migrations/0016_spec_reads.sql`:** the `spec_reads` table. Its columns:
  - `id`, `vehicle_id` (CASCADE), `document_id` (SET NULL)
  - `requested_pages`, `pages_json`, `job_id`
  - `status`: queued, reading, read, failed, used or discarded
  - `extraction_json`, `warnings_json`, `error`
  - usage columns, as `schedule_drafts` has
  - timestamps
- **`src/amg/ingest/manuals.py`:** `find_pages(path, typed, score=score, what="maintenance schedule")`. The scorer and the words in its errors become parameters; the schedule's behaviour is unchanged.
- **New `src/amg/ingest/specs.py`:**
  - **The page search:** `score()` with its own keywords. `read_specs(path, car, pages) -> SpecsRead` reuses `manuals.find_pages`, `manuals.describe_car` and `pdf.render`.
  - **What Claude returns:** `SpecsExtraction(printed_for, specs: [SpecValue(key, value, page, note)], uncertain)`. `key` comes from the catalogue, which is listed in the prompt with its examples.
  - **Settings:** effort medium, 16k max tokens, streamed
  - **`to_draft()`:**
    - drops unknown keys and blank values, with a warning for each unknown key
    - keeps the first of a repeated key
    - puts each value's note and the `uncertain` text into the warnings
- **`src/amg/ingest/background.py`:**
  - `SPEC_JOB`, plus `read_specs()`, `read_specs_again()` and `read_one_specs()`
  - `run()` dispatches it, with the same failure handling as schedules
- **`src/amg/repo/specs.py`:**
  - the life of a read: `create_read`, `claim_next`, `mark_read`, `mark_failed`, `requeue`, `get_read` (with `stalled`), `open_reads` and `mark_used`/`discard`
  - `car_files(conn, car)`: files from its schedule drafts and spec reads
- **`src/amg/web/routes_specs.py`:**
  - POST `/vehicles/{id}/specs/read`: an upload or a chosen file
  - GET and POST `/spec-reads/{id}`: the review and **Use these specs**
  - POST `/spec-reads/{id}/read-again`, `/carry-on` and `/discard`
- **New template `spec_read.html`:** its parts are copied from `schedule_draft.html`:
  - the reading, failed, used and discarded states
  - the scan column
  - `_spec_fields.html` with `data-read`, so the dashed style and `app.js`'s `is-edited` toggle work as on receipts
- **`specs.html`:** the read form and the waiting-reads notice
- **`src/amg/repo/reports.py`:** `manuals()` also returns documents that `vehicle_specs` were read from

## Tests
- **`tests/amg/engine/test_specs.py`:**
  - catalogue keys are unique and every group is in `GROUPS`
  - electric cars hide oil and fuel, but a stored value still shows
  - `candidates`:
    - an oil grade from "0W20 FULL SYN"
    - a tire size
    - a part number preferred over the description
    - no duplicates
  - `last_fitted` takes the newest visit that replaced the part, and ignores inspections
- **`tests/amg/repo/test_specs_repo.py`:**
  - `save` replaces, keeps the order of custom lines, and only one row per key
  - `fitted_lines` uses confirmed services only
  - a read's life, from queued to used
  - `car_files`
- **`tests/amg/ingest/test_specs_reading.py`:**
  - the scorer ranks a generated spec page above others in a 40-page PDF
  - typed pages are honoured
  - a short document is sent whole
  - `to_draft` drops unknown keys and keeps the first of a repeated key
  - with `claude.parse` faked, `read_specs` returns the pages and the draft
- **`tests/amg/ingest/test_manuals.py`:** passes unchanged, which shows the refactor kept the schedule's page search
- **`tests/amg/web/test_spec_pages.py`:**
  - the empty card, and the car page's Specs button
  - edit and save make values yours, a cleared box removes the spec, and custom lines work
  - receipt suggestions appear as **Use …**
  - last-fitted lines show on the card
  - **A read, with `spawn` running inline and the reader faked:**
    - the review shows the pages and dashed values
    - saving an unchanged value keeps its file and page
    - a changed one becomes "Set by you"
    - "Was: …" shows where Claude read something different
  - a failed read says why
  - discard
  - a waiting read is listed on the card
  - an electric car's card
- **`tests/amg/reports/test_export.py`:**
  - `specs.csv`
  - the read file appears under `manuals/`
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 3: `docs: Phase 12, specs card`)
- **`docs/ROADMAP.md`:** a new **Phase 12 — Specs card**, in the usual shape:
  - For, the checklist (ticked)
  - Decisions:
    - receipts suggest, they don't fill
    - reading values only from the page
    - one card per car
  - Data owned, Can go wrong, Tests pin, Done when
- **The plan:** saved to `docs/plans/2026-10-08-specs-card.md` with the header, and an index row

## Verification
- **Tests** pass after every commit.
- **The scratch garage** (`scratchpad/p11/data`, made-up data):
  - add a made-up confirmed receipt for the Civic with part numbers (oil filter, 0W-20 oil, cabin filter, two wiper blades) through AMG's own code
  - check the last-fitted lines, the **Use …** buttons, saving, and custom lines
  - print preview of the card
- **One real read** of a made-up spec page: a PDF generated with PyMuPDF, with an oil grade, capacities, tire size and pressure, and bulbs. About 5¢ on your API key, and nothing personal is sent. It checks the prompt and the review end to end: dashed values, pages beside, then **Use these specs**.
- **Layout:** the card, the edit form and the review at 360px and on the desktop, in light and dark themes.
- **Done when (yours), after you deploy:**
  - each car's card is filled, read from its owner's manual or typed from the door sticker, and checked
  - one trip to the parts counter with it
