> **Approved** 2026-10-25 12:59 · **Roadmap** [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `4c18760` feat(services): tag a line from the car's schedule, `ebb6000` feat(services): say what a service counted for on the schedule, `781ed99` feat(schedule): mark as done with a service you logged, `a561830` fix(services): point to a same-day "Done, no receipt", and a shorter menu, `4735345` fix(services): say beneath the menu which jobs a line was tagged for, and the docs commits that adds this record
>
> **As built:** As planned, except:
> - **A same-day "Done, no receipt" is pointed to as well** (`a561830`). In the browser check, a job marked done with no receipt on the day of the logged service counted instead of it, and the service's page only said another service had counted. It now points to that entry there too: "Open that one to delete it, and this one counts."
> - **The line says what the menu tagged it for** (`4735345`, after you used it on the Elantra). Picking a job showed nothing near the menu: it went back to its prompt, and the chips appeared above the text box, so it looked as if nothing had been chosen, though saving linked the service. Beneath the menu the line now says "✓ Tagged for Engine oil and filter" while that job's chips are on it, and a line tagged from Mark as done arrives saying so too. It's shown with a bound `hidden` attribute: `x-show` there lagged one change behind.
> - **The menu's first option reads "From the schedule…"** (`a561830`), without the car's name, which a phone cut off. The name stays in the menu's label for screen readers.
> - **A car with neither an in-service nor a "got it" date** counts from its first record, so its first service can't count. The service's page says so and how to fix it, one of the reasons a matching service didn't count.
> - **`status.engine_car`** was added so those reasons see the car as the engine does.
> - **Checked in the browser** on a newly seeded scratch car, with made-up data and no Claude calls, that reproduced the problem: an untagged oil change you did yourself left the oil overdue.
>   - Picking the job from the menu tagged the line, and saving made it count.
>   - Mark as done on the tire rotation offered a receipt, whose review opened with its line tagged.
>   - **Log a service for it** opened with the line tagged.
>   - The duplicate was pointed to.
>   - At 360px (no sideways scroll), on the desktop and in dark mode.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Tie a logged service to the schedule job it did

## Context
You logged a service on the Elantra GT Sport that you did yourself, but the job it was for stayed due. **Mark as done** then added a separate "Done, no receipt" entry that doesn't point at the service you logged.

**Why it happens:** the gap engine (`engine/schedule.py`, `meets`) counts a service for a job only when one of the service's lines is tagged under **Services covered** with one of that job's service types. A replacement or procedure job also needs the line to say it was replaced or done, not only inspected. A line with a description and an amount but no tags counts for nothing, and nothing on the form or the service page says so. **Mark as done** (`routes_schedules.attest`) always creates a new `attested` service, with no way to choose one you already logged.

You chose three of the four fixes. The fourth (stopping the save when tag text was typed but never picked from the list, and warning on untagged lines) is left out.
- **Pick from the schedule:** each line can be tagged from a list of this car's jobs.
- **Mark as done offers your services:** choosing one opens it with the job filled in, for you to check and save.
- **Say what it counted for:** each service's page lists the jobs it counted for, or says it counts for none and how to fix that.

There's no migration and no new dependency. The service types stay the link between a service and a job, the same way receipts read by Claude are matched today.

## How it behaves for you

### Pick from the schedule
- **Where it shows:** under **Services covered** on each line of **Log a service** and **Edit service**, and on a receipt's review. It's a menu, **From the Elantra GT Sport's schedule…**, listing the jobs that apply to the car (normal or severe):
  - first those overdue or due soon, with when ("Engine oil and filter · 1,200 mi overdue")
  - then the rest, in schedule order
- **What picking a job does:** it adds that job's service types to the line as chips, the same chips typing adds.
  - A replacement or procedure job records its own action ("replaced" or "done"), even where a service type's default is "inspected". So the line always meets the job.
  - An inspection job on a line with no tags ticks **Inspected only**.
  - It names the line after the job if the line has no description yet.
- **Chips stay editable:** you can still remove a chip or type more.
- **No schedule:** a car without one shows no menu.

### Mark as done offers your services
**Mark as done** on an overdue job, **It was done** on a missed one, and the chart's marks all lead to the same page. It now offers three ways out:
1. **Was it a service you logged?** Up to five of the car's services that don't already count for this job:
   - not "Done, no receipt" ones, and none on or before the job's count-from date
   - picked as the five dated closest to when the job fell due, then listed newest first
   - each shown as "Oct 20, 2026 · Your own work · Oil change, Wiper blades", with **Tag it for this job**

   **Tag it for this job** opens that service's **Edit service** form, or its receipt's review for a service from a receipt. The job is already applied to the service's first untagged line, or to a new line if every line is tagged. A notice says "Tagged for Engine oil and filter: check the line, then save." Nothing changes until you save.
2. **Not logged yet? Log a service for it:** opens **Log a service** with a line already tagged for the job, for the date, odometer and cost.
3. **Done with no receipt:** the existing form, as before.

### Say what it counted for
A confirmed service's page gets an **On the schedule** section (shown when the car has a schedule):
- **Counts for:** each job it met, with when that job was due, e.g. "Engine oil and filter: was due at 37,500 mi · Oct 3" ("late" when it was).
- **Matches but doesn't count**, with the reason: before the job's count-from date; before the car's start; or another service had already counted for it (a second service the same day, or a one-off job already done).
- **Counts for nothing:** "This doesn't count for anything on the Elantra GT Sport's schedule. Tag its lines with the services they covered", with **Edit service** (or **Check the receipt**).
- **A likely duplicate:** where a "Done, no receipt" entry meets the same job within 30 days of this service: "You also marked it done with no receipt on Oct 24. Open it to delete it." That's your Elantra's case now.

### Not included
- **Stopping the save on untyped tags and warning on untagged lines:** not chosen.
- **Tagging in one tap from Mark as done:** you chose to see the change first.
- **Suggesting tags from a manual line's description:** receipts' learned phrases aren't applied to typed lines.
- **A stored link between a service and a job:** the service types already link them.

## Code

### Commit 1: `feat(services): tag a line from the car's schedule`
- **`web/status.py`:**
  - `CarStatus` keeps the engine's `services: list[Service]`, already built in `load`.
  - New `picks(state) -> list[dict]`: the in-effect items as `{id, name, codes, action, when}`. Overdue and due soon come first, ordered as `next_up` orders them and worded with `when()`. The rest follow in schedule order.
- **`web/line_editor.py`:** a line row gains `actions: {code: action}` (only actions other than inspect).
  - `blank_line` and `clean_lines` carry it, filtered to `services.ACTIONS` and known codes.
  - `parse_lines`: inspect if `inspect_only`, else `actions.get(code)`, else the type's default.
  - `rows_from_draft` fills it from the saved covers. Editing a line read as "replaced" on a type whose default is "inspected" no longer turns it into "inspected" on save; that was an existing lossy round-trip.
- **`static/app.js`:**
  - `withId` copies `actions`.
  - `unpick` drops the code's action.
  - `lineEditor` takes `editor.schedule` (default `[]`).
  - New `fromSchedule(row, id)` applies a job as described above.
- **`_line_editor.html` (`lines` macro):** the **From … schedule** select under the chips, `x-show="schedule.length"`, labelled with the car's name.
- **Callers:**
  - `routes_services._form` passes `schedule=status.picks(status.load(conn, car))`.
  - `routes_receipts._review` passes the same for the receipt's car, when it has one.

### Commit 2: `feat(services): say what a service counted for on the schedule`
- **New `web/schedule_links.py`**, words and loading like `web/follow_ups.py`:
  - `counted_for(conn, car, event) -> Counted | None`. It reads `status.load`: done occurrences whose `service.id` is this event, and in-effect items the event `meets` (from `engine/schedule.py`) that it didn't count for, with the reason.
  - The duplicate check: `attested` services in `CarStatus.services` meeting a counted job, within 30 days.
- **`routes_services.service_page`** passes `schedule=schedule_links.counted_for(...)` for confirmed services.
- **`service.html`:** the **On the schedule** section.

### Commit 3: `feat(schedule): mark as done with a service you logged`
- **`web/schedule_links.py`:**
  - `candidates(conn, car, item, near: date) -> list[dict]`: confirmed, non-attested services that don't meet the item and are after its `counts_from`. The five nearest `near`, newest first, each with words and its link: `/services/{id}/edit?item=` or `/receipts/{rid}?item=`.
  - `apply_item(rows, item) -> list[dict]`: the job on the first untagged row, else a new row.
- **`routes_schedules.attest_form`:**
  - `near` is the `due` param, else the item's current occurrence's due day, else today.
  - It passes the candidates and the **Log a service** link (`/vehicles/{id}/services/new?item=`).
- **`attest.html`:** the three ways out; the existing form becomes the third.
- **`?item=` support:**
  - on `routes_services.new_service` and `edit_service`
  - on `routes_receipts.review`, threaded into `_review` after the rows are built
  - In each, an item of another car, or one not in effect, is ignored. A notice names the job.

## Tests
- **New `tests/amg/web/test_schedule_links.py`, with the hand-checked `schedule_fixtures.steady_car`:**
  - `parse_lines` keeps a line's own action, `inspect_only` still wins, and `rows_from_draft` round-trips a non-default action.
  - `picks`: due ones first, then schedule order, and a severe-only item left out on a normal car.
  - The service form shows the menu with the car's jobs. A car with no schedule shows none.
  - A service posted with a line tagged from a job (covers plus actions) meets it: the job moves to later. A replace job on a default-inspect type is met too.
  - **The service page:**
    - counts for, with the due words
    - an untagged service counts for nothing, with the Edit link
    - before a count-from date, with that reason
    - the nearby "Done, no receipt" pointed to
    - an unconfirmed service has no section
  - **The Mark as done page:**
    - it lists the nearest logged services, newest first
    - it leaves out "Done, no receipt" entries, other cars' services, ones already counting, and ones before the count-from date
    - it links to the edit form, or to the receipt review for a receipt
    - it has the Log a service link
  - `?item=` on edit applies to the first untagged line and keeps its description. It adds a line when all are tagged, ignores another car's item, works on the new-service form, and works on the receipt review.
- **Existing tests:** the mark-as-done tests in `test_car_status_pages.py` keep passing; the "Done, no receipt" form is unchanged.
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 4: `docs: tie a logged service to the schedule job it did`)
- **`docs/ROADMAP.md`, Phase 5:** three items "(added after the phase shipped, 2026-10-25)", for picking from the schedule, Mark as done with a service you logged, and what a service counted for. A **Can go wrong** line: an untagged line counts for nothing, and the service page now says so.
- **The plan:** saved verbatim to `docs/plans/2026-10-25-services-to-schedule-jobs.md` with the header, plus an index row. The As built note and its commits are added when it ships.

## Can go wrong
- **Changing a receipt's car after the menu was built:** the menu still lists the first car's jobs. The tags are still true of the work, since service types aren't per car.
- **A service that matches but doesn't count** (before a count-from date, such as wiper blades' from migration 0012): the service page now says why.
- **Two services for one job the same day:** only one counts. The page says the other didn't, and why.

## Verification
- **Tests:** `pytest` after every commit.
- **The scratch garage** (`scratchpad/p11`, made-up cars, `ANTHROPIC_API_KEY=""`):
  1. Log a service with an untagged line: its page says it counts for nothing.
  2. Edit it and pick the overdue job from the menu: the chips appear. Save: the page says what it counted for, and next up moves on.
  3. On another overdue job, **Mark as done**: the list shows that car's logged services. **Tag it for this job** opens the edit form with the job applied.
  4. **Log a service for it**: the form opens with the line tagged.
  5. A receipt's review shows the menu.
  6. The page at 360px, on the desktop, and in dark mode.
- **After you deploy (yours):**
  1. On the Elantra, open the service you logged, **Edit service**, and pick the job from the menu (or **Mark as done → Tag it for this job**). Save.
  2. Delete the "Done, no receipt" entry: the service page points to it.
  3. Next up then counts from your service.
