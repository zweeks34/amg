> **Approved** 2026-10-05 06:53 · **Roadmap** [Phase 10](../ROADMAP.md#phase-10--inspections-and-registration)
>
> **Built in** `b31f72a` feat(renewals): inspection and registration dates, `40099e3` feat(web): inspections and registration on the car page and garage, `48569f9` feat(alerts): remind of inspections and registration, `80d3f2d` feat(reports): inspections and registration in your data, `c1b354d` docs(roadmap): phase 10
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 10: Inspections and registration

## Context
You asked for due dates and reminders for three things:
- the safety inspection
- the emissions inspection
- the registration

They don't fit the maintenance schedule, which comes from the manual and counts miles and months from when work was last done. These three are fixed dates set by the state: the date on the sticker, or on the registration card. So they get their own small feature, and they reach you through the channels Phase 8 built:
- the car page and the garage
- ntfy pushes
- the weekly email
- the calendar file

Your receipts are from Virginia, but AMG doesn't build in any state's rules. **You type the expiry date.** AMG only suggests one, and you check it against the sticker or card.

## How it behaves for you

### The car page: a new "Inspections and registration" block, after Next up
The block has one row per kind. Each row has a status mark (the same marks the schedule uses), its name, and its status in words:

| Status | Words | Mark |
|---|---|---|
| More than 30 days left | "Expires Mar 31, 2027" | later |
| 30 days or fewer | "Expires Oct 31 · in 26 days" | due soon |
| The expiry day | "Expires today" | due soon |
| After it | "Expired Sep 30 · 5 days ago" | overdue |

"Expires" means good through that day.

**Rows not tracked yet:**
- They are quiet: "Not tracked", plus **Add the expiry date**.
- EVs get no emissions row, matching the catalogue's Emissions test type (gas and hybrid only). The row comes back if an EV already has emissions records.

**Logging a new one:** the button is **Log an inspection** for the inspections and **Log a renewal** for the registration. It opens an inline form, like the odometer's:
- **Inspected on / Renewed on:** optional; defaults to today.
- **Expires:** required.
  - The hint says "The last day it's good for. A sticker punched 9/27 is good through Sep 30, 2027."
  - It comes pre-filled with AMG's guess.
- **Cost:** optional.
- **Note:** optional.
- **Errors are shown on the field:**
  - an expiry before the done date
  - a done date in the future (`forms.day`)
  - an amount it can't read (`forms.money`)

**History:** under each row, "Earlier (3)" opens the older records: done date, expiry, cost and note, each with **Edit**. `/renewals/{id}/edit` has the same form plus **Delete**, following the fuel log's edit page.

**Archived cars:** no block and no reminders. Their records stay, and they're in the data export.

### AMG's guess for the expiry
The guess always lands on the last day of a month, because stickers and registrations run to the end of the month:
- **Inspections:** the inspection date plus the interval. Inspecting early doesn't keep the months left.
- **Registration:** the later of the old expiry and the renewal date, plus the interval. A renewal extends the old date, and a lapsed one counts from when you renewed.
- **The interval:** what your last two records show, rounded to whole years. Otherwise 12 months for safety, 24 for emissions and 12 for registration. Two- and three-year registrations get picked up after the first one.

### Receipts help, but never decide
A confirmed service can include a **State inspection** or **Emissions test** line (both already in the catalogue, and Claude tags receipts with them). If that service would move the expiry later, the row offers it: "Corner Garage did a state inspection on Sep 3, 2026: **Log it**".
- **The form opens filled in from the receipt:** the date, the line's amount, AMG's expiry guess, and a link to the service.
- **Nothing is logged until you save it.** A receipt says an inspection happened, not what the sticker says.
- **The offer goes away** once the expiry is that late, or once a record links to that service.
- **A car with no records yet** is offered its newest inspection receipt as a starting point.

### The garage card
- Anything due soon or expired gets a line with its mark, for example "Registration expires Oct 31 · in 26 days".
- Cars with no maintenance schedule show the line too.

### Reminders
- **Pushes:** one at 30 days, one at 7 days, and one the day after it expires. Each goes once, and logging the renewal starts fresh, because the new expiry date is part of the alert's key.
  - These ride in the car's daily push with any schedule jobs, still one push per car per run. The single-item title reads "Outback: Registration due soon" or "Outback: Registration expired".
  - The several-item title changes from "Outback: 2 jobs — 1 overdue, 1 due soon" to "Outback: 1 overdue, 1 due soon", because a registration isn't a job.
- **Weekly email:** due-soon ones go under Due soon and expired ones under Overdue, and the subject's counts include them.
- **Calendar file:**
  - one all-day event on each current expiry date: "Registration expires · Outback"
  - the UID is fixed per car and kind, so re-importing after a renewal moves the event rather than adding one
  - expired ones are left out, as overdue jobs are
- **Decision (recommended): these reminders don't depend on the car's alerts switch.**
  - The switch exists because job alerts are wrong while old receipts are still going in. A date you typed yourself can't be wrong that way.
  - So you'd get the Outback's registration reminders now, while its job alerts stay off.
  - Cars with alerts off are in the weekly email only when they have a date tracked. They show just those dates and the line "Maintenance alerts are off for this car."
  - Turning a car's alerts on still takes stock of its schedule jobs only.
  - The Alerts page says this under the switch.

### Not included (say if you want them)
- **The budget:** costs are recorded but not forecast. Fees are small and the budget engine is involved, so it's a later step if you want it.
- **Other dates:** no insurance, no custom kinds. Only these three.

## Data: migration `0009_renewals.sql`
```sql
CREATE TABLE renewals (
    id                INTEGER PRIMARY KEY,
    vehicle_id        INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    kind              TEXT NOT NULL CHECK (kind IN ('safety', 'emissions', 'registration')),
    done_on           TEXT,             -- inspected / renewed; NULL when only the expiry is known
    expires_on        TEXT NOT NULL,    -- good through this day
    cost_cents        INTEGER CHECK (cost_cents IS NULL OR cost_cents >= 0),
    note              TEXT NOT NULL DEFAULT '',
    service_event_id  INTEGER REFERENCES service_events (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX renewals_vehicle ON renewals (vehicle_id, kind, expires_on);
```
- **What each row is:** one inspection or renewal. A kind's current one is the latest expiry, with the highest id breaking ties.
- **`alert_log` is unchanged:**
  - the subject is `"{car}:renewal:{kind}:{expires_on}"` at level `due` (30 days) or `overdue` (expired)
  - the 7-day push uses the same subject plus `:week`, at level `due`

## Code
- **`src/amg/engine/renewals.py`** (pure):
  - `KINDS` (codes, names and default months)
  - `status(expires_on, today)`: later, due, week or expired, with the days left
  - `end_of_month`, `add_months`
  - `interval(kind, records)` and `suggest(kind, done_on, records)`
- **`src/amg/repo/renewals.py`:**
  - `create`, `update`, `get`, `delete`
  - `for_car(conn, car_id)`: records by kind, newest first
  - `inspection_services(conn, car_id, code)`: the newest confirmed services covering `state_inspection` or `emissions_test`, with the covering lines' amounts and the shop
  - `all_records(conn)` for the export
- **`src/amg/web/renewals.py`:** like `web/status.py`, it turns the engine's answer into rows. Each row has its words, mark, form defaults and receipt offer, and there's an `urgent()` for the garage and alerts.
- **`src/amg/web/routes_renewals.py`:**
  - `POST /vehicles/{id}/renewals` (create; on error, re-renders the car page with the form open, like `add_reading`)
  - `GET`/`POST /renewals/{id}/edit`
  - `POST /renewals/{id}/delete`
- **Changes to existing code:**
  - **`routes_vehicles._page`** gets the rows and the form state.
  - **`vehicle.html`** gets the block. **`renewal_form.html`** is new, for the edit page.
  - **`routes_garage` and `garage.html`** get the line.
  - **`app.css`:** a small "Inspections and registration" section reusing `.mark`, `.sheet`, `.missed__row`'s grid and `.fieldgrid`, checked at 360px.
  - **`alerts/watch.py`:**
    - `Watched` gains `renewal: bool`
    - `look()` adds renewal reminders, and adds schedule jobs only when the car's alerts are on (`CarWatch.maintenance`)
    - `take_stock` skips renewals
    - `events()` adds the expiry events
    - `push()` uses the new titles
  - **`repo/alerts.py`:** `cars_watched()`, which returns active cars with alerts on or a date tracked. `alerts/run.py` uses it.
  - **`alerts/mail.py` and `email/digest.html`:** renewals in the lists, and the line for cars with alerts off.
  - **`alerts.html`:** one sentence under the switch.
  - **`reports/export.py`:** `inspections-and-registration.csv` (Car, What, Done on, Expires, Cost, Note, Service), plus a README line.
- **No new dependencies.**

## Tests
- **`tests/amg/engine/test_renewals.py`:**
  - the status edges: 31 and 30 days, 8 and 7 days, the expiry day, the day after
  - end of month, including Jan 31 plus a month and leap years
  - suggestions: an inspection counted from its date, including an early one; a registration from its old expiry, and from the renewal date when it had lapsed
  - an interval learned from two records (2 years), and the defaults
- **`tests/amg/repo/test_renewals_repo.py`:**
  - create, update and delete
  - the current one per kind
  - the inspection-service query: confirmed only, the covering lines' cost, the newest first
- **`tests/amg/web/test_renewal_pages.py`:**
  - each status in words and marks
  - adding the first date, and logging a renewal
  - the errors (expiry before done, done in the future, a missing expiry)
  - the receipt offer: shown, pre-filled and linked; gone after logging, and gone when it wouldn't move the expiry
  - edit and delete
  - no emissions row for an EV, and no block on an archived car
  - the garage line, and everything behind the login
- **`tests/amg/alerts/`:**
  - the 30-day, 7-day and expired pushes, each once across runs
  - a new expiry alerting afresh
  - reminders going while the car's alerts are off, with no schedule jobs pushed for it
  - `take_stock` leaving renewals alone
  - the email lists, and an alerts-off car showing only its dates
  - the calendar event: fixed UID, its date moving after a renewal, expired ones left out
  - the existing push-title tests updated
- **`test_export.py`:** the new sheet and its README line.

## Commits
1. **`feat(renewals): inspection and registration dates`:** the migration, the engine, the repo and their tests.
2. **`feat(web): inspections and registration on the car page and garage`:** routes, templates, CSS and tests.
3. **`feat(alerts): remind of inspections and registration`:** watch, run, the email, the calendar, the Alerts page line and tests.
4. **`feat(reports): inspections and registration in your data`.**
5. **`docs(roadmap): phase 10`:** a new phase section with its decisions, can-go-wrong, tests-pin and done-when.

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on a scratch database in the scratchpad (never `samples/`):
  - **Seed:** a gas car and an EV. The gas car has a confirmed service with a State inspection line, a registration expiring in 20 days, and an expired emissions date.
  - **The car page at desktop and 360px:** the statuses, the receipt offer pre-filling the form, logging a renewal moving the status, and the edit page.
  - **The garage card** lines.
  - **`python -m amg.alerts.run --dry-run`**, with alerts off for the car: renewal pushes and an email listing only the dates.
  - **The calendar file** parsed.
- **Done when (yours, on the server):**
  - each car's three dates are entered and read right on the car page and garage
  - the Outback's registration reminder arrives as a push and in Monday's email while its job alerts stay off, once ntfy and Gmail are working
  - the calendar import shows the expiry dates
