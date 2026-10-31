> **Approved** 2026-10-07 22:22 · **Roadmap** [Phase 11](../ROADMAP.md#phase-11--recommendations-recalls-and-readings)
>
> **Built in** `be7508a` feat(alerts): ask for an odometer reading when the last is old, `8eef96e` feat(receipts): follow up on shop recommendations, `f664ad7` feat(recalls): check NHTSA for recalls, `231104a` fix(recalls): one garage line however many recalls a car has, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The garage card** shows a car's recalls in one line, by name when there's one and "Recalls 4 open" when there are more, not a line each. Real model years carry several, often for the same part (`231104a`).
> - **`vehicles` gained a fourth column,** `recalls_listed`: NHTSA's model names, kept so the page can list them when the car's model matches none.
> - **Recall pushes** go at priority 4, and 5 when NHTSA says not to drive or to park outside.
> - **The weekly email** lists recommendations for a car with alerts on even when it has no schedule.
> - **On the car page,** the reading notice gives way to the existing "due by mileage alone" one when that shows, since both ask for a reading. The Recalls section sits above Shop recommendations.
> - **Prices:** quoted prices show to the cent; the section's total is in whole dollars, like the budget.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Shop recommendations, recalls and odometer readings

## Context
You picked three of my ideas for AMG to keep track of:
1. **Shop recommendations.** Receipts already record work the shop recommended that wasn't done ("rear pads at 3 mm"). Today they only help price jobs in the budget, and nothing reminds you of them.
2. **Recalls.** AMG never checks for recalls, though NHTSA (the agency whose VIN lookup AMG already uses) lists them free, with no key needed.
3. **Odometer readings.** Mileage due dates come from readings, and AMG never asks for one when they stop coming.

They ship as one step, a new roadmap Phase 11, in three feature commits and a docs commit.

## How it behaves for you

### 1. Shop recommendations
- **On the car's page,** a new **Shop recommendations** section lists each open one from your confirmed receipts, newest first. Each shows:
  - what was recommended, the date and the shop
  - the quoted price, if there was one
  - its services, as chips like the history's
- The section heading gives the total quoted for the open ones. They aren't added to the budget.
- **One closes by itself** when a later confirmed service does the work: it covers one of the recommendation's services by replacing or doing it. An inspection only closes a recommendation for a service you'd normally just inspect, such as a multipoint inspection. A service on the same visit, or before it, doesn't count.
- **Two buttons on each:**
  - **Log it** opens the new-service form with a line already filled in (the description and services). Saving it closes the recommendation, even one with no services.
  - **Not doing it** closes it in one click. Closed ones fold under "N not doing" with an **Undo**.
- **Old ones:** open recommendations over 12 months old fold under "N older". Older receipts won't bury the recent ones, and you can clear them with "Not doing it".
- **The weekly email** lists each car's open recommendations from the last 12 months. That only applies to cars with alerts on, since old receipts may still be going in. There are no pushes: you saw the recommendation when you confirmed the receipt.
- **Garage card:** a count, such as "2 recommended", alongside overdue, due soon and missed.
- **If you edit a recommendation's wording** on its receipt, a "Not doing it" on it is lost and it reopens. Closes from a later service aren't affected.

### 2. Recalls
- **The check:**
  - **What's sent:** the car's year, make and model, never the VIN. NHTSA lists recalls by model year, not by car.
  - **When:**
    - the daily alerts run checks each car (not archived) once a week
    - a **Check now** button on the car page checks it straight away
  - **Model names:** AMG first asks NHTSA which models of that year and make have recalls, then matches the car's model. "Outback Limited" matches NHTSA's "OUTBACK". If nothing matches, the page lists NHTSA's model names, so you can spot a naming difference.
- **On the car's page,** a new **Recalls** section. Each open recall shows:
  - the component and NHTSA's campaign number
  - the date NHTSA got the report
  - the summary, with "what can happen" and "the fix" folded under it
  - for a recall NHTSA says not to drive, a warning at the top: "NHTSA says not to drive it until this is fixed" (or "…to park it outside", where that's NHTSA's advice)
- The page also says not every recall fits every car, since some cover only cars built on certain dates. To check your VIN, ask a dealer or use nhtsa.gov/recalls.
- **Three buttons on each:**
  - **It's been done:** a date, and optionally which service it was. AMG offers the car's services since the recall that have a "Recall or service campaign" line.
  - **Not my car:** for one that doesn't apply.
  - **Undo,** on closed ones, which fold under the open ones.
- The section ends with "Checked Oct 7: NHTSA lists 4 for 2016 Subaru Outbacks". If NHTSA couldn't be reached, it says so, and the next run tries again.
- **Alerts:**
  - **A push for each recall the first time AMG finds it,** whether or not the car's alerts are on, as inspection dates already work. A recall comes from NHTSA, not your receipts, so it isn't wrong while old receipts are still going in.
  - **All recalls found in one check go in a single push.** So the first check sends one push per car, say "Outback: 4 recalls to check". A recall NHTSA says not to drive is sent at high priority.
  - **The weekly email** lists each car's open recalls and puts the count in its subject, as in "AMG: 1 overdue, 2 open recalls".
  - **The garage card** shows each open recall, as it shows inspection dates.
- **When the list changes:** if NHTSA stops listing an open recall you haven't touched, for example after you correct the car's model, AMG drops it.

### 3. Odometer readings
- **When a reading is wanted:** the car's latest reading is over 60 days old, and its schedule has an item due by mileage. Every service, fill-up and charge with an odometer counts as a reading.
- **On the car's page,** under Next up: "The last odometer reading was Jun 2, 4 months ago, so mileage due dates are guesses. Add a reading". The link opens the reading form, which is already on the page.
- **Cars with alerts on** also get:
  - **a push,** once each time readings stop coming: "Outback: odometer reading wanted. The last was Jun 2, 4 months ago; AMG's guess is ~52,300 mi." Tapping it opens the reading form. A new reading starts the 60 days again.
  - **a line in the weekly email** with the same link
- **Turning a car's alerts on** doesn't hold the reading push back, unlike due jobs, because a reading is something you can do right away.

## Code

### Commit 1: `feat(alerts): ask for an odometer reading when the last is old`
- **`src/amg/web/status.py`:** `READING_DAYS = 60` and `stale_reading(state) -> Stale | None`. It returns the last reading's date, how long ago that was, and today's estimate. It's `None` when the car has no item due by mileage or the reading is recent.
- **`src/amg/alerts/watch.py`:**
  - `Watched` gets a `kind` ("job", "renewal", "recall" or "reading"). The existing `renewal` flag becomes a property, so existing callers still work.
  - `CarWatch.notices` holds the recalls and the reading request, kept apart from `jobs` so they don't enter the overdue and due-soon counts.
  - The reading request's round is `"{car}:reading:{last read_on}"`, or `"{car}:reading:none"` when the car has no reading.
  - `news()` covers jobs and notices. `push()` titles each kind and links the reading request to `#add-reading`.
  - `take_stock()` holds back schedule jobs only.
- **`src/amg/alerts/mail.py` and `templates/email/digest.html`:** the "Odometer" line for each car.
- **`src/amg/alerts/run.py`:** pushes cover `jobs + notices`. Nothing else changes.
- **`src/amg/web/routes_vehicles.py` and `templates/vehicle.html`:**
  - the notice under Next up
  - `adding` in the odometer section also starts true when the address ends `#add-reading`

### Commit 2: `feat(receipts): follow up on shop recommendations`
- **New `src/amg/migrations/0013_recommendations.sql`:** the `recommendation_outcomes` table:
  - `receipt_id`, `phrase`: the recommendation's wording, normalised by `drafts.phrase()`
  - `outcome`: done or skipped
  - `service_event_id`, for one logged with **Log it**
  - `created_at`
  - `UNIQUE (receipt_id, phrase)`
- **New `src/amg/engine/follow_ups.py` (pure):** `open(recs, services, default_actions)`. It decides which are still open by the rule above, and adds the outcome of each one that's closed.
- **New `src/amg/repo/follow_ups.py`:**
  - reads recommendations from confirmed receipts' `draft_json`, the same query `prices.quotes()` uses
  - `skip()`, `undo()` and `done()` write the outcomes
- **New `src/amg/web/follow_ups.py`:** `load(conn, car, today)` returns the open recommendations (recent and older), the skipped ones and the quoted total. The car page, the garage and the email all use it.
- **New `src/amg/web/routes_follow_ups.py`:** POST to skip a recommendation and to undo; each goes back to `#follow-ups`. It's registered in `app.py`.
- **`src/amg/web/routes_services.py`:** `new_service` reads `?receipt=&rec=` and fills the first line, using each service's default action. Two hidden fields carry them through. `create_service` records the outcome `done` with the new service's id.
- **Templates:**
  - `vehicle.html`: the section
  - `garage.html` and `routes_garage.py`: the count
  - `email/digest.html` and `mail.text()`: the email lines
- **`src/amg/reports/export.py`:** `recommendations.csv` with car, date, shop, recommendation, services, quoted and state (open, done on a later visit, logged, not doing). The README text gains a line.

### Commit 3: `feat(recalls): check NHTSA for recalls`
- **New `src/amg/migrations/0014_recalls.sql`:**
  - **`vehicles` gains:**
    - `recalls_checked_on`
    - `recalls_model`, NHTSA's model name it matched, or `''` for none
    - `recalls_error`
  - **A new `recalls` table:**
    - `vehicle_id` and `campaign`, with `UNIQUE (vehicle_id, campaign)`
    - `reported_on`, `component`, `summary`, `consequence`, `remedy`
    - `park_it`, `park_outside`
    - `status`: open, done or not_mine
    - `closed_on`, `service_event_id`, `note`
    - `found_at`, `updated_at`
- **New `src/amg/ingest/recalls.py`, in the style of `ingest/vin.py`** (urllib, a 10-second timeout, no new dependencies):
  - `models(year, make)`
  - `match(model, listed)`: exact, else the longest listed name the car's model starts with
  - `lookup(year, make, model) -> Lookup`
  - `parse()`: `ReportReceivedDate` comes as DD/MM/YYYY, such as "19/12/2019", and an unreadable date becomes `None`. An HTTP 400 is an empty list, and other failures raise `RecallLookupError`.
  - All HTTP goes through one `_get(url)`, which `tests/conftest.py`'s autouse fixture swaps for one that refuses, so no test reaches NHTSA.
- **New `src/amg/repo/recalls.py`:**
  - `due_for_check()`: cars with year, make and model, checked 7 or more days ago
  - `record(conn, car, lookup)`: adds new recalls, keeps the status of existing ones, drops open untouched ones NHTSA no longer lists, and sets the checked fields
  - `close()` and `reopen()`
  - `open_for()`
  - `cars_watched()` gains cars with an open recall
- **`src/amg/alerts/run.py`:** before watching, checks the cars that are due, one at a time. A failure is stored on the car and said in the output. It doesn't fail the run, because NHTSA being down isn't your alerts failing. A dry run doesn't check.
- **`src/amg/alerts/watch.py`:**
  - a recall's round is `"{car}:recall:{campaign}"`, at level `due`, so the alert log needs no change
  - a recall NHTSA says not to drive is pushed at priority 5
  - the email subject counts open recalls
- **New `src/amg/web/routes_recalls.py`:** Check now, done, not my car and undo. Each goes back to `#recalls`.
- **Templates:**
  - `vehicle.html`: the section
  - `garage.html`: each open recall
  - `email/digest.html` and `mail.text()`: the email lines
- **`src/amg/reports/export.py`:** `recalls.csv`.

## Tests
- **Readings:**
  - `tests/amg/web/test_status.py`: stale after 60 days; never for a car with no item due by mileage; the case with no reading at all
  - `tests/amg/alerts/test_watch.py`: pushed once; a new reading and then 60 quiet days pushes again; a car with alerts off isn't nudged; `take_stock` doesn't hold it back
  - `test_mail.py`: the line
  - `tests/amg/web/test_car_status_pages.py`: the notice and the `#add-reading` link
- **Recommendations:**
  - **`tests/amg/engine/test_follow_ups.py`:**
    - closed by a later replacement
    - not closed by a later inspection
    - closed by an inspection of a type you'd normally inspect
    - not closed by the same visit or an earlier one
    - one with no services stays open
    - outcomes win
  - **`tests/amg/repo/test_follow_ups_repo.py`:**
    - only confirmed receipts count
    - skip and undo
    - editing the wording reopens a skipped one
  - **Pages:**
    - the car page lists recent ones and folds older ones
    - Not doing it, then Undo
    - Log it fills the form, and saving closes the recommendation
    - the garage count
  - **The email and the export:** the email lists only the last 12 months; the CSV
- **Recalls:**
  - **`tests/amg/ingest/test_recalls.py`,** on a saved NHTSA response:
    - parsing, including the DD/MM/YYYY date
    - matching: exact, starts-with, and none
    - a 400 gives an empty list
    - a network error raises
  - **`tests/amg/repo/test_recalls_repo.py`:**
    - new recalls are added
    - a closed one keeps its status when checked again
    - an untouched open one that's no longer listed is dropped
    - weekly, not daily
  - **Alerts:**
    - one push per check
    - a recall NHTSA says not to drive goes at priority 5
    - pushed with the car's alerts off
    - a dry run doesn't check
    - NHTSA being down doesn't fail the run
    - the email subject and lines
  - **Pages:** Check now (with a fake lookup), It's been done with a service, Not my car, Undo, and the garage card
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 4: `docs: Phase 11, recommendations, recalls and readings`)
- **`docs/ROADMAP.md`:** a new **Phase 11 — Recommendations, recalls and readings**, in the phases' usual shape: what it's for, the data it owns, decisions, what can go wrong, what tests pin, and done when. Its checklist is ticked as each part ships.
- **The plan:** this plan, saved to `docs/plans/2026-10-07-recommendations-recalls-readings.md`, with its index row.

## Verification
- **Tests** pass after every commit.
- **A local run** on the scratch copy (`scratchpad/p11/data`, made-up data):
  - **Recommendations:** the scratch receipts have none, so add a few made-up ones to confirmed receipts in the receipt editor. Make one that a later service on record covers, and one with no services. Check the auto-closing, then Not doing it and Undo, then Log it.
  - **Recalls:** Check now against real NHTSA, which receives only the scratch cars' year, make and model. Check the 2016 Outback's list, a not-drive warning, It's been done and Not my car, and that the garage card shows open recalls.
  - **Readings:** move a car's last reading back past 60 days, and check the notice and that the link opens the form.
  - **Alerts:** `python -m amg.alerts.run --dry-run` shows the reading push and the email's new sections. A real run with pushes faked isn't needed, since tests cover it.
  - **Layout:** each new section at 360px and on the desktop, in light and dark themes.
- **Done when (yours), after you deploy:**
  - each car's page shows its recalls, checked; mark the ones already done
  - the shop recommendations look right; clear the stale ones
  - Monday's email has the new sections
  - a car with an old reading gets one push asking for a reading
