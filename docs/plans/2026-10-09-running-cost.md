> **Approved** 2026-10-09 23:15 · **Roadmap** [Phase 15](../ROADMAP.md#phase-15--running-cost)
>
> **Built in** `8f7bd00` feat(running-cost): what a car costs a mile, since you got it and year by year, `5ea7e02` feat(running-cost): the next 12 months, and the garage, `2c56175` fix(running-cost): a mile beside the year; the garage says when fuel isn't in it, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The table's columns** (`2c56175`): the figure a mile comes straight after the year, not last, so a phone shows it without scrolling. "In all" at the foot adds up to the headline.
> - **The garage says "a mile, not counting fuel"** for a car with no fill-up costs (`2c56175`). In the browser check, the scratch Civic showed 1.0¢ a mile beside the Outback's 16.5¢, which had fuel in it.
> - **A year with nothing recorded** shows no figure a mile rather than 0.0¢ (`2c56175`).
> - **Words:**
>   - Every start shows its day ("from May 1, 2019"), where the plan's examples gave a month for two of them.
>   - The headline's label names the start ("Since it was new").
>   - With no fill-up costs, the next 12 months says "Not counting fuel: log fill-ups with their cost."
>   - With no schedule it says "Fuel and fees only", or "Fuel only" or "Charging only" when there are no fees.
> - **Checked in the browser** on the scratch garage's existing made-up cars rather than a newly seeded one, with no Claude calls:
>   - the Outback: a fuel log, fees, since you got it
>   - the Civic: no fill-ups, since it was new
>   - the Model 3: charging
>   - the archived Tacoma: one reading, so "AMG needs two odometer readings"
>   - the garage
>   - at 360px (the table scrolls in its box and the page doesn't), on the desktop, and in dark mode
>
>   The changes above were the only ones it called for.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Running cost: what a car costs a mile

## Context
AMG already works out fuel's cost a mile from your fill-ups, but nothing puts fuel, service and fees together. So there's no answer to "what does this car cost me a mile to run?", and no way to see whether that's climbing as it ages. You chose:
- **What it counts:** what AMG already knows. That's fuel or charging, every confirmed service (shop bills and parts for your own work), and inspection and registration fees. There's nothing new to type in.
- **Which figures:** since you got it, year by year, and the next 12 months.
- **Where:** the car's page and the garage.
- **Fuel before your log starts:** estimated at your fill-ups' cost a mile, and marked as estimated.

It ships as roadmap Phase 15 in two feature commits and a docs commit. There are no new dependencies, no migration and no Claude calls.

## How it behaves for you

### On the car's page
A **Running cost** block (`#running-cost`) sits after Fuel and before Service history.
- **The headline:** "**31.2¢** a mile", followed by "$14,230 over 45,600 mi since you got it, Mar 12, 2019".
  - Its parts: Fuel 12.4¢ (est.), Service and repairs 17.6¢, Fees 1.2¢.
  - The start is when you got it. Without that date it's the in-service date ("since it was new, Mar 2015"). Without either, it's your first record ("since your first record, Jun 2020").
- **Next 12 months:** "~27¢ a mile", followed by "~$3,240 for ~12,000 mi: fuel ~$1,500, maintenance ~$1,600, fees ~$140".
  - This uses the budget's own figures, with a link to the budget.
  - Work already overdue is left out, as the put-aside figure leaves it out, so it doesn't count against future miles. The line says "not counting $480 due now".
  - "3 jobs not priced yet" when there are any.
  - With no maintenance schedule: "Fuel and fees only: with a maintenance schedule, AMG counts its jobs too".
- **Year by year:** a table with Year, Miles, Fuel, Service and repairs, Fees and A mile.
  - Newest first. The current year reads "2026 so far", and the first year notes "from Mar 12".
  - A year under 500 miles shows its money but no figure a mile, which would mean nothing.
  - On a phone the table scrolls inside its own box, like the reports' tables.
- **How fuel is counted** (a note under the table):
  - Miles a logged fill-up measured, full tank to full tank, count at what they actually cost.
  - Every other mile counts at your fill-ups' cost a mile: the fuel page's figure, over the last 12 months or all time.
  - A fuel figure with any estimated miles is marked **est.**, and the note gives the rate used.
  - With no fill-ups that have a cost, fuel isn't counted. The headline then says "not counting fuel", and the note says to log fill-ups with their cost.
- **When there isn't enough to go on:**
  - With fewer than two odometer readings, the block says what the budget says: "AMG needs two odometer readings a while apart to tell how far the car goes."
  - Under 500 miles since you got it: "Too few miles yet: 320 mi since you got it."
- **An archived car:** its figures end at its last odometer reading, since a car you've sold stops adding miles. It has no Next 12 months.

### What counts, and where
- **Service and repairs:** each confirmed visit on or after the day you got it, at what it cost. That's its total, or its lines and tax when there's no total, the same rule as the Spending report. It includes parts for your own work and anything bought on a receipt, such as a warranty. A visit marked "Done, no receipt" has no amount and adds nothing.
- **Fees:** each inspection or registration record with a cost, counted on the day it was done.
  - With no day done: a year before it expires (two years for emissions).
  - One logged from a visit is already in that visit's total. Its cost moves from Service and repairs to Fees, so the total doesn't count it twice.
- **Miles:** from the odometer model, between the start and today (estimated to today, as everywhere else).

### On the garage
Each car's card gets a fact: **Running cost** "31.2¢ a mile". The next 12 months stays on the car's page, so the card keeps one line. A car without enough to go on simply doesn't show it.

### Not included
- insurance, a loan, parking or depreciation (not chosen)
- a running-cost view in Reports, or a column in Download your data
- old fuel priced at the gas prices of its day: early fuel is at your recent cost a mile, marked

## Code

### Commit 1: `feat(running-cost): what a car costs a mile, since you got it and year by year`
- **New `engine/running_cost.py`** (pure):
  - **Constants:** `MIN_MILES = 500`
  - **Types:**
    - `Spend(day, part, cents)`, where part is `service` or `fees`
    - `Period(start, end, miles, fuel, estimated_miles, service, fees)`, with `total` and `cents_a_mile` (None under `MIN_MILES`), plus each part a mile
  - **`years(start, end, odometer, spends, stretches, rate) -> list[Period]`:** a calendar year each, the first from `start` and the last to `end`.
    - Miles come from `Odometer.miles_on` at the boundaries.
    - Stretches with a cost count in the year they ended, the same rule as the Fuel report.
    - The rest of the year's miles are counted at `rate` (`estimated_miles`), never below zero.
    - `rate` None means fuel is None.
  - **`whole(periods) -> Period`:** their sum, so the table adds up to the headline.
- **New `web/running_cost.py`** (loading and words, like `fuel_status.py`):
  - `start_of(car, odometer)` → (day, words), and `end_of(car, odometer, today)`
  - **`spends(conn, car, start)`:**
    - `repo.reports.visits(conn, car_id, start=…)` with `reports.history.paid`
    - plus `repo.renewals.for_car` records with a cost
    - moves a visit-linked fee out of the service figure (capped at the visit's amount)
  - `load(conn, car, odometer, today) -> RunningCost | None` (with the reason when None): fuel from `fuel_status.load` and `fuel_status.cost_a_mile`
  - **Words:** `headline`, `parts`, `year_rows`, `fuel_note`, reusing `fuel_status.cents_a_mile` and the `money` and `dollars` filters
- **Move `odometer_for` from `web/warranties.py` to `web/status.py`:**
  - `status.load` uses it too.
  - `web/warranties.py` imports it from there.
- **`routes_vehicles.car_page`:** passes `running=running_cost.load(conn, car, state.odometer, state.today)`.
- **`vehicle.html`:** the block, built from the existing `figures sheet`, `.figure` and `tablewrap sheet sheet--flush` / `sumtable` pieces.
- **`app.css`:** only what the block's parts line and **est.** mark need.

### Commit 2: `feat(running-cost): the next 12 months, and the garage`
- **`engine/running_cost.ahead(months, rate) -> Period`:**
  - **From `forecast.Month`s:**
    - fuel is the months' fuel
    - service is priced jobs not overdue
    - fees are priced fees not expired
  - **Miles:** rate × the horizon's days.
  - **Also returns:** the overdue sum left out, and the unpriced count.
- **`web/running_cost`:** `ahead_words(plan)` from the `CarBudget` the car page already loads (`budget.load(conn, car, 12, state=state)`).
- **`vehicle.html`:** the Next 12 months lines.
- **`routes_garage`:**
  - `car["running"]` from `running_cost.load` with `status.odometer_for`
  - **`garage.html`:** the **Running cost** fact

## Tests
- **New `tests/amg/engine/test_running_cost.py`:** a hand-worked car (got it mid-year, three years of readings, services, a linked and an unlinked fee, a fuel log starting in the last year), with every row worked out on paper. It covers:
  - the years' boundaries and miles
  - a first year that starts mid-year, and a current year that's partial
  - measured stretches at their cost, the rest estimated, est. miles never negative
  - a stretch with a cost missing counted as estimated
  - no rate means no fuel
  - under 500 miles has no figure a mile
  - `whole` adds up the rows
  - `ahead`: overdue and expired left out, unpriced counted, the miles from the rate
- **New `tests/amg/web/test_running_cost_pages.py`:**
  - The start and its words: acquired, in service, first record.
  - What's counted:
    - visits before you got it are left out
    - a visit with no total counts its lines and tax
    - an unconfirmed receipt and "Done, no receipt" add nothing
    - a linked fee isn't counted twice
    - a fee with no day done is counted a year before it expires
  - The block's words:
    - headline, parts, est. and its note
    - not counting fuel, too few miles, no odometer
  - **Car types:** an archived car ending at its last reading with no next 12 months; an electric car says Charging.
  - **Next 12 months:** due now, unpriced, no schedule.
  - **The garage fact:** shown, and left out when there's nothing to go on.
- **Existing warranty tests still pass** after `odometer_for` moves.
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 3: `docs: Phase 15, running cost`)
- **`docs/ROADMAP.md`:** **Phase 15 — Running cost**, in the usual shape:
  - For, the checklist (ticked), Data owned (none new), Can go wrong, Tests pin, Done when
  - **Decisions:**
    - only what AMG knows
    - early fuel estimated at your cost a mile, marked
    - overdue work left out of the next 12 months
    - a linked fee moved, not doubled
    - an archived car ends at its last reading
    - 500 miles before a figure a mile means anything
- **The plan:** saved verbatim to `docs/plans/2026-10-09-running-cost.md` with the header, plus an index row.

## Can go wrong (for the roadmap)
- **A used car with no "when you got it":** counted from new, so the earlier owner's miles carry no costs and the figure reads low. The block says "since it was new", so you'd see it, and setting the date fixes it.
- **A receipt history still going in:** the missing years read cheap.
- **A big repair:** it lands in one year's row, but is spread over every mile in the headline.
- **Fuel before your log:** estimated at today's prices, and marked.

## Verification
- **Tests** pass after every commit.
- **The scratch garage** (`scratchpad/p11`, made-up data, no Claude calls): seed a car with readings over three years, services, a linked and an unlinked fee, and a few fill-ups. Check:
  - the block's headline, parts, est. note and year table
  - Next 12 months
  - the garage fact
  - an archived car
  - a car with one reading
- **Layout:** at 360px (the table scrolls in its box, the page doesn't) and on the desktop, in light and dark.
- **Done when (yours), after you deploy:** each car's running cost looks believable to you against what you know you've spent, and the year rows show what you'd expect, such as the year of a big repair.
