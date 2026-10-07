> **Approved** 2026-10-06 22:48 · **Roadmap** [Phase 1](../ROADMAP.md#phase-1--garage-manual-records-extraction-trial) and [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `7cc9516` feat(catalogue): washer fluid, beside wiper blades, `b97d883` feat(schedule): count an item from a date, and the docs commit that adds this record
>
> **As built:** As planned. The gap engine also ignores a date on a one-off item (the editor refuses one anyway), and setting a date doesn't mark an item "Set by you": it changes how AMG counts, not the manual's interval.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Washer fluid as a standard service, and a count-from date for schedule items

## Context
You asked whether AMG budgets and reminds for windshield wipers and washer fluid.
- **Wiper blades** are already a standard service.
- **Washer fluid** is not.

**A correction to my earlier answer.** I said you couldn't put washer fluid on a schedule. You can: Service types (footer) → add your own. A standard service is still better, because:
- it sits right after wiper blades in every picker, report and budget group
- it's offered in AMG's generic schedules
- AMG forgets the receipt wording it learned as "no service" for washer-fluid lines, so the receipt reader can suggest the new service

**The catch** is that no top-up has ever been recorded. A new washer-fluid item would count every top-up since you got the car as missed, about four a year, and would be overdue at once. You chose to fix that with an optional **Count from** date on any schedule item.

## How it behaves for you

### Washer fluid
- **A new standard service, "Washer fluid".**
  - It's in Electrical with wiper blades, listed right after them.
  - Its usual action is Replace, since a top-up adds fluid. That's how the receipt reader already treats fluids.
- **New receipts:** the reader suggests it for lines such as "Washer fluid" or "Top off washer fluid", as it does for every service on the list.
- **Wording AMG already learned:**
  - When you confirm a receipt, AMG remembers each line's wording and the services you gave it. The next receipt with the same wording gets those services instead of Claude's suggestion.
  - Washer-fluid lines were remembered with no service, because there wasn't one to give them.
  - AMG forgets only those: wording that says "fluid" plus "washer", "wiper", "windshield" or "windscreen", remembered with no service.
  - A line you did give a service keeps it, and "drain plug washer" isn't touched because it doesn't say "fluid".
- **AMG's generic schedules** gain a left-out row, "Washer fluid, every 3 months", one tap to include. Its reason: "Only if you want reminders: most cars warn when it runs low".
- **Budget:** priced like any other job.
  - The price comes from your receipts, else another car's, else Claude's estimate when you ask, or your own price.
  - It counts under Electrical: grey in the month bars, and the type picker can bring it forward.
- **Reminders:** like any schedule item, once the car's alerts are on.
- **Past receipts aren't changed.** To have old washer-fluid lines count, for example toward the price, search receipts for "washer" and give those lines the service.

### Count from a date
- **In the schedule editor,** each item gets an **Add a start date** button beside "Add a first due" and "Add a note".
  - It opens a **Count from** date field.
  - Hint: "For a job you've never kept records of. Nothing before this date counts as missed, and the first falls due one interval after it."
- **The gap engine starts that item's count on the date, as if the job was done then.** A used car with no in-service date already counts from the day you got it, in the same way.
  - The item has no missed or "before you had it" marks before the date.
  - Services before the date are ignored for this item; services after it count as usual.
  - "First at" no longer applies, since the count doesn't start from new any more.
- **Rules:**
  - The date can't be in the future: "That date is in the future."
  - Only a repeating item can have one: "Only a repeating item can count from a date."
- **Where you see it:**
  - the schedule page: "every 3 months, counting from Oct 6, 2026"
  - the schedule CSV export: a "Count from" column
- **What keeps it:**
  - editing the car's schedule keeps it
  - copying a schedule to another car drops it, since it's about this car's records
  - re-reading a manual replaces the schedule, as it does now
- **Nothing else needs changing.** These all come from the engine:
  - the garage's missed count
  - the car's "missed in the past" list
  - the interval chart
  - next up
  - the budget
  - alerts

## Code

### Washer fluid (commit 1)
- **`src/amg/migrations/0010_washer_fluid.sql`:**
  - Inserts `('washer_fluid', 'Washer fluid', 'Electrical', 'gas,hybrid,ev', 'replace', 615)`. This is skipped (`WHERE NOT EXISTS`) if a service called "Washer fluid" already exists, so there are never two.
  - Deletes the learned wording: `service_aliases` with `covers_json = '[]'`, `phrase LIKE '%fluid%'`, and washer, wiper, windshield or windscreen in the phrase.
- **`src/amg/ingest/schedule_templates.py`:** the left-out row in `_CHASSIS`.
- **`src/amg/repo/services.py`:** the docstring's example of a line with no service, "a wiper-fluid top-up", becomes a car wash.

### Count from (commit 2)
- **`src/amg/migrations/0011_count_from.sql`:** `ALTER TABLE schedule_items ADD COLUMN counts_from TEXT`, an ISO date. NULL means "from new, or from when you got it", as now.
- **`src/amg/engine/schedule.py`:**
  - `Item.counts_from: date | None`.
  - When it's set, `walk()` starts at `(counts_from, odometer.miles_on(counts_from) or 0.0)` with `first=False`, instead of calling `start_point()`.
  - The existing `s.day > base_day` already ignores earlier services.
  - The module docstring gains the rule.
- **`src/amg/web/status.py`:** `load()` passes `counts_from` into `Item`.
- **`src/amg/repo/schedules.py`:**
  - `ItemInput.counts_from`.
  - `_values()`, `_insert()` and `save_items()` write it.
  - `items()` already selects `i.*`.
- **`src/amg/ingest/schedule_drafts.py`:**
  - `blank_item()` gains `counts_from: None`, and `to_items()` passes it on.
  - `from_items()` keeps it only with `keep_ids` (editing this car), not when copying.
  - `interval_words()` adds ", counting from Oct 6, 2026".
- **`src/amg/web/schedule_editor.py`:**
  - `editor_row()`, `clean_items()` and `parse_items()` carry `counts_from` and `show_start`.
  - The date is parsed with `forms.day()`, which already refuses future dates.
  - Adds the one-off rule.
- **`src/amg/web/static/app.js`:**
  - `blankItem()` gains `counts_from: ""` and `show_start: false`.
  - `whenHint()` explains the date when it's set.
- **`src/amg/web/templates/_schedule_editor.html`:**
  - a "Count from" group with `x-show="item.show_start"`, after "First at"
  - the "Add a start date" button
- **`src/amg/reports/export.py`:** the "Count from" column in the schedule CSV.

**No new dependencies.**

## Tests
- **Migrations, in `tests/amg/test_db.py`,** starting from a database at 0009, built from a copy of migrations 0001–0009:
  - Washer fluid comes right after wiper blades in `list_types()`.
  - Learned wording:

    | Wording | Remembered with | After |
    |---|---|---|
    | "washer fluid" | nothing | forgotten |
    | "top off windshield washer fluid" | nothing | forgotten |
    | "wiper blades and fluid" | wiper blades | kept |
    | "drain plug washer" | nothing | kept |

  - With your own "Washer fluid" service already there, there's still just one.
- **Templates, in `tests/amg/ingest/test_schedule_drafts.py`:** the existing known-codes test covers the new row. New: it's left out, with its reason.
- **The engine, in `tests/amg/engine/test_schedule.py`:** an every-3-months item on a car you've had since 2019.
  - Without a date: many missed, and overdue.
  - Counted from 2026-10-06: no past marks, and the next is due 2027-01-06.
  - A top-up on 2026-12-01: done, with the next due 2027-03-01.
  - A service before the date is ignored.
  - "First at" is ignored.
- **Storage, in `tests/amg/repo/test_schedules_repo.py`:** `counts_from` round-trips through `save_items()`.
- **The editor, in `tests/amg/web/test_schedule_editor.py`:**
  - it parses the date
  - a future date is an error
  - a one-off item with a date is an error
  - copying another car's schedule drops the date
  - editing this car's keeps it
- **Pages, in `tests/amg/web/test_schedule_pages.py`:**
  - the schedule page shows "counting from"
  - a counted-from item adds nothing to the car page's missed count
- **The export, in `tests/amg/reports/test_export.py`:** the column is there.

## Commits
1. `feat(catalogue): washer fluid, beside wiper blades`
2. `feat(schedule): count an item from a date`
3. `docs: washer fluid and count-from dates`, covering:
   - **ROADMAP:** the Phase 1 catalogue line becomes 46 types. Phase 5 gets a ticked count-from item, a "Can go wrong" line, and a decision: a date you set, not a guess from when the item was added, because an item added late from the manual should still show what was missed.
   - **The plan:** saved to `docs/plans/2026-10-06-washer-fluid-and-count-from.md`, with its index row.

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on the seeded scratch copy (`scratchpad/p11/data`, made-up data), which migrates on start:
  - add Washer fluid to a car with years of history, every 3 months, counted from today
  - check that the car page's missed count doesn't change
  - check the chart, next up, and the budget (Electrical, grey, with the picker)
  - check the editor at desktop width and at 360px, in light and dark themes
- **The alerts dry run** on the scratch copy: no washer-fluid alert.
- **Done when (yours):** after you deploy:
  - you add Washer fluid to each car's schedule, every 3 months, counted from today
  - each car's missed count stays as it was
  - the budget shows washer fluid once it has a price
