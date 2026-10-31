> **Approved** 2026-10-05 20:52 · **Roadmap** [Phase 10](../ROADMAP.md#phase-10--inspections-and-registration)
>
> **Built in** `b767ddb` feat(budget): inspection and registration fees, `5e17b8a` feat(alerts): the fee in inspection and registration reminders, `b409243` docs(roadmap): fees in the budget
>
> **As built:** The line for kinds without a date shows only when a car has no dates at all — "Inspection and registration fees are budgeted once their dates are on the car's page" — rather than naming each untracked kind, so a state with no emissions testing isn't reminded forever.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Inspection and registration fees in the budget

## Context
Phase 10 records what each safety inspection, emissions inspection and registration cost, but the budget leaves those costs out. It was a deliberate decision at the time, noted as "a later step if wanted". You've now asked for it.

The goal: "Put aside $X a month" covers these fees too, and each one appears in the month it falls due, next to the maintenance jobs.

## How it behaves for you

### When a fee is counted
- **In the month the current one expires.** Stickers and registration cards run to the month's end, and that's the month you pay.
- **Already expired:** the fee counts as **due now**, like an overdue job. It isn't spread over the months to come.
- **After that:** it repeats at the same interval Phase 10 already uses, until the end of the horizon:
  - the interval your records show, otherwise 12 months, or 24 for emissions
  - so a 3-year budget holds three registrations
- **Not tracked:** if a car has no date for a kind, that kind isn't budgeted. The car's budget page says so, for example: "Add the safety inspection and registration dates on the car's page to budget for them."

### What a fee costs: what you paid last time, the first of these that exists
1. **The newest record of that kind that has a cost.** It shows as "Paid Mar 2026", or "Paid last time" if the record has no done date.
2. **For an inspection only:** the newest receipt line for it. That's the same amount **Log it** already fills in, and it shows as "Paid Sep 2025".
3. **Nothing:** the row says "No cost yet", with **Add what you paid**. That link opens the latest record's edit page, which has the Cost field. A notice says the totals leave it out.

Two exceptions to how other prices work:
- **No 4%-a-year increase.** The state sets these fees by law, not the market, so last time's price is this time's.
- **No Claude estimate.**

### How the totals show it
Fees count in all the totals:
- put aside a month
- the month bars
- due now
- the garage line
- the car page's budget line
- the weekly email's budget line

The labels say where fees are included:
- **Budget lines that read as a sentence** say "maintenance and fees" when a car has any. For example: "~$231 of maintenance and fees in the next 12 months: put aside $19 a month".
- **The Maintenance figure** on the car budget page and the garage budget page keeps its label. Its note says how much of it is fees: "next 12 months, $88 of it fees".
- **The Due now note** names expired fees: "3 overdue jobs, registration expired".
- **In the month list,** each fee is its own row, named and marked like a job. An expired fee is marked "Expired", not "Overdue". The row says "Expires Mar 31" or "Expired Sep 30", with its cost and where the cost came from.

### Not counted twice
A schedule might have a **State inspection** or **Emissions test** item, from the manual or added by hand. Once that kind has a date, the schedule item drops out of the budget and the dated fee replaces it.

### Reminders show the cost too
An inspection or registration push, and its line in the weekly email, now end with the cost, the way jobs do. For example: "expires Oct 31 · in 26 days · ~$41".

## Code

### `src/amg/engine/renewals.py`
- **New `coming(kind, records, today, end)`:** returns each occurrence up to `end` as a pair: the day the fee lands (the expiry, or today if it has passed) and the expiry date.
- **Reuses** `interval`, `end_of_month` and `schedule.add_months`.

### `src/amg/engine/forecast.py`
- **New `Fee` dataclass:** `kind`, `name`, `status`, `day` and `due_day`. The status is overdue (expired), due or later, as for jobs.
- **`budget(..., fees=())`:** takes `(Fee, Price | None)` pairs and puts them in their months. Each month's items are kept in day order.
- **`Month.unpriced`:** jobs only.
- **New `Month.fees` sum.**

### `src/amg/web/budget.py`
- **`load()`:**
  - reads the car's records (`repo.renewals.for_car`) and the receipt fallback (`repo.renewals.latest_service`)
  - prices each tracked kind
  - drops schedule jobs that are exactly a tracked kind's service type
  - passes the fees to `forecast.budget`
- **`CarBudget` additions:**
  - `fees`: per kind, its price and the latest record's id
  - `fee_total`, `expired` (the kinds expired now), `fees_unpriced`, `untracked`
  - `fee_cost(kind)`, used by the alerts
  - `overdue` keeps counting jobs only
- **`month_rows`:** fee rows with their mark label, when, cost and source words, plus the **Add what you paid** link.
- **`strip()`:** gains the fee total for the garage.

### Templates
- **`_budget.html`, `month_list`:**
  - a row-level mark label, so a fee can say "Expired"
  - the source can carry a link
  - the bars' legend and aria-label say "Maintenance and fees" when fees are in
- **`car_budget.html`:**
  - the Maintenance figure's note and the Due now note
  - the "No cost yet" notice
  - the untracked-kinds line
- **`budget.html`:** the Maintenance figure's note and the Due now note.
- **`garage.html` and `vehicle.html`:** "maintenance and fees" in the budget line.

### Alerts
- **`src/amg/alerts/mail.py`, `budget_line`:** "maintenance and fees" when fees are in.
- **`src/amg/alerts/watch.py`, `look()`:** a renewal's `Watched` gets `plan.fee_cost(kind)` as its cost. Push and email already print a job's cost when it has one.

### Not changed
- the database: there's no migration, because costs are already stored on `renewals`
- the price list and Ask Claude, which stay maintenance jobs only
- the data export
- no new dependencies

## Tests
- **`tests/amg/engine/test_renewals.py`: `coming()`.**
  - the expiry in the horizon
  - an expired one due today, then the next one counted from today
  - three registrations in 36 months
  - a two-year emissions inspection appearing once in 12 months
  - one beyond the end left out
- **`tests/amg/web/test_budget_pages.py`,** extending the worked Outback example:
  - a logged registration cost and an inspection priced from its receipt line appear in their months, with "Paid …"
  - the totals and put-aside figure move by exactly the fee, with no inflation
  - an expired fee goes to due now ("registration expired")
  - a fee with no cost shows "No cost yet", the link to its edit page, and is left out of the totals
  - an untracked kind gets the line saying so
  - a schedule's State inspection item isn't counted twice
  - the garage budget page's figure note, plus the garage and car page lines saying "maintenance and fees"
  - all existing figures unchanged when a car has no fees
- **`tests/amg/alerts`:** a renewal push and email line with its cost. The existing ones have no cost, so they're unchanged.

## Commits
1. `feat(budget): inspection and registration fees`, covering the engine, `web/budget.py`, the templates and the tests.
2. `feat(alerts): the fee in inspection and registration reminders`.
3. `docs(roadmap): fees in the budget`:
   - a ticked item under Phase 10
   - the "Costs are kept, not budgeted" decision rewritten to explain the new behaviour (last time's cost, no inflation, no Claude, never counted twice)

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on a scratch database in the scratchpad, never `samples/`. Seed a car with:
  - a schedule
  - a registration expiring in 4 months with a cost
  - an expired safety inspection with a receipt line
  - an emissions inspection with no cost
- **Check in the browser, at desktop width and 360px:**
  - the car budget at 12 and 36 months
  - the garage budget page and the garage line
  - the car page's budget line
- **Check the alerts:** `python -m amg.alerts.run --dry-run` shows the cost on the reminders.
- **Done when (yours, on the server):** after deploying, the Outback's budget shows its registration and inspections in the right months at what you paid, and put-aside goes up by about the fees divided by 12.
