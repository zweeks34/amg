> **Approved** 2026-10-02 21:21 · **Roadmap** [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `d0485d6` feat(engine): odometer model, `e33af42` feat(engine): gap engine, `6bbe297` feat(web): next up, the interval chart, garage badges and mark as done, `05b7283` docs(roadmap): tick off phase 5
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 5: Gap engine, interval chart, dashboard

## Context
Phase 4 is done: the Outback's schedule is in use on the server. Phase 5 answers the app's core question: **what have I missed, and what's next?** It needs four pieces:
- an odometer model
- a gap engine that walks each schedule item against your confirmed services
- the interval chart. Phase 0 designed it on `/design` with sample data; this phase gives it real data.
- a "next up" list, garage badges, and a way to mark a missed item as done without a receipt

### Decisions you made
- **The next one is due from when it was last done.**
  - An occurrence is **missed** only when the following one has also fallen due with nothing done.
  - A service after the due point, but before the next one falls due, counts as **done late**.
  - Example, oil every 6,000 mi: done at 13,500, so the next is due at 19,500. If nothing is done until 27,000:
    - 19,500 is missed, because 25,500 also fell due with nothing done.
    - 25,500 counts as done late, at 27,000.
    - The next one is due at 33,000.
  - The earlier preview also showed 25,500 as missed. That line was wrong.
- **A multi-point or state inspection counts for every *inspect* item on that visit.** It never counts for a replacement.

## How it behaves for you
- **Car page, top.**
  - "Odometer ~64,300 mi, estimated today", then **Next up**:
    - overdue items first, most overdue at the top
    - then items due soon
    - then the next few later ones
  - Each entry shows its mark, its name, and when it's due:
    - "1,200 mi overdue"
    - "in 700 mi · by Nov 12"
    - "~Jul 2027"
  - A line underneath: "5 missed in the past".
  - Overdue and missed items get a **Mark as done** button.
- **The interval chart** (the `/design` chart with real data).
  - One row per schedule item that applies to the car, grouped by category.
  - Marks:
    - ● done, linking to that service
    - ✕ missed
    - ▲ overdue
    - ◐ due soon
    - ○ later
  - An ink line at today's estimated odometer.
  - On a phone, Next up comes first and **Show the chart** opens the chart. It scrolls sideways with a sticky item column; that styling already exists.
- **The garage.** Each car's card adds what's next and a count with the marks, e.g. "2 overdue · 1 due soon · 5 missed".
- **Mark as done** (no receipt).
  - A short form: when, the odometer (optional) and a note.
  - It records a service with source `attested` and one line, "Engine oil, done, no receipt". The line covers the item's service types with its action.
  - That fills the gap. It shows in the history as "No receipt", and deleting it undoes it.
- **No odometer readings.** Items with a months interval are judged on months alone. An item with only a mileage interval says it needs a reading, with a link to add one.

## Engine: pure functions in `src/amg/engine/`
**`odometer.py`**: `Odometer(points, in_service)`
- **Points:**
  - From the `odometer_points` view (`repo/odometer.points`).
  - Plus (in-service date, 0 mi) when the in-service date is known.
  - Several readings on one day count as the highest.
- **`miles_on(day)`:**
  - Between readings: a straight line between them.
  - After the last reading: projected at the recent rate.
  - Before the first reading: extended back along the first segment, never below 0.
- **`day_at(miles)`:** the inverse, i.e. when the car did or will reach a mileage.
- **`rate()`:** miles per day.
  - Uses readings from the last 12 months when they span at least 60 days, otherwise the whole history.
  - `None` with fewer than two points.
- **No readings:** every function returns `None`.

**`schedule.py`**
- **Inputs:**
  - `Item`
  - `Service(id, day, miles, coverage {code: {actions}})`
  - `Car(in_service, acquired_on, acquired_miles, severe)`
- **Outputs:**
  - `Occurrence(due_day, due_miles, status, service_id, late)`
  - `ItemStatus`
- **`in_effect`** moves here from `ingest/schedule_drafts.py`, which imports it back.
- **`meets(service, item)`:**
  - The service must share a service type with the item.
  - An inspect item is met by any action on that type; a replace or perform item needs replace or perform.
  - A `multipoint_inspection` or `state_inspection` line meets every inspect item.
- **`walk(item, services, odometer, car, today, until)`:**
  - **Start:** the in-service date at 0 mi, else the acquisition, else the first record.
  - **Due point:** start + (first-due or interval), whichever of miles and months comes first. A mileage is turned into a date with the odometer model.
  - **Done:** the first matching service after the start, if it comes before the following occurrence falls due. It's late if it comes more than 10% of the interval after the due point. The next is counted from that service.
  - **Missed:** nothing matched and the following occurrence has already fallen due. If it fell due before you had the car, it's marked "before you had it" and is neither done nor missed. The next is counted from the due point.
  - **Overdue:** the due point has passed, but the following occurrence hasn't fallen due yet.
  - **Due soon:** due within 30 days or 1,000 mi.
  - **Later:** anything further off.
  - It keeps projecting later occurrences up to `until`, for the chart.
- **`assess(items, services, odometer, car, today)`:** one status per item that applies to the car.
- **Constants:** `DUE_SOON_DAYS = 30`, `DUE_SOON_MILES = 1_000`, `LATE_TOLERANCE = 0.10`.

## Glue
- **`repo/services.py`:** `coverage(conn, vehicle_id)` returns confirmed services with their coverage, in one query.
- **`web/status.py`** builds what the pages show.
  - It loads the data, runs the engine, and builds:
    - the chart dict that `_chart.html` already takes
    - the Next up rows
    - the garage summary
  - **Chart width:** from today's odometer and the furthest due point shown, rounded to neat ticks.
  - It also writes the "when" words.
- **`_chart.html`:**
  - Done marks link to their service.
  - In `next_up`, the cost becomes optional (phase 7 fills it in), and each row can show **Mark as done**.
- **`routes_vehicles.py`:** the car page gets the status.
- **`routes_garage.py`:** each car card gets its summary.
- **New routes:**
  - `GET /vehicles/{id}/schedule-items/{item}/done` shows the Mark as done form.
  - `POST` to the same URL records it, through the existing `services.create_event`.
- **`app.css`:** Next up actions, garage card badges, and the "Show the chart" toggle. These reuse the existing `.mark` and `.ichart` styles.

## Tests
- **`tests/amg/engine/test_odometer.py`:**
  - the straight line between readings
  - projection at the recent rate
  - the in-service anchor
  - one reading, and no readings
  - several readings on one day
- **`tests/amg/engine/test_schedule.py`:**
  - **Whichever comes first:** months first on a low-mileage car, miles first on a high-mileage one.
  - **First-due offsets:** first at 7,500, then every 15,000.
  - **Acquisition cutoff:** nothing is missed before you had the car.
  - **Tolerance edge:** exactly 10% late is on time; anything more is late.
  - **No readings:** judged on months only; a mileage-only item needs a reading.
  - **What meets what:**
    - an inspection doesn't meet a replace item
    - a replacement meets an inspect item
    - a multi-point inspection meets inspect items only
  - **Early, missed and one-off:**
    - a service done early resets the count
    - the corrected oil example above
    - a one-off item
  - **Normal and severe:** only the items that apply are judged.
- **A hand-checked car.** A fixture car with about 10 services and 5 items, with every mark on its chart written out by hand in the test. The chart builder must match it exactly.
- **Web:**
  - Next up's order and wording
  - the chart's marks and links
  - Mark as done turning a missed mark into done
  - the garage counts

## Local check before the UI
I'll run the engine on the 14 sample receipts against the trial's Outback schedule, locally with nothing committed. Then I'll check the gaps it finds are believable and report back.

## Commits
1. `feat(engine): odometer model`
2. `feat(engine): gap engine`
3. `feat(web): next up, interval chart and garage badges`
4. `feat(web): mark a missed item as done`
5. `docs(roadmap): phase 5`

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- A local run on a scratch database seeded with the sample receipts and the schedule.
  - Screenshots at desktop width and at 390px, the latter in an iframe.
- Then you deploy and check the Outback's chart against your receipts. That's Phase 5's done-when.
