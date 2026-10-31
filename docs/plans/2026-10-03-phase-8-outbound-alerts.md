> **Approved** 2026-10-03 22:09 · **Roadmap** [Phase 8](../ROADMAP.md#phase-8--outbound-alerts)
>
> **Built in** `bb37689` feat(db): alert log and the per-car switch, `7964fa4` feat(alerts): what to send, by push and email, `3840f46` feat(web): the alerts page, `dce07ca` feat(deploy): the daily alerts timer, `9d6a066` docs(roadmap): phase 8
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 8: Outbound alerts

## Context
The SPEC's third goal is "Alert me to future required maintenance". Today AMG only tells you anything when you open it. Phase 8 sends word out, using channels that work off the VPN:
- a phone push (ntfy) when a job comes due soon or goes overdue
- a weekly email digest
- the schedule as a calendar file

The gap engine already decides due soon (30 days or 1,000 mi) and overdue (`engine/schedule.py`). Phase 7's budget gives each job a price. This phase decides what's new since the last run, sends it once, and keeps a record.

**Your receipts aren't all in yet.** Alerts are switched on **per car**, and switching on takes stock without sending (below). Keep the Outback's alerts off until its history is complete: while old receipts are still going in, a job can move between "never done" and "last done 2019" and look newly overdue.

**Calendar, changed from the roadmap:** you use Google Calendar, and Google's servers can't reach a VPN-only app, so a subscribed `/calendar/<token>.ics` feed would never update. Instead, the calendar is an `.ics` **file** that you import. It's attached to the weekly email and can be downloaded from the new Alerts page. That drops the token and its "rejects a wrong value" test. The roadmap gets this edit.

## How it behaves for you

### Daily, at 8:00 (a systemd timer on LXC 302)
- For each car with alerts on, AMG runs the schedule and finds jobs that are newly **due soon** or newly **overdue**.
- **One push per car per run**, so a bad day doesn't buzz six times:
  - one job: "Outback: oil and filter is overdue", with "1,200 mi overdue · due Sep 3 · ~$85"
  - several: "Outback: 3 jobs need doing", one line each
  - tapping it opens the car's page
  - overdue pushes are high priority; due-soon pushes are normal
- **Once each:**
  - one "due soon" and one "overdue" push for each job, each time it comes round
  - a job that went straight to overdue doesn't get a late "due soon" after it
  - doing the job starts its next round, so the next one is told about again
  - a missed occurrence rolls straight into the next one without a second push for the same undone job; the weekly email still shows it
- **What counts as the same job:** its service types and action, as Phase 7's prices do. Confirming a new schedule doesn't re-alert everything.
- **When a send fails** (no internet, a wrong setting), it's recorded, and the next day's run tries again.
- **The timer catches up.** If the container was off at 8:00, the run happens at boot.

### Weekly email (Mondays, or the first run after Monday that week)
- **Subject** like "AMG: 2 overdue, 1 due soon", or "AMG: nothing due this week". It always goes out, so a missing email tells you something's wrong.
- **For each car with alerts on:**
  - overdue and due-soon jobs with when and cost
  - how many were missed earlier
  - the next three jobs coming up
  - the budget line: "~$1,420 of maintenance in the next 12 months: put aside $118 a month"
- **Receipts waiting:** "3 receipts to check", if any.
- **Links** go to `http://amg.home.arpa`, so they open when you're home or on the VPN.
- **Format:** plain text with a simple HTML version.
- **The calendar file is attached** (`amg-maintenance.ics`).

### The calendar file
- **Events:** an all-day event on each job's due date for the next 12 months, for example "Oil and filter · Outback". Its description says "by Dec 12 or at 18,000 mi, whichever comes first · ~$85", and that dates for mileage-based jobs are estimated from your driving.
- **Overdue jobs are left out:** a file you import can't keep them on today's date.
- **Importing into Google Calendar:**
  - Import it into a separate calendar (say "Car maintenance") through Settings → Import & export.
  - Each event keeps the same ID between files ("the next oil change on the Outback"), so a later import should update the date rather than add a copy.
  - I can't confirm how Google treats a re-import. If it adds copies, delete that calendar and import a fresh file. That's a step in your done-when.

### The Alerts page (`/alerts`, a new footer link)
- **Push:** "Sending to ntfy.sh/amg-…" with **Send a test push**, or "Not set up: add AMG_NTFY_TOPIC to .env".
- **Email:** "Weekly on Mondays to you@gmail.com" with **Send a test email**, or "Not set up".
- **Cars:** each active car with **Turn on alerts** / **Turn off alerts**.
  - Turning on records what's already due soon or overdue as known, without sending it. The page says so: "AMG starts watching from now: what's already overdue is in the weekly email, not pushed."
- **Calendar:** **Download the calendar (.ics)** and how to import it.
- **Last run:** "Today 8:00: 1 push, no email due". This shows the timer is alive.
- **Recently sent:** the last 20 alerts, failures with their reason.

### On the server
- `amg alerts --dry-run` prints what would be sent and records nothing.
- `amg alerts` runs it now.
- `systemctl list-timers amg-alerts` shows the next run, and `journalctl -u amg-alerts` its output.

## Settings (`.env`, documented in `.env.example`)
- `AMG_BASE_URL`: the address links point to. Default `http://amg.home.arpa`.
- **ntfy:**
  - `AMG_NTFY_TOPIC`: no topic, no pushes.
  - `AMG_NTFY_URL`: default `https://ntfy.sh`.
  - `AMG_NTFY_TOKEN`: optional, for a protected topic.
  - ntfy.sh topics are public to anyone who knows the name, so the doc says to use a long random one. Pushes carry car and job names through ntfy's server.
- **Email:**
  - `AMG_SMTP_USER` and `AMG_SMTP_PASSWORD`: your Gmail address and a Gmail **app password**, which needs 2-Step Verification. Neither set, no email.
  - `AMG_SMTP_HOST` (`smtp.gmail.com`), `AMG_SMTP_PORT` (`587`, STARTTLS; `465` uses SSL).
  - `AMG_EMAIL_TO`: defaults to the user.
- The digest day is fixed at Monday, and the run time lives in the timer.
- These are read per call (`config.py`), so tests can redirect them.
- **No new dependencies:** `urllib.request` (ntfy's JSON publish), `smtplib`, `email` and `ssl`.

## Data: `src/amg/migrations/0008_alerts.sql`
- `vehicles.alerts INTEGER NOT NULL DEFAULT 0`: the per-car switch.
- **New table `alert_log`:**
  - columns: `id`, `channel` (`ntfy` or `email`), `subject`, `level` (`due`, `overdue` or `digest`), `vehicle_id` (CASCADE), `title`, `body`, `outcome` (`sending`, `sent`, `known`, `failed`), `error`, `created_at`, `updated_at`
  - **`subject` for a job:** `"{vehicle_id}:{codes}:{action}:{since}"`. `since` is the last service that did the job (`s123`), or `new`. That is what "occurrence" means here.
  - **`subject` for a digest:** `digest:2026-W40`.
  - **`UNIQUE (channel, subject, level)`:** a run claims a row (`sending`) before it sends. Two runs at once can't send the same alert, and only `failed` rows are tried again.
- The last run's time and summary go in the existing `settings` table (`alerts_last_run`).

## Code
- **`src/amg/repo/alerts.py`** (all the SQL):
  - `cars_on`, `switch`
  - `claim(conn, channel, subject, level, …) -> bool`
  - `mark(conn, id, outcome, error)`, `known(conn, …)`
  - `logged(conn, channel) -> {(subject, level)}`
  - `recent(conn, limit)`
  - `last_run` / `set_last_run` (through `repo/settings`)
- **New package `src/amg/alerts/`:**
  - **`watch.py`:** what's true for a car now.
    - `jobs(conn, car, today) -> list[Watched]`: subject, level, name, when and cost. It reuses `web/status.load` and `when`, and `web/budget.load(...).item_costs()`.
    - `new(watched, logged)`: what to push, with "overdue covers due" applied.
    - `take_stock(conn, car, today)`: used when a car is switched on.
  - **`ntfy.py`:**
    - `Push(title, message, priority, click)`
    - `send(push, settings)`: a JSON POST, with a bearer token if set and a 15 s timeout.
  - **`mail.py`:** `digest(cars, today, …) -> EmailMessage` (text, HTML and the `.ics` attachment), `send(message, settings)`.
  - **`ics.py`:** pure. `calendar(events) -> str`, RFC 5545: CRLF endings, 75-octet folding, escaped text, `VALUE=DATE` all-day events, stable UIDs (`amg-{vehicle}-{codes}-{action}-{n}@amg`).
  - **`run.py`:** `main(argv)`, as `python -m amg.alerts.run [--dry-run]`.
    - It migrates first, as the CLI does.
    - It skips a channel that isn't set up and says so.
    - It exits 1 if any send failed, so systemd marks the run failed.
- **`src/amg/cli.py`:** `alerts [--dry-run]` delegates to `alerts.run.main`, so `amg alerts` works as the app user.
- **`src/amg/config.py`:** `base_url()`, `ntfy()`, `smtp()`. These return `None` when the channel isn't set up.
- **Web:**
  - **`src/amg/web/routes_alerts.py`:**
    - `GET /alerts`
    - `POST /alerts/cars/{id}` (switch)
    - `POST /alerts/test-push`, `POST /alerts/test-email`: send now and show the result, or the error, on the page
    - `GET /alerts/calendar.ics`, behind the login like every page
  - **Templates:** `alerts.html` is new; `base.html` gets a footer link. The page reuses `.sheet`, `.notice` and `.btn`. It's a small "Alerts" CSS section, checked at 360px.
- **Deploy:**
  - `deploy/amg-alerts.service`: `Type=oneshot`, `User=amg`, `AMG_DATA_DIR`, running `/opt/amg/venv/bin/python -m amg.alerts.run`.
  - `deploy/amg-alerts.timer`: `OnCalendar=*-*-* 08:00`, `Persistent=true`.
  - `scripts/deploy.sh` installs both when they change and runs `systemctl enable --now amg-alerts.timer`.
  - `docs/DEPLOY-proxmox.md` gets a new "Alerts" section:
    - the ntfy app and topic
    - the Gmail app password
    - `.env`, then restart
    - the test buttons
    - `amg alerts --dry-run`, the timer and the log
    - keeping a car off until its receipts are in

## Tests
- **`tests/amg/alerts/test_watch.py`** (a car built through the repo, with `today` moved forward):
  - a job coming due pushes once, and a second run the same day or the next pushes nothing (the roadmap's pin)
  - due soon, then overdue, sends a second push
  - straight to overdue pushes once, with no due-soon after it
  - doing the job starts a new round that alerts again
  - a new schedule with the same jobs doesn't re-alert
  - switching on takes stock without sending
  - a car switched off sends nothing
  - several new jobs make one push
  - a failed send is tried again the next run
  - a `sending` row from a run that died isn't sent twice
- **`test_ics.py`:**
  - the file parses (a small unfolding parser in the test, the roadmap's pin)
  - folding at 75 octets, escaping `,;\` and newlines
  - UIDs stable between two runs
  - overdue jobs and anything past 12 months are left out
- **`test_mail.py`** (`smtplib.SMTP` faked):
  - the digest's subject and sections
  - the text and HTML parts, and the `.ics` attachment
  - STARTTLS and login with the settings, and SSL on 465
  - once per ISO week, on or after Monday
  - "nothing due" is still sent
  - a failure is logged and tried again
- **`test_ntfy.py`** (`urlopen` faked): the JSON body, priority, click link and bearer token.
- **`test_run.py`:**
  - `--dry-run` prints and records nothing
  - an unset channel is skipped with a message
  - exit code 1 on a failure
  - `alerts_last_run` is written
- **`tests/amg/web/test_alerts_page.py`:**
  - channel status, set up and not
  - switching a car on takes stock
  - the test buttons (faked) show the result or the error
  - the `.ics` download needs a session

## Commits
1. `feat(db): alert log and the per-car switch`: the migration, `repo/alerts.py` and repo tests
2. `feat(alerts): what to send, by push and email`: `alerts/*`, config, CLI and tests
3. `feat(web): the alerts page`: the routes, template, footer link, CSS and tests
4. `feat(deploy): the daily alerts timer`: the units, `deploy.sh`, `.env.example` and the deploy doc
5. `docs(roadmap): phase 8`:
   - ticks
   - the calendar-file change, and the Decisions row updated to match
   - per-car switch and take-stock
   - can-go-wrong, tests-pin and done-when

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- **A local run on a scratch database** (`AMG_DATA_DIR` in the scratchpad), with two cars and a few jobs due and overdue:
  - `AMG_NTFY_URL` points at a tiny local HTTP server in the scratchpad that records what it's sent, so nothing leaves the PC.
  - Run `python -m amg.alerts.run --dry-run`, then a real run (pushes captured), then again to show nothing is sent twice.
  - Email is checked with `--dry-run` and the faked-SMTP tests. I won't send a real email or push: the Gmail password and topic are yours and live only in the server's `.env`.
  - The Alerts page at desktop width and 360px.
- **Proposed done-when (yours, on the server):**
  - **Test sends:** with ntfy and Gmail set in `.env`, **Send a test push** reaches your phone and **Send a test email** reaches your inbox.
  - **Dry run:** `amg alerts --dry-run` lists what it would send.
  - **Timer:** after the next 8:00 run, `systemctl list-timers amg-alerts` shows it ran and the Alerts page shows the last run.
  - **Calendar:** the `.ics` imports into a Google calendar, and importing a second file updates the events rather than duplicating them. If it duplicates, we note that the way to refresh is to replace the calendar.
  - **Weekly email:** the first Monday digest arrives.
