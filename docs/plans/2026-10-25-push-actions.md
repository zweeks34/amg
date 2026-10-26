> **Approved** 2026-10-25 20:32 · **Roadmap** [Phase 8](../ROADMAP.md#phase-8--outbound-alerts)
>
> **Built in** `57df82c` feat(alerts): say each job's action in the pushes, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The dry run's test pinned the push's lines too** (`tests/amg/alerts/test_run.py`), so it gains the word as well.
> - **Checked on the scratch garage** by building its pushes with `watch.push` and printing them, with nothing sent:
>   - "Hatch: 2 overdue", with "INSPECT Brakes: 5,323 mi overdue · due May 17" and "REPLACE Cabin air filter: …"
>   - each job alone as "Hatch: INSPECT Brakes overdue" and "Hatch: REPLACE Cabin air filter overdue"
>
> The plan below is as it was approved; it isn't edited afterwards.

# The action words in the ntfy pushes

## Context
The weekly email now says **REPLACE**, **INSPECT** or **PERFORM** before each schedule job (`df4eb09`). The ntfy pushes don't yet: "Outback: Oil and filter due soon". They should, in the same plain-text form the email's text part uses.

**How the alerts log works:** it remembers what it has sent by job and level (`alerts.logged`: subject and level), not by the words. Each sent alert's line is only stored as its title, which the Alerts page lists under recent alerts. So the words can change safely: nothing is pushed twice. The logged title gets the word too, so that list matches what was pushed.

## How it looks
- **One job:** the title says it.
  ```
  Outback: REPLACE Oil and filter due soon
  by Jul 1 · ~$80
  ```
- **Several things at once:** each job line in the message, as in the email.
  ```
  Outback: 1 overdue, 1 due soon
  REPLACE Oil and filter: overdue since Jul 1
  Registration: expires Jun 30 · in 20 days
  ```
- **On the Alerts page:** "Outback · REPLACE Oil and filter: by Jul 1".
- **No word for anything else:** registrations and inspections, recalls, warranties ending and a reading wanted read as now.

## Code (one commit: `feat(alerts): say each job's action in the pushes`)
- **`alerts/watch.py`:**
  - `action_word(action)` gives `"REPLACE "` from the shared `ACTION_WORDS`, or `""`. It moves here from `mail.py`'s `_word`, so the email and the pushes share it.
  - `Watched` gains `said`: `action_word(self.action) + self.line`.
  - `push()`:
    - one job: the title becomes `f"{name}: {action_word(job.action)}{job.name} {job.state}"`
    - several: the message joins each `j.said`
  - `take_stock()` logs `job.said`.
- **`alerts/run.py`:** `alerts.claim(...)` logs `job.said`.
- **`alerts/mail.py`:** uses `job.said` and `watch.action_word` in place of `_word`. The email reads the same as now.

## Tests
- **`tests/amg/alerts/test_watch.py`:**
  - the titles become "Outback: REPLACE Oil and filter due soon" / "… overdue" and "Outback: REPLACE Wiper blades overdue"
  - the multi-job message is "REPLACE Oil and filter: overdue since Jul 1\nREPLACE Wiper blades: by Sep 1"
  - a sent job's logged title has the word
- **`tests/amg/alerts/test_renewal_alerts.py`:** the mixed push's lines become "REPLACE Oil and filter: by Jul 1" and "Registration: expires Jun 30 · in 20 days". The registration-only pushes are unchanged.
- **Recall, warranty and reading pushes:** their tests are unchanged.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the pushes say each job's action`)
- **`docs/ROADMAP.md`, Phase 8:** the weekly-email action item becomes "Each job's action in the weekly email and the pushes". It covers the push title, the lines of a push with several, and the Alerts page's list.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-push-actions.md` with the header, and an index row. Its commit and an As built note are added when it ships.

## Not included
- **The calendar file's event names.**

## Verification
- **Tests:** `pytest` passes.
- **The scratch garage** (`scratchpad/p16`, made-up car): `watch.push()` for its two overdue jobs, rendered to text without sending, reads "Hatch: 2 overdue", then "INSPECT Brakes: …" and "REPLACE Cabin air filter: …". No real push is sent and nothing outside is contacted.
- **After you deploy (yours):** the next push for a job says what to do. The Alerts page's test push is unchanged.
