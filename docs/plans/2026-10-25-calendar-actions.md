> **Approved** 2026-10-25 20:39 · **Roadmap** [Phase 8](../ROADMAP.md#phase-8--outbound-alerts)
>
> **Built in** `5997dd8` feat(alerts): say each job's action in the calendar file, and the docs commit that adds this record
>
> **As built:** As planned. Checked on the scratch garage by building its calendar file before and after the change and writing it to a scratch file, with nothing sent. Its six events went from "Brakes · Hatch" to "INSPECT Brakes · Hatch", "PERFORM Tire rotation · Hatch", "REPLACE Engine oil and filter · Hatch" and so on. Each kept its UID and day.
>
> The plan below is as it was approved; it isn't edited afterwards.

# The action words in the calendar file

## Context
The weekly email and the pushes now say **REPLACE**, **INSPECT** or **PERFORM** before each schedule job (`df4eb09`, `57df82c`). The calendar file's job events don't yet: "Oil and filter · Outback". Each should say what to do, in the same plain-text form: "REPLACE Oil and filter · Outback".

**Re-importing is safe.** Each job event's UID already carries the job's action (`amg-{car}-{codes}-{action}-{n}@amg`), so the UIDs don't change. Every file also carries a higher `SEQUENCE`, so importing a new file renames your existing events rather than adding a second set.

## How it looks
```
Jul 1   REPLACE Oil and filter · Outback
Sep 1   INSPECT Brakes · Outback
Oct 31  Registration expires · Bolt        (unchanged: not a schedule job)
```
- **Where the file comes from:** both the weekly email's attachment and the Alerts page's download (`watch.events`, `alerts/ics.py`).
- **Only job events change.** An inspection's or registration's expiry reads as now.
- **The description** ("Due at 45,000 mi or by this date…", "About $80.") is unchanged.

## Code (one commit: `feat(alerts): say each job's action in the calendar file`)
- **`alerts/watch.py`:** in `events()`, a job's summary becomes `f"{action_word(item.action)}{item.name} · {car['name']}"`, using the shared `action_word` added with the pushes.

## Tests
- **`tests/amg/alerts/test_ics.py`:**
  - the next 12 months read "REPLACE Oil and filter · Outback" and "REPLACE Wiper blades · Outback"
  - the UID is unchanged (`…-engine_oil+oil_filter-replace-1@amg`)
- **`tests/amg/alerts/test_renewal_alerts.py`:**
  - the expiry events are unchanged
  - the Alerts page's every-job file has "REPLACE Oil and filter · Outback"
- **`tests/amg/web/test_alerts_page.py`:** the download has "SUMMARY:REPLACE Wiper blades · Outback".
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the calendar file says each job's action`)
- **`docs/ROADMAP.md`, Phase 8:** the action item becomes "Each job's action in the weekly email, the pushes and the calendar file". It adds the event title, and that a re-import renames the events rather than adding new ones.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-calendar-actions.md` with the header, and an index row. Its commit and an As built note are added when it ships.

## Verification
- **Tests:** `pytest` passes.
- **The scratch garage** (`scratchpad/p16`, made-up car): its calendar file, built with `watch.events` and `ics.calendar` and written to a scratch file, has "INSPECT"/"REPLACE"/"PERFORM" summaries with the same UIDs as before. Nothing is sent and nothing outside is contacted.
- **After you deploy (yours):** download the file from the Alerts page and import it again. The events you imported before are renamed, not doubled.
