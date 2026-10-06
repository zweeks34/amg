> **Approved** 2026-10-03 02:09 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Built in** `93253d7` feat(db): fuel_logs, and fill-ups as odometer readings, `8c41274` feat(engine): fuel economy, `e5cc206` feat(web): log fill-ups and charges, `61ced65` feat(web): the fuel page, `3bb6706` docs(roadmap): tick off phase 6
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 6: Fuel and energy

## Context
Phase 5 answers "what have I missed?". Phase 6 adds the running cost:
- a quick phone form at the pump or charger
- fuel economy and cost per mile
- every fill-up as an odometer reading

The odometer model currently depends on service visits and the odometer readings you type in. A fill-up every week or two gives it fresh readings, so today's estimated odometer and every due date get sharper. Your service history isn't needed: fill-ups stand alone, and older receipts uploaded later fit in behind them.

### Your decisions
- **No plug-in hybrids.**
  - Gas and hybrid cars log *fill-ups*: gallons and MPG.
  - Electric cars log *charges*: kWh, mi/kWh, and home or public.
  - No switch on the form.
- **No import.** The log starts at your next fill-up, though the form accepts past dates for back-filling.

## How it behaves for you
- **One tap from anywhere.** The masthead gets **Fill-up** (it reads **Charge** if every car is electric).
  - With one car, it opens that car's form.
  - With several, it lists them, most recently filled first.
  - Each car's form has its own URL, so you can add it to your phone's home screen.
- **The form, at the pump.**
  - Fields:
    - date (today)
    - odometer (required), with "Last: 64,300 mi on Sep 28" as the hint
    - gallons
    - total cost (optional), with the price per gallon worked out live underneath: "$3.459/gal"
    - **Filled the tank** (ticked by default)
  - Folded under **More**:
    - **I didn't log the fill-up before this one**
    - a note
  - For an EV:
    - kWh instead of gallons
    - **Home / Public**, defaulting to the last one used
    - **Charged to your usual limit** instead of Filled the tank
    - For a home charge, the cost fills in at your last home rate (cost ÷ kWh of the last home charge). You can change it.
  - The button says **Save fill-up** or **Save charge**.
- **After saving** you land on the car's fuel page, with "Saved. 28.6 mpg since your last full tank." A partial fill or your first fill-up instead says MPG shows at the next full tank.
- **An odometer lower than an earlier reading is refused** by the check every reading already goes through: "That's lower than the 64,300 mi recorded earlier, on 2026-09-28 (a fill-up)."
- **Car page.** A **Fuel** block (**Charging** for an EV) sits between Next up and Service history.
  - It shows:
    - MPG over the last 12 months
    - cost per mile
    - the last fill-up
  - It has two buttons: **Log a fill-up** and **The fuel log**.
  - With nothing logged yet, it says economy appears after your second full tank.
  - In the odometer readings list, readings from fill-ups say "From a fill-up" and link to that entry.
- **The fuel page** (`/vehicles/{id}/fuel`).
  - Figures:
    - MPG for the last tank, the last 12 months and all time
    - cost per mile
    - spent in the last 12 months
    - average price per gallon
  - A trend chart: MPG for each tank over time, with the 12-month average as a line. It's drawn on the server as SVG, so no chart library.
  - The log, newest first:
    - date, odometer, gallons, $/gal, total, MPG
    - a partial fill says "partial"
    - an MPG more than 40% off your median is flagged "unusual, check it". The usual cause is a fill-up that wasn't logged, or a typo.
  - Every entry can be edited or deleted. A wrong odometer is fixed the same way.

## The arithmetic: `src/amg/engine/fuel.py` (pure)
- **Inputs and outputs:**
  - `Fill(id, day, odometer, quantity, cost_cents, full, missed_before)`
  - `Stretch(start, end, miles, quantity, cost_cents, economy)`, where `economy` is miles ÷ quantity
- **`stretches(fills)`.** Fills are sorted by date, then odometer.
  - A full fill starts the count.
  - Partial fills after it add up.
  - The next full fill closes the stretch: miles since the last full fill ÷ everything put in since, that fill included.
  - A partial fill before the first full one is ignored: it fuelled miles nobody measured.
  - **I didn't log the one before** breaks the count. No stretch ends across it, and if that fill is full, it starts a new count.
  - A full fill at no new miles (a top-off) closes no stretch.
- **`economy(stretches, since=None)`.** Total miles ÷ total quantity, not an average of averages, so a short tank doesn't count as much as a long one.
- **`cost_per_mile`.** Total cost ÷ miles over stretches whose fills all have a cost. One with a missing cost is left out rather than counted at $0.
- **`spent(fills, since)`.** The cost of every fill, partials included.
- **`unusual(stretches)`.** Stretches more than 40% from the median. Needs at least 3 stretches.
- **`home_rate(fills)`.** Cents per kWh from the last home charge with a cost.
- **Kept for Phase 7:** `cost_per_mile` and the odometer model's miles a day give its fuel projection.

## Data: `src/amg/migrations/0006_fuel.sql`
- **New table `fuel_logs`:**
  - `vehicle_id` (cascade, like `odometer_readings`)
  - `filled_on`
  - `odometer` (NOT NULL, ≥ 0)
  - `energy` (`gas` / `electric`): stored per row, so correcting a car's powertrain later doesn't change old entries' units
  - `quantity` (REAL, > 0; US gallons or kWh)
  - `cost_cents` (NULL = unknown, ≥ 0)
  - `full`
  - `missed_before`
  - `place` (`home` / `public`, charges only)
  - `note`
  - timestamps
- **Index:** `(vehicle_id, filled_on)`.
- **`odometer_points` view:** dropped and recreated with one more branch. Its source is `charge` for electric rows, else `fill`.
  - The view's comment already promised this.
  - Everything that reads the view picks fill-ups up with no other change: the odometer model, today's estimate, the garage card's odometer and the conflict check.

## Code
- **`src/amg/repo/fuel.py`:**
  - `FillInput`
  - `create`, `get`, `update`, `delete`
  - `log(conn, vehicle_id)` (newest first)
  - `last(conn, vehicle_id)`
  - `garage_order(conn)` (cars, most recently filled first)
- **`src/amg/repo/odometer.py`:** `Conflict.message` learns "a fill-up" and "a charge".
- **`src/amg/web/forms.py`:** `amount(value, unit)`.
  - Takes a positive number, up to 3 decimals.
  - Sanity limits: 100 gal, 300 kWh.
  - Messages: "Enter gallons, like 11.482."
  - The existing `quantity` allows negatives for receipt credits, so it isn't reused.
- **`src/amg/web/routes_fuel.py`:**
  - `GET /fuel/new`: the picker, or a redirect when there's one car
  - `GET /vehicles/{id}/fuel/new`
  - `POST /vehicles/{id}/fuel`
  - `GET /vehicles/{id}/fuel`
  - `GET` and `POST /fuel/{id}/edit`
  - `POST /fuel/{id}/delete`
  - Odometer checks use `odometer.conflict(..., ignore=(source, id))` when editing, as `routes_services._read` does.
  - Registered in `app.py`.
- **Templates:**
  - `fuel_form.html` (Alpine: live $/gal and the home-rate fill)
  - `fuel.html` (figures, chart and log)
  - `fuel_pick.html`
  - `_fuel_chart.html` (the SVG macro)
- **Existing templates:**
  - `base.html`: the nav link
  - `vehicle.html`: the Fuel block, and the "From a fill-up" source in the readings list
- **`src/amg/web/routes_vehicles.py`:** `_page` passes the fuel summary. A small `web/fuel_status.py` turns the engine's numbers into words ("28.6 mpg", "13.1¢ a mile"), as `status.py` does for the schedule.
- **`src/amg/web/static/app.css`:** reuses `.sheet`, `.form`, `.fieldgrid`, `.check`, `.ledger` and the tokens. New styles cover only the figures row, the chart and the unusual flag.
- **`src/amg/backup.py`:** the backup page counts fill-ups alongside cars, services and files.

## Tests
- **`tests/amg/engine/test_fuel.py`:** a hand-worked log of about 10 fills, with every stretch and figure worked out on paper in the docstring, like `test_status.py`. It covers:
  - two full fills
  - partials between two full fills (the roadmap's pin)
  - a partial before the first full fill
  - **I didn't log the one before**, on a full fill and on a partial
  - a top-off at no new miles
  - the miles-weighted average beating a naive mean
  - cost per mile leaving out a stretch with an unknown cost
  - the 12-month window
  - the unusual flag, and fewer than 3 stretches
  - the home rate
- **`tests/amg/repo/test_fuel_repo.py`:**
  - create, edit and delete
  - a fill-up shows in `odometer_points` and `latest_odometer`
  - the conflict check refuses a lower odometer (the roadmap's pin) and ignores the entry itself when editing
- **`tests/amg/web/test_fuel_pages.py`:**
  - a gas car's form asks for gallons, an EV's for kWh and home/public, both in one garage (the roadmap's pin)
  - a lower odometer gives a 422 with the message
  - saving redirects with the MPG line
  - the picker with one car and with two
  - edit and delete
  - the car page's Fuel block and "From a fill-up"
  - a fill-up moving today's estimated odometer in `status.load`
- **`tests/amg/web/test_forms.py`:** `amount`.

## Commits
1. `feat(db): fuel_logs, and fill-ups as odometer readings`: the migration, `repo/fuel.py`, the conflict wording and the repo tests
2. `feat(engine): fuel economy`
3. `feat(web): log fill-ups and charges`: the form, the picker, the nav link, edit and delete, and the car page's block and readings list
4. `feat(web): the fuel page`: the figures, the trend chart and the log
5. `docs(roadmap): phase 6`: ticks, decisions and a Done-when

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- A local run on a scratch database: a gas car and an EV, with a dozen fills each, partials and a missed one included.
  - Check the form, the fuel page and the car page at desktop width and at 360px, the latter in an iframe as before.
  - Check the readings list and today's estimate on the car page.
- **Proposed Done-when for the roadmap:**
  - the engine matches the hand-worked log in the tests
  - you log a real fill-up from your phone at the pump, and it shows on the car page and moves today's estimated odometer
