> **Approved** 2026-10-03 09:13 · **Roadmap** [Phase 7](../ROADMAP.md#phase-7--forecast-and-budget)
>
> **Built in** `c6ae465` feat(db): price_book, `dddc4a9` feat(engine): forecast and budget arithmetic, `1f0cea0` feat(ingest): Claude's price estimates, `7cc0715` feat(web): the budget, `4975995` docs(roadmap): tick off phase 7
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 7: Forecast and budget

## Context
The SPEC's fourth goal is to estimate future costs so you can budget for them. Phases 5 and 6 already supply the inputs:
- the schedule engine knows when each item next falls due, dated from the odometer projection
- your confirmed receipts know what work cost
- the fuel log knows the cost a mile

Phase 7 puts these together. It answers how much to put aside, and when.

## How it behaves for you

### Where it shows
- **Garage, above the cars:** "Next 12 months: ~$1,420 of maintenance, ~$1,900 of fuel. Put aside ~$118 a month." It links to **The budget** for all cars.
  - There's no masthead link. A fourth link doesn't fit at 360px, and the garage is one tap away.
- **Car page, next up:** each item shows its estimated cost, using the "~$85" slot already reserved in the next-up row. A line under the list gives the 12-month total, the monthly amount and a link to the car's budget.

### The car's budget page (`/vehicles/{id}/budget`)
- **Figures:**
  - **Put aside**, per month: maintenance only, spread evenly over the horizon. You pay for fuel as you go.
  - **Maintenance** and **Fuel** for the horizon.
- **Horizon switch:** 12 months (default), 2 years or 3 years. The longer views catch the expensive, infrequent jobs (timing belt, coolant at 137,500, tires) in the monthly figure.
- **Month chart:** one bar per month, maintenance and fuel stacked. It's drawn in HTML/CSS, so no library is needed. The month list below holds the same figures.
- **Month list:**
  - The current month counts from today to its end.
  - Overdue items go in the current month.
  - Each item shows its status mark, its name, when ("in 2,300 mi · ~Dec"), its price and where the price came from.
  - Each month ends with a fuel line: "Fuel ~$154 · ~1,050 mi".
  - A job due twice in the horizon (an oil change every 6 months) is listed twice.
- **Prices:** a list of every job in the car's schedule with its price and source.
  - **Set your price** opens an inline field ("What one visit costs, tax included"). **Save price** saves it, and **Use AMG's estimate** removes it.
  - **Ask Claude to price 6 items** appears when jobs have no price, with the note "About 4¢. You can change any price it gives." While Claude works, the page shows "Claude is pricing 6 items…" and refreshes itself, as the receipt and schedule pages do.

### The all-cars budget (`/budget`)
- The same figures and chart, summed across cars.
- A month-by-month table: maintenance, fuel and total.
- A per-car table: maintenance, fuel and a month's set-aside, each car linking to its own budget.
- Archived cars are left out.

## Where a price comes from (first match wins)
1. **Your price:** what you typed.
   - **This changes the roadmap's order**, which put the price book after your history. If a price you typed lost to an old receipt, you'd have no way to correct an estimate. The roadmap gets this edit.
2. **Paid on this car:** the median of what visits that did this job cost, in today's money. Shown as "Median of 4 visits".
3. **Quoted on this car:** recommendations on your confirmed receipts that carried a price. Phase 2 kept these apart from work done, and the tire invoice has six of them. Shown as "Quoted Mar 2024".
4. **Paid on your other cars:** the same median, archived cars included. Shown as "Paid on your Forester".
5. **Claude's estimate:** a range, flagged wherever it shows ("Claude's estimate, $180–260") and stored so it's only asked for once. The budget counts the midpoint.
6. **Nothing:**
   - An inspection job shows "Usually part of a visit" and counts as $0. Dealers check these during other work, and Claude isn't asked to price them. If you've paid for one on its own, your history prices it.
   - Any other job shows "No price yet". The totals note how many such jobs there are.

### What one visit charged for a job
- **Which visits count:** the visit must have done all of the job. An oil-and-filter job isn't priced from a visit where you only bought a filter. Inspection jobs only need one of their parts looked at.
- **Lines:** the job's price is its share of the lines that did the work. A line that did several things is split evenly between the ones it did. Inspections riding along on a line that replaced something get none of it.
- **Tax, shop fees and discounts:** a fee line or negative line that covered no service type is shared out with the visit's tax, in proportion to each line's amount.
- **$0 and blank lines:** a visit whose share comes to $0 or less isn't a price. That covers warranty work and $0 lines, so they never pull the median down.
- **Inflation:** older prices are brought up to today's at **4% a year**. That's roughly what US car maintenance and repair prices rose from 2016 to 2025, the span your receipts cover. Over those years the BLS index rose about 50%, from 1.4% a year early on to 8% in 2023.

### Fuel
- Fuel for a month is miles a day (`Odometer.rate()`), times the days in the month, times the cost a mile. The cost a mile is the fuel page's figure: the last 12 months, else all time.
- With no fill-up costs or no odometer pace, the fuel line says what's missing ("Log fill-ups with their cost to budget fuel").

## The arithmetic: `src/amg/engine/forecast.py` (pure)
- **Constant:** `INFLATION = 0.04`.
- **Inputs:**
  - `Line(amount_cents, kind, covers: {code: action})`
  - `Visit(id, vehicle_id, day, lines, tax_cents)`
  - `Job(codes, action)`, where the key is the sorted codes plus the action
- **Pricing functions:**
  - `paid(visit, job) -> int | None`: the rules above.
  - `quoted(quote, job)`: a quote split across its codes the same way. Only for replace or perform jobs.
  - `today_money(cents, day, today)`
  - `Price(cents, low, high, source, count, day)`
  - `estimate(job, yours, here, quotes, elsewhere, claude, today) -> Price | None`: the fallback order. `low` and `high` give the history spread ("4 visits, $72–95") or Claude's range.
- **Budget functions:**
  - `upcoming(statuses, today, end)`: every overdue, due-soon or later occurrence from the gap engine, up to the horizon's end.
    - Overdue ones are dated today.
    - Anything past the end is excluded.
    - The gap engine already counts each occurrence from the one before. `web/status.load` gains an `until` argument so the walk reaches 36 months.
  - `months(today, count)`: the horizon in calendar months, starting with the rest of this one.
  - `fuel_cents(rate, cents_a_mile, start, end)`
  - `budget(...) -> list[Month(start, items, maintenance, fuel)]`

## Data: `src/amg/migrations/0007_price_book.sql`
- **New table `price_book`:**
  - `vehicle_id` (cascade)
  - `codes` (sorted, comma-joined) and `action`: keyed by the job, not the schedule item, so prices survive using a new schedule, and a severe-service oil change shares the normal one's price
  - `name`: the item's name when priced
  - `source`: `you` or `claude`
  - `low_cents`, `high_cents`: equal for yours
  - `note`: Claude's one line on what the range covers
  - Claude's asking, as receipts do it:
    - `status`: queued, asking, done or failed
    - `job_id`
    - `error`
    - `model`
    - `cost_usd`
  - timestamps
- **Constraint:** `UNIQUE (vehicle_id, codes, action, source)`. Your price and Claude's can both exist; removing yours brings Claude's back.

## Code
- **`src/amg/repo/prices.py`:**
  - `set_yours`, `remove_yours`
  - `for_car`, with every row for a car
  - `queue_claude`, `claim`, `mark_priced`, `mark_failed`
  - `visits(conn)`: every confirmed visit's lines with what they covered, for all cars, in one query
  - `quotes(conn, vehicle_id)`: priced recommendations from confirmed receipts' `draft_json`
- **`src/amg/repo/jobs.py`:** `resume` also re-queues `price_book` rows left `asking`.
- **`src/amg/ingest/prices.py`:**
  - `ask_claude(car, jobs, anchors)` goes through `claude.parse`, the one way AMG calls Claude, with a Pydantic schema (`key`, `low_usd`, `high_usd`, `note`).
  - **Inputs:**
    - the car's year, make, model, trim and engine
    - each job's name and action
    - up to 12 of the car's own prices from history, so it knows what your shops charge
  - **Validation:** low ≤ high, both > 0, under $20,000. A job missing from the answer is marked failed with the reason.
  - **Cost:** one call per car, about 4¢ on Opus.
- **`src/amg/ingest/background.py`:** a `price_jobs` job kind, which follows the read-receipts pattern (spawn, run, `ClaudeError` → failed with the message).
- **`src/amg/web/budget.py`:** loads a car (`status.load` with `until`, `fuel_status.load`, prices, visits, quotes), runs the engine and words the answer, as `status.py` and `fuel_status.py` do. It builds:
  - `car_budget`
  - `garage_budget`
  - `price_rows`
  - `costs_for_next_up`
- **`src/amg/web/routes_budget.py`:**
  - `GET /budget?months=`
  - `GET /vehicles/{id}/budget?months=`, where months is 12, 24 or 36, else 12
  - `POST /vehicles/{id}/prices`: save or remove your price, using the `forms.money` parser
  - `POST /vehicles/{id}/prices/ask`
  - Registered in `app.py`.
- **Templates:**
  - new: `budget.html` (all cars), `car_budget.html`, `_budget.html` (the month chart and the month list macros)
  - `garage.html`: the strip
  - `vehicle.html`: the line under next up
  - next-up costs go through the existing `next_up` macro's `item.cost`
- **`src/amg/web/status.py`:** `load(..., until=None)`, and `next_up` rows take an optional cost.
- **`src/amg/web/static/app.css`:** a "Budget" section for the strip, the figures (reusing `.figures`), the month bars, the month list (built on the `.nextup` row grid), the price rows and the source tags. Claude's estimates use the dashed "as Claude read it" style already used on review screens.

## Tests
- **`tests/amg/engine/test_forecast.py`:** hand-worked, with every figure worked out in the docstring. It covers:
  - `paid` on a visit with an oil-and-filter line, a rotation, a $0 multi-point check, a shop fee and tax, with the overhead share worked to the cent
  - a package line split between the jobs it did, with the inspections on it getting nothing
  - a filter-only visit not pricing oil and filter
  - a $0 warranty line not lowering the estimate (the roadmap's pin)
  - a credit line
  - inflation: $50 four years ago comes to $58.49
  - the fallback order, tier by tier (the roadmap's pin)
  - an occurrence past the horizon left out (the roadmap's pin)
  - overdue counted this month
  - oil twice in 12 months
  - a one-off item
  - month buckets
  - fuel for the rest of this month and a whole month
- **`tests/amg/repo/test_prices_repo.py`:**
  - yours and Claude's side by side
  - removing yours
  - `visits` reading lines and coverage
  - `quotes` from a confirmed receipt only
  - prices kept after a new schedule replaces the items
- **`tests/amg/ingest/test_prices.py`:** Claude's answer validated, with `claude.parse` faked. It covers:
  - a missing key
  - low > high
  - a refused or failed call, with the rows marked failed and the message
  - the job running inline, as `test_background.py` does
- **`tests/amg/web/test_budget_pages.py`:**
  - the car budget's months, figures and sources
  - setting and removing a price changing the total
  - the ask button starting a job and the page showing it waiting
  - the horizon switch
  - the garage strip
  - next-up costs
  - all-cars totals
  - an archived car left out
  - a car with no schedule budgeting fuel only

## Commits
1. `feat(db): price_book`: the migration, `repo/prices.py`, `jobs.resume` and the repo tests
2. `feat(engine): forecast and budget arithmetic`
3. `feat(ingest): Claude's price estimates`
4. `feat(web): the budget`: the pages, the garage strip, next-up costs and price editing
5. `docs(roadmap): phase 7`: ticks, the price-order change, the 4% decision, can-go-wrong and done-when

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- A local run on a scratch database: the Outback's schedule, a dozen services with the cases above, a few fills, and a second car. Claude is faked or left unconfigured, so nothing is spent.
  - Check the garage strip, the car page, the car's budget at 12, 24 and 36 months, the all-cars page and price editing.
  - Check each at desktop width and at 360px, the latter in an iframe as before.
- **Proposed done-when:**
  - the engine matches the hand-worked figures
  - on the server, the Outback's budget is priced from your receipts, with Claude asked only for what they don't cover, and the 12-month total looks believable to you
