> **Approved** 2026-10-05 21:15 · **Roadmap** [Phase 7](../ROADMAP.md#phase-7--forecast-and-budget)
>
> **Built in** `340a197` feat(budget): the budget by type of work, `025f310` docs(roadmap): budget by type
>
> **As built:** Jobs say "3 times · 1 due now" and "due now", not "1 overdue" and "expired": one phrase for overdue jobs and expired fees, matching the Due now figure.
>
> The plan below is as it was approved; it isn't edited afterwards.

# The budget, by type of work

## Context
You asked for the budget predictions to be broken down by maintenance type. Today the budget gives:
- one maintenance total
- month bars
- a month-by-month list

None of these answers "how much of this is brakes, and how much is tires?"

The catalogue already gives every job a type. Every service type belongs to one category: Engine, Drivetrain, Brakes, Tires and wheels, Steering and suspension, Electrical, Cabin, Hybrid and EV, and Inspections and other. The Spending report already splits past spending this way. The budget will split future spending the same way, so what's coming and what you've paid line up.

## How it behaves for you

### A new "By type" section
It goes on the car's budget page and the garage budget page.
- **Car's budget page:** after the figures, before Month by month.
- **Garage budget page:** after By car.

It follows the horizon switch: 12 months, 2 years or 3 years.

```
BY TYPE                                   next 12 months
Engine                                    $204   58%
███████████████████████████████
  Oil and filter          3 times         $204
Tires and wheels                           $75   21%
███████████
  Tire rotation           3 times · 1 overdue     $75
Inspections and registration               $69   20%
██████████
  Registration            once             $41
  Emissions inspection    expired          $28
Cabin                                   not priced
  Cabin air filter        2 times · not priced     —
```

### What goes in each type
- **Each type** shows its total, its share of the maintenance total, and a bar. The bars are scaled to the biggest type, so the largest fills the row.
- **The types add up exactly to the Maintenance figure.**
- **Order:** most expensive first. Types with nothing priced go last, in catalogue order.
- **The jobs in a type:**
  - each job shows how many times it falls in the horizon, how many of those are overdue or expired, and what they cost together
  - most expensive first
  - on the garage page each job also names its car: "Oil and filter · Outback"
- **A job's type** is its service type's category, the same rule the schedule page uses to group it.
- **A job that spans categories** goes under its first service type's category, the same rule the Spending report uses.
- **Fees get their own type, "Inspections and registration"**, because a registration isn't an inspection. The catalogue's "Inspections and other" keeps jobs like a multi-point inspection.
- **Jobs with no price** are listed under their type as "not priced", so the gap shows where it is.
- **Inspections done during other work aren't listed.** These are the "usually part of a visit" jobs, which have no cost of their own. The month list still shows them.
- **A car with nothing priced and no fees** doesn't show the section.

### On a phone (360px)
- The type name and total share the top line.
- The bar runs the full width under them.
- Job rows wrap their notes under the name, as the month list does.

## Code

### `src/amg/web/budget.py`
- **New `breakdown(plans)`:** returns one row per type: label, total, share, bar width, any unpriced, and its job rows. It reads every month's `(Due | Fee, Price)` items:
  - `forecast.Month.items`, built in Phase 7 and extended for fees
  - pass one plan for the car page, or every car's for the garage page
- **`CarBudget` gains `categories: dict[int, tuple[int, str]]`:** schedule item id → (catalogue order, category).
  - `load()` fills it from `state.items`, which already carries `category` and `category_sort` from `repo/schedules.py`.
  - A `Due` finds its type through its `item_id`. A `Fee` goes under "Inspections and registration".
- **A job row is keyed by car, type and name.** Occurrences, overdue count, priced total and unpriced count are summed across it.
- **No engine change.** The forecast already holds every occurrence with its price. Grouping them is presentation, like `month_rows`.

### `src/amg/web/routes_budget.py`
`garage_budget` and `_page` pass `types=budget.breakdown(...)`.

### Templates
- **`_budget.html`:** a new `by_type(types, horizon, per_car=False)` macro, shared by both pages.
- **`car_budget.html` and `budget.html`:** call it.
- **Accessibility:** each bar is decoration, hidden from screen readers. The name, dollar amount and percentage are real text.

### `src/amg/web/static/app.css`
- **A small `.btypes` block:**
  - rows divided like `.bcars`
  - the bar a solid `--ink` strip on a `--rule-soft` track, like the month bars
  - amounts in mono
- **No new colours.** The rows are labelled, so the bars don't need a colour per type.

**No new dependencies, no migration.**

## Tests
All in `tests/amg/web/test_budget_pages.py`. The worked Outback example is $143:
- **Tires and wheels:** tire rotation 3 times, 1 overdue, $75.
- **Engine:** oil and filter once, $68.
- **Cabin:** the cabin air filter twice, not priced.
- **Left out:** the brake lines inspection.
- **Checks:**
  - order: Tires and wheels, Engine, Cabin
  - shares of 52% and 48%
  - the types add up to `plan.maintenance`
- **With the fees from the last change:** an "Inspections and registration" type holding the registration and the expired emissions inspection.
- **Garage page:** two cars' oil changes under Engine, each naming its car, and the garage total matching.
- **The 24-month horizon** counts more occurrences, for example "5 times".
- **A car with no schedule and no fees** has no By type section.

## Commits
1. `feat(budget): the budget by type of work`: `budget.py`, the route, the templates, the CSS and the tests.
2. `docs(roadmap): budget by type`: a ticked item under Phase 7 and one decision (types are the catalogue's categories, as in the Spending report, with fees as their own type).

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on a scratch database in the scratchpad, never `samples/`:
  - at least one car with a priced schedule, such as an oil change and tire rotation from receipts, plus the fees seeded last time
  - check the car's budget page and the garage budget page at desktop width and 360px
  - switch to 3 years and check the counts and totals move
- **Done when (yours):** on the server, the Outback's budget shows where its next 12 months of money goes by type, and the types add up to its Maintenance figure.
