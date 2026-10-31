> **Approved** 2026-10-07 06:56 · **Roadmap** [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `79f2e23` feat(schedule): wiper blades count from today where none are on record, and the docs commit that adds this record
>
> **As built:** As planned. The schedule page words a 12-month interval "every 1 year", so the item reads "every 1 year, counting from" the deploy day. The second test is named `test_wiper_blades_on_record_is_what_already_counts_for_the_item`; it also checks that an inspection of the blades doesn't count for a replacement item. The roadmap's decision that a count-from date is one you set now names this migration as the one exception.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Wiper blades count from the day you deploy, on cars with none on record

## Context
You asked for wiper blades to get a count-from date too, like the one you'll give washer fluid. Few people keep receipts for wiper blades, so on a car with none on record the wiper item counts every change since new as missed, and shows as overdue.

You can already set the date yourself in the schedule editor. You asked me to do it. Your schedules are in the server's database, which I don't touch, so a one-off migration sets it the next time you deploy. You chose to limit it to cars with no wiper-blade replacement on record. A car that has one keeps counting from it, so its next due stays right.

## How it behaves for you
- **On your next `bash scripts/deploy.sh`,** the app migrates as it starts. Each wiper-blade schedule item gets a **Count from** date of that day, unless:
  - **the car has a wiper-blade replacement on record** (a confirmed service). Nothing changes on that car.
  - **the item already has a date,** for example one you set before deploying. It's kept.
  - **the item is a one-off.** Only a repeating item can count from a date.
- **What counts as on record** is what already counts for the item: a confirmed service that replaces the blades. If the item is an inspection, any wiper-blade line or a multipoint or state inspection also counts, as it does now. A receipt you haven't confirmed doesn't count.
- **What you'll see:**
  - the schedule page: "every 12 months, counting from" the deploy day
  - next due: one interval after that day
  - the garage's missed count and the car's "missed in the past" list both drop by that car's missed wiper changes. Unlike washer fluid, these numbers do change.
  - wiper reminders stop until the new due date
- **Afterwards,** the date is an ordinary count-from date: change or clear it in the editor. Cars and schedules you add later get no date unless you set one.

## Code (one commit)
- **New: `src/amg/migrations/0012_wiper_blades_count_from.sql`.** One `UPDATE schedule_items` that:
  - sets `counts_from = date('now', 'localtime')`, the deploy day. It uses the server clock, as the app's own "today" (`date.today()`) does, so the date is never in the app's future.
  - sets `updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`, the format of `db.now_iso()`
  - applies only where:
    - `counts_from IS NULL`
    - the item has an interval
    - the item covers `wiper_blades`, through `schedule_item_services` and `service_types`
    - no confirmed service for that car meets the item. This is the rule of `meets()` in `src/amg/engine/schedule.py`, written in SQL: a line covers one of the item's services, by replacing or performing it, or by anything at all if the item is an inspection. For an inspection item, a multipoint or state inspection also counts.
  - A comment explains why, in the style of `0010_washer_fluid.sql`.
- **No Python changes.** The engine, editor, schedule page, export and alerts already read `counts_from` (migration 0011).

## Tests (`tests/amg/test_db.py`)
Both tests start from a database at version 11, using the existing `_at(tmp_path, 11)`, and make cars and items with the repos: `vehicles.create`, `schedules.create_draft` / `confirm`, `services.create_event`.
- **`test_wiper_blades_count_from_today_where_none_are_on_record`:**
  - a car with nothing on record: its wiper item gets `date.today()`, its oil item stays NULL, and a wiper item already dated 2026-01-01 keeps that date
  - a car with a confirmed wiper replacement: its item stays NULL
  - a car whose wiper replacement is only on an unconfirmed receipt: its item gets today's date
- **`test_a_wiper_inspection_met_by_a_multipoint_keeps_its_count`:** on a car with a confirmed multipoint inspection, an "inspect wiper blades" item stays NULL.

## Docs (second commit)
- **`docs/ROADMAP.md`, Phase 5:**
  - "Data owned" gains: migration 0012 started wiper blades counting from the day it ran, on cars with no wiper change on record
  - the washer-fluid "Can go wrong" line notes that wiper blades were handled this way
- **The plan:** this plan, saved as `docs/plans/2026-10-07-wiper-blades-count-from.md` with its header and an index row in `docs/plans/README.md`.

Commits:
1. `feat(schedule): wiper blades count from today where none are on record`
2. `docs: wiper blades count-from migration`

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on the scratch copy (`scratchpad/p11/data`, made-up data, at version 11), which migrates to 12 when it starts:
  - for each car's wiper item, check that it counts from today if the car has no wiper change on record, and is unchanged if it has one
  - check the schedule page wording, and that the garage missed count drops only by the wiper misses
- **Done when (yours), after you deploy:**
  - each car with no wiper record shows "counting from" the deploy day on its wiper item
  - cars with a wiper record are unchanged
  - then add washer fluid as before
