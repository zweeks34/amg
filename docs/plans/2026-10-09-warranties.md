> **Approved** 2026-10-09 09:55 · **Roadmap** [Phase 14](../ROADMAP.md#phase-14--warranties)
>
> **Built in** `d55a24a` feat(warranties): keep part, repair and car warranties, read from receipts or typed in, `744eac5` feat(warranties): ask when a later visit replaces a covered part, and show them before the work, `67e71f0` feat(warranties): look through older receipts for warranties, `250e83a` feat(warranties): warn before a warranty ends, `5fbb16d` fix(warranties): oil, filters and fluids are never a claim; round estimated miles, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **Oil, filters and fluids never ask** (`5fbb16d`). Checking in the browser, a dealer's parts-and-labor guarantee on an oil change asked whether the next oil change was under it; dealers print that guarantee on every invoice. These services (`engine.warranties.ROUTINE`) now never raise the question or an "under warranty" note, the reader lists a shop's general guarantee only for a visit that did more than routine maintenance, and one naming no services covers the visit's work less those.
> - **A receipt's review** says what was under warranty in one notice above the lines, not a note on each line. Only rows found on older receipts are dashed; a new reading's warranties aren't, as its recommendations aren't.
> - **A service's page** has its Warranties block on every confirmed visit not marked done with no receipt, so **Add a warranty** is always there; with nothing to show it says "None came with this visit."
> - **The look's section** is its own partial (`_warranty_look.html`), polled at `/receipts/warranty-look` while it runs; `warranty_looks` has an `updated_at` so `jobs.resume` requeues a look stopped mid-receipt. Its page tests sit with the other warranty page tests, not in `test_background.py`.
> - **Words:** a push or email line names "Powertrain · Subaru", not "Powertrain (Subaru)", which doubled up on names with brackets; an end mileage estimated from readings shows to the hundred; the question says "covered them" for several parts. A car watched for nothing else joins the daily run while a warranty of its is ending (`alerts.cars_with_warranties`).
> - **Checked in the browser** on the scratch garage with made-up warranties and no Claude calls (the key blanked, so **Look for warranties** failed at once and showed Try again): the car's section, the question and **Paid for it** with undo from a service's page, a new receipt's block and note, confirming it, an older receipt's dashed find, the Receipts page section, the form with **From the in-service date**, the sheet, the garage count, and `alerts --dry-run`; at 360px with no overflow, on the desktop, and in dark mode. The oil-change question above was the one thing to change.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Warranties

## Context
This is idea 5: part and repair warranties from receipts, each with an end date or mileage, shown when that part is serviced again. Today AMG's receipt reader is told to skip warranty wording. A battery's 36-month free replacement, a shop's 12 months/12,000 miles on parts and labor, or a lifetime brake-pad guarantee only lives on paper, so it's easy to pay for something that was covered. You chose:
- **The receipts' warranties and the car's own:** read from receipts, or typed in yourself. That includes the car's factory and extended warranties from its booklet.
- **Look through older receipts once:** about 3¢ a page, with the cost shown first. Finds don't count until you check them.
- **AMG asks** when a later visit replaces a covered part. **Done under the warranty** keeps it; **Paid for it** ends it, since the part it covered is gone.
- **A warning before one ends:** a notice on the car's page, a line in the weekly email, and one push.

It ships as roadmap Phase 14, in four feature commits and a docs commit. There are no new dependencies. Claude is called only to read receipts, as now, and for the look through older receipts, which you start.

## How it behaves for you

### Warranties from receipts
- **What the reader looks for:** each warranty a receipt gives *with its terms* for that visit's parts or work, such as "36-month free replacement", "Parts and labor 24 months / 24,000 miles", "Lifetime brake pad warranty" or a tire's road hazard. Disclaimers ("no warranty expressed or implied", "the manufacturer's warranty is the only warranty") aren't warranties and are left out.
- **What it reads for each one:**
  - what it says, as printed
  - who honours it, if not the shop (e.g. Interstate, or NAPA AutoCare nationwide)
  - how long it lasts: months and miles from the visit, whichever comes first, or lifetime
  - what it covers, as services from that visit's lines (e.g. 12-volt battery)
  - If a warranty is free for a while and prorated after, the free period is what counts, and the rest is described.
- **On the receipt's review:** a **Warranties** block between "Recommended, not done" and the totals, with rows like the recommendations'.
  - **Fields:** Description, Who honours it, Months, Miles, a Lifetime box, and the services it covers as chips.
  - **Add a warranty** adds a row.
  - **Errors:**
    - "Say how long it lasts: months, miles, or lifetime."
    - "Choose what it covers, such as 12-volt battery."
- **When it starts:** a receipt's warranty starts on the visit's date and odometer. It counts once the receipt is confirmed, and saving the receipt again rewrites it. A warranty found on an older receipt (below) is the exception: it starts counting when you save that receipt.
- **A road hazard or extended warranty you bought** is still a fee line, as the roadmap says. It's now also kept as a warranty.

### Older receipts, looked through once
- **On the Receipts page,** once, while any confirmed receipt was read before AMG kept warranties:
  - "N receipts were read before AMG kept warranties. Look through them: about $1.40."
  - **Look for warranties** starts it. The cost is worked out from each receipt's first reading.
- **How it works:**
  - It runs in the background like receipt reading, with "Looked at 12 of 41" while it runs.
  - Each receipt's pages go to Claude with one question: what warranties does it print? Claude also gets the visit's lines as you confirmed them, so it names the right services.
  - If the app restarts mid-way, **Carry on looking** picks it up.
- **What it finds:**
  - Each find is added to that receipt, drawn dashed and marked "Found Oct 9: check it against the scan." It doesn't count until you **Save changes** on that receipt. To throw one away, remove the row and save.
  - The Receipts page lists the receipts with finds until each is saved, and the car's Warranties section says "Found on 2 receipts: check them."
  - A receipt it couldn't look at is listed with **Try again**.

### Adding one yourself
- **Where:** **Add a warranty** in the car's **Warranties** section, and on the page of a service you logged by hand.
- **The form:**
  - **Name** (required, under 120 characters), e.g. "Powertrain" or "Battery free replacement"
  - **Who honours it**, e.g. Subaru, Costco, or the shop
  - **What it covers:** **The whole car**, or **Parts or work**, chosen as chips like the line editor's.
  - **Starts on** (required) and **Miles then** (optional; left blank, it's estimated from your readings). With "The whole car" chosen, **From the in-service date** fills in the car's in-service date and 0 miles.
  - **Lasts:** a number with months or years, and/or miles, whichever comes first, or a **Lifetime** box
  - **Details:** the terms, a contract number, a phone number for claims
  - **Came with:** one of your visits, optional. From a service's page, it's filled in from that visit: its date, odometer and shop, and the parts it replaced.
- **Buttons:** **Save warranty**, Cancel, and on edit **Delete warranty** (with a confirm).
- **Editing:** a receipt's warranties say **Edit on the receipt** instead, as services from receipts do.

### On the car's page
A **Warranties** section (`#warranties`) sits after Shop recommendations, with **Add a warranty** in its heading. Empty, it says: "No warranties yet. AMG reads them from receipts; add the car's own from its warranty booklet."
- **Each warranty in force shows:**
  - its name and who honours it
  - what it covers ("The whole car", or "12-volt battery")
  - its terms ("3 years or 36,000 mi, whichever comes first", "Lifetime")
  - where it came from (Costco's receipt, Mar 1, 2025, linked)
  - "Until Mar 1, 2028 or about 72,500 mi · about 2 years 5 months left"
  - Edit
- **Ending soon** (within 60 days, or the miles you usually drive in 60 days): a due mark and "Ends in 45 days, Nov 23" or "Ends in about 1,800 mi, around Nov 20".
- **The question** (below), when there is one
- **Ended ones** fold under "N ended":
  - "Ended Mar 1, 2028"
  - "Ended at 72,500 mi, around Aug 2027"
  - "Ended Sep 20, 2026: you paid for a new 12-volt battery at Valley Honda", with **Undo**
- **What it's been used for:** each warranty lists claims made under it ("Used Sep 20, 2026 at Valley Honda"), each with **Undo**.

### When a later visit replaces a covered part
- **When it asks:** a confirmed visit after the warranty started (not its own visit, and not one marked "Done, no receipt") replaced one of the services it covers, while it was in force on that day by date and by miles.
- **The question:** "Valley Honda replaced the 12-volt battery on Sep 20. Costco's warranty covered it until Mar 1, 2028."
  - **Done under the warranty:** the warranty carries on (a replacement under warranty usually keeps the rest of the term), and the visit is listed as used.
  - **Paid for it:** the warranty ends that day, since the part it covered is gone.
  - Both have **Undo**.
  - If several visits qualify, the earliest unanswered one is asked about first.
- **What never asks:** inspections, and procedures like rotations or alignments. For those, a lifetime-rotation warranty shows as a note on the visit instead, never a question. "Other repair" never asks either; it's too vague to match.
- **Whole-car warranties** never ask, since their parts aren't listed.
- **Where it's asked:**
  - **The car's page**, on the warranty
  - **The service's page:** a **Warranties** block with the question about that visit ("Was this under the warranty?"), answers coming back to it, plus "Came with this visit" and **Add a warranty**.
  - **A receipt's review, before you confirm:** a note on each line that replaces something under warranty: "The 12-volt battery was under Costco's warranty until Mar 1, 2028." Confirming it then raises the question.

### Before the work
- **Shop recommendations:** an open recommendation for a part under a warranty in force says "Under warranty: Costco, until Mar 1, 2028".
- **The sheet for the shop:**
  - a new **Under warranty** block, after the car's facts: every warranty in force, whole-car ones first, with who honours each and until when
  - the same "Under warranty" note on Due now and Recommended rows that touch a covered part
  - still no prices

### Warnings before one ends
- **When:** 60 days before it ends by date, or before it reaches its miles at the rate you drive. Lifetime warranties never warn.
- **On the car's page:** the ending mark and words in its section.
- **The weekly email:** a "Warranties ending" list per car, in text and HTML.
- **A push, once per warranty:**
  - one: "Outback: warranty ending", saying "Powertrain (Subaru): ends in 45 days, Nov 23", which opens `#warranties`
  - with other news: "1 warranty ending" in the counts
  - It's keyed `{car}:warranty:{id}:{end}`, so a changed end date warns again.
- **The car's alerts switch:** these don't wait for it. They're dates you confirmed, as inspections are.
- **The garage card:** "1 warranty ending" in its tally.

### Download your data
`warranties.csv` gets one row per warranty:
- car, name, who honours it, what it covers
- starts, miles then, months, miles, ends on, ends at
- now (in force, ending, or ended, and why)
- where from (a receipt, a visit, or yours)
- used on (each claim), and details

The README's file list says what's in it.

### Not included
- warranty end dates in the calendar file
- photos or scans of a warranty certificate (Details takes contract numbers)
- AMG suggesting a car's factory terms: they vary by make and year, so you type them from the booklet

## Code

### Commit 1: `feat(warranties): keep part, repair and car warranties, read from receipts or typed in`
- **New `migrations/0018_warranties.sql`:**
  - **`warranties` table:**
    - `id`, `vehicle_id` (CASCADE)
    - `receipt_id` (→ receipts, CASCADE; set when read from one), and `phrase`, its normalised wording, `UNIQUE (receipt_id, phrase)`. A save keeps the same row, and its answers.
    - `service_event_id` (→ service_events, SET NULL): the visit it came with
    - `title` (`CHECK <> ''`), `provider`, `details`
    - `starts_on`, `start_miles`
    - `months`, `miles` (each `NULL` or `> 0`; both NULL means lifetime), `whole_car`
    - `created_at`, `updated_at`
  - **`warranty_covers` table:** `warranty_id` (CASCADE), `service_type_id` (RESTRICT); primary key on both
  - **`warranty_answers` table:** `warranty_id` (CASCADE), `event_id` (→ service_events, CASCADE), `answer` (`claimed` or `paid`), `created_at`; primary key `(warranty_id, event_id)`
- **New `engine/warranties.py`** (pure):
  - **Types:**
    - `Warranty(id, starts_on, start_miles, months, miles, codes, whole_car, event_id)`
    - `Visit(id, day, shop, odometer, replaced)`
    - `Standing(state, ends_on, end_miles, ended_on, why, event_id)`, where state is in_force, ending or ended
  - **Functions:**
    - `ends_on`: uses `add_months` from `engine/schedule.py`
    - `end_miles(w, odometer)`: an unknown start is estimated with `Odometer.miles_on`
    - `in_force_on(w, day, miles, odometer)`
    - `to_ask(w, visits, answers) -> Visit | None`
    - `standing(w, odometer, today, visits, answers)`: "ending" uses `Odometer.day_at` for the miles end
  - `ENDING_DAYS = 60`; `other` never triggers a question.
- **New `repo/warranties.py`:**
  - **Writing your own:** `WarrantyInput`, then `create`, `update`, `delete`.
  - **From a receipt:** `sync_receipt(conn, receipt_id, vehicle_id, event_id, rows)` upserts by `(receipt_id, phrase)` and deletes the rows no longer on it. A repeated phrase gets " 2".
  - **Reading:** `get`, `for_car` (with covers and answers), `for_event` (the ones that came with a visit), and `everything` for the export.
  - **Visits:** `visits(conn, vehicle_id)`: confirmed and not attested, with the codes each replaced.
- **`repo/receipts.py`:**
  - `confirm` calls `warranties.sync_receipt`.
  - `release_event` deletes the receipt's warranties, since the receipt goes back to be checked.
- **The reader, `ingest/receipts.py`:**
  - `ReceiptWarranty(description, provider, months, miles, lifetime, service_codes)`, and `ReceiptExtraction.warranties` (required)
  - `WARRANTY_RULES`, a prompt paragraph shared with commit 3, which replaces "warranty boilerplate" in the lines rule
  - `checks()` drops unknown codes from warranties too.
  - The one place that loads a stored extraction (`routes_receipts._review`) gives old ones `warranties: []`.
- **`ingest/drafts.py`:**
  - `Draft.warranties`: `{description, provider, months, miles, lifetime, codes, found}`
  - `from_extraction`: when Claude names no services, it uses the ones the visit's lines replaced or performed.
- **The review editor:**
  - **`line_editor.py`:** `clean_warranties`, `parse_warranties` and `warranties_from_draft`
  - **`_line_editor.html`:** a `warranties()` macro
  - **`app.js`:** `receiptEditor` gets `warranties`, `addWarranty`, `removeWarranty` and `serializedWarranties`; `found` rows are dashed until touched.
  - **`receipt.html`:** the block and the `warranties_json` field
  - **`routes_receipts.save` and `_read`:** parse the block. Saving drops `found` marks.
- **New `web/warranties.py`** (words and forms):
  - `Row`, `Section(in_force, ended, found)`, and `load(conn, car, state)`
  - **The words:**
    - `terms`: "3 years or 36,000 mi, whichever comes first" or "Lifetime"
    - `until`, `ending` and `ended`
  - `parse(form)` for your own, and `covering(section, codes)` for the notes in commit 2
- **New `web/routes_warranties.py`** (registered in `app.py`):
  - GET `/vehicles/{id}/warranties/new` (`?service=` fills it from a visit)
  - POST `/vehicles/{id}/warranties`
  - GET and POST `/warranties/{id}/edit`, POST `/warranties/{id}/delete`. A receipt's warranty redirects to its receipt.
- **Templates:**
  - **New `warranty_form.html`:** the chips use `lineEditor` through a small `warrantyCovers` component in `app.js`.
  - **New `_warranties.html`:** `warranty_row` and `ended_row` macros
  - **`vehicle.html`:** the section
- **`routes_vehicles.car_page`:** passes `warranties=warranty_words.load(...)`.
- **`app.css`:** `.warranties` and `.warranty__*`, reusing the issue row's look
- **`reports/export.py`:** `warranties.csv`, plus the README and docstring lines

### Commit 2: `feat(warranties): ask when a later visit replaces a covered part, and show them before the work`
- **The answers:**
  - **`repo/warranties.py`:** `answer(conn, warranty_id, event_id, answer)` and `unanswer`
  - **Routes:** POST `/warranties/{id}/answer` takes `event_id`, an answer and an optional `back=service`; it accepts only the car's visits, and only when that visit is the one being asked about. POST `/warranties/{id}/unanswer`.
- **The question and claims:** in `web/warranties.Row`, the `_warranties.html` `ask` macro, and the car page row.
- **`service.html` and `routes_services.service_page`:**
  - a Warranties block from `warranty_words.for_service(conn, event)`: came with it, asked, answered, and the procedure notes
  - **Add a warranty** for hand-logged visits; a receipt's visit says "Add one on the receipt" instead.
- **`receipt.html` and `_review`:** the "was under warranty" notes, from `covering()` against the draft's date and replaced codes, leaving out this receipt's own warranties.
- **Recommendations:** the car page's rows in `vehicle.html` get the "Under warranty" note.
- **The sheet for the shop:**
  - **`shop_sheet.py`:** `Sheet.warranties`, and a `warranty` note on its `due` and `recommended` rows. Due rows match through `state.items[item_id]["codes"]`.
  - **`for_the_shop.html`:** the block and the notes
  - **`app.css`:** the sheet's block

### Commit 3: `feat(warranties): look through older receipts for warranties`
- **New `migrations/0019_warranty_looks.sql`:** `warranty_looks` table with `receipt_id` (primary key, CASCADE), `job_id`, `status` (queued, looking, done or failed), `found`, `error`, the usage columns as on receipts, and `looked_at`.
- **New `ingest/warranties.py`:** `look(path, lines, types) -> (list[ReceiptWarranty], Usage)`
  - **The request:** vision pages like `read_receipt`, plus the confirmed lines as text, with a system prompt built from `WARRANTY_RULES` and the catalogue.
  - **The call:** `claude.parse` at low effort.
- **`ingest/background.py`:**
  - `LOOK_JOB`, `look_for_warranties(conn, receipt_ids)`, and a `run` branch
  - `look_one`: adds new finds (by phrase) to the receipt's `draft_json` with `found: true`, and marks the look done or failed.
- **New `repo/warranty_looks.py`:**
  - `waiting(conn)`: confirmed receipts whose extraction has no `warranties` and no finished look
  - `estimate(conn, ids)`: from each receipt's own token counts and `claude.PRICES`, with a per-page fallback
  - `queue`, `claim_next`, `mark_done`, `mark_failed`, `progress`
  - `to_check(conn, vehicle_id=None)`: receipts with `found` rows
- **The Receipts page:**
  - **`routes_receipts`:** POST `/receipts/look-for-warranties`, and **Try again** re-queues failed looks; **Carry on looking** reuses `/jobs/{id}/carry-on`.
  - **`_inbox`:** passes the section.
  - **`receipts.html`:** the section, polling with htmx while it runs, as uploads do.
- **The receipt's review:** the "Found Oct 9" notice.
- **The car's Warranties section:** "Found on N receipts: check them".

### Commit 4: `feat(warranties): warn before a warranty ends`
- **`alerts/watch.py`:**
  - `look()` adds a `warranty` notice for each warranty ending soon, keyed `{car}:warranty:{id}:{end}` at level due, whatever the alerts switch says.
  - `push()` gets the single-warranty wording and "N warranties ending" in the counts.
  - `CarWatch.warranties` lists them.
- **`alerts/mail.py` and `email/digest.html`:** the "Warranties ending" list.
- **The garage:** `routes_garage` and `garage.html` get "N warranties ending".

## Tests
- **`tests/amg/engine/test_warranties.py`:**
  - **When it ends:** the end date from months, including across month ends; the end miles from a known start and from an estimated one.
  - **In force on a day:** by date, by miles, and lifetime.
  - **Ending:** at 61 days not ending, at 60 ending; by miles at the rate driven.
  - **Asking:**
    - asks about a later visit that replaced a covered part
    - never about its own visit, the same day, an inspection or a procedure, `other`, or a visit after it ended
    - the earliest unanswered first
    - claimed keeps it in force; paid ends it that day; whole-car warranties never ask
- **`tests/amg/repo/test_warranties_repo.py`:**
  - create, update and delete, with covers
  - `sync_receipt`:
    - inserts, updates in place and keeps answers
    - deletes what's gone
    - repeated phrases
    - moving the receipt to another car
  - releasing a receipt's service deletes its warranties
  - deleting the visit it came with keeps it; deleting an answered visit drops the answer
  - `visits` leaves out attested and unconfirmed services
- **`tests/amg/ingest/test_receipts.py`:**
  - the schema has warranties, and unknown codes are dropped
  - an empty services list is filled from the visit's lines
  - an old extraction without warranties still loads
- **`tests/amg/web/test_warranty_pages.py`:**
  - the empty section
  - adding the whole car from the in-service date, and a part warranty with chips
  - the form's errors (no name, no length, no covers, a bad date)
  - edit and delete; a receipt's warranty sends you to the receipt
  - the receipt review's block: saved, errors, confirm writes rows, saving again keeps answers
  - the question on the car page and the service page: done under the warranty, paid for it (ended words), undo
  - a stale answer refused
  - the "was under warranty" note on a review
  - the recommendation note
  - the sheet's block and notes, with no dollar amounts
  - ending words on the page
- **`tests/amg/ingest/test_background.py`**, with `claude.parse` replaced:
  - looking puts dashed finds in the draft and they don't count until saved
  - no duplicates by phrase
  - a failure, then **Try again**
  - the estimate, and the Receipts page section's states
  - only receipts read before warranties are offered
- **New `tests/amg/alerts/test_warranty_alerts.py`:**
  - the warranty notice once, and again for a new end
  - not held back by the alerts switch
  - push titles, single and in counts
  - the email's list in text and HTML
  - the garage count
- **`tests/amg/reports/test_export.py`:** `warranties.csv`
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 5: `docs: Phase 14, warranties`)
- **`docs/ROADMAP.md`:** **Phase 14 — Warranties**, in the usual shape:
  - For, the checklist (ticked), Data owned, Can go wrong, Tests pin, Done when
  - **Decisions:**
    - AMG asks, it doesn't decide
    - paid ends it because the part is gone
    - procedures and "Other repair" never ask
    - finds on older receipts count only once saved
    - warnings don't wait for the alerts switch
    - no factory terms from memory
  - The Decisions table's "Line kinds" row gets a note that a bought warranty is also kept as a warranty.
- **The plan:** saved verbatim to `docs/plans/2026-10-09-warranties.md` with the header, plus an index row.

## Verification
- **Tests** pass after every commit.
- **The scratch garage** (`scratchpad/p11`, made-up data, no Claude calls):
  - a receipt draft with a warranty row, confirmed
  - a later hand-logged visit replacing the battery, so the service page asks; **Paid for it**, then **Undo** and **Done under the warranty**
  - a whole-car warranty from the in-service date, set to end within 60 days
  - a seeded "found" warranty and finished look, for the Receipts page section and the dashed rows
  - the sheet's block
  - `python -m amg.cli alerts --dry-run` showing the warranty push and email lines
- **Layout:** the section, the form, the review block, the service block and the sheet, at 360px and on the desktop, in light and dark.
- **Done when (yours), after you deploy:**
  - run **Look for warranties** once and check what it finds
  - add each car's factory warranties from its booklet
  - the next receipt with a warranty is read with it
  - an ending warranty arrives as a push and in Monday's email
