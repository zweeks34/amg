> **Approved** 2026-10-25 20:22 · **Roadmap** [Phase 8](../ROADMAP.md#phase-8--outbound-alerts)
>
> **Built in** `df4eb09` feat(alerts): say each job's action in the weekly email, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **Checked by rendering the scratch garage's email to files**, not with `amg alerts --dry-run`. A dry run also asks NHTSA for recalls, and rendering called nothing outside and sent nothing.
>   - The plain text read "• INSPECT Brakes: 5,323 mi overdue · due May 17", "• REPLACE Cabin air filter: …" and, in Coming up, "• PERFORM Tire rotation: …".
>   - The HTML part was opened in the browser, on the desktop and at phone width (no sideways scroll).
>
> The plan below is as it was approved; it isn't edited afterwards.

# The action words in the weekly email

## Context
The garage card, the For the shop sheet and next up all say what to do to each job now. The weekly email's lists don't yet: "Overdue · Oil and filter · overdue since Jul 1". Its "Overdue", "Due soon" and "Coming up" lists should say **Replace**, **Inspect** or **Perform** before each schedule job, in both of the email's versions, the HTML and the plain text.

**Where the action is today:**
- "Coming up" rows are `next_up` rows, which already carry `action`.
- "Overdue" and "Due soon" are `alerts/watch.Watched`, which doesn't. Those lists also hold inspections and registrations (`kind="renewal"`), which have no action.

`Watched.line` also feeds the ntfy pushes and the alert log (`alerts/watch.py`, `alerts/run.py`), so it stays as it is, and the word is added in the email alone.

## How it looks
- **HTML**, as on the garage card: a small capitalised word in ink before the name.
  ```
  OVERDUE
  • REPLACE Oil and filter · overdue since Jul 1 · ~$80
  • Emissions inspection · expired Jun 1 · 9 days ago
  COMING UP
  • INSPECT Brakes · in 4,300 mi · ~Feb 2027
  ```
- **Plain text**, with the word in capitals:
  ```
  Overdue
    • REPLACE Oil and filter: overdue since Jul 1 · ~$80
  ```
- **No word for anything that isn't a schedule job:** inspections and registrations, open recalls, warranties ending, a reading wanted, and the shop's recommendations.

## Code (one commit: `feat(alerts): say each job's action in the weekly email`)
- **`alerts/watch.py`:**
  - `Watched` gains `action: str | None = None` ("a schedule job's: replace, inspect or perform").
  - `look()` passes `action=item_status.item.action` for schedule jobs. Renewals and notices keep `None`.
- **`alerts/mail.py`:**
  - A small `_word(action)` gives `"REPLACE "` from the shared `ACTION_WORDS` (`web/templating.py`), or `""`.
  - `text()` puts it before each job's line (`f"  • {_word(job.action)}{job.line}"`) and before each coming-up row.
- **`templates/email/digest.html`:**
  - In the job lists and "Coming up": `{% if job.action %}<span style="font:700 12px/1 'Arial Narrow',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase">{{ action_words[job.action] }}</span> {% endif %}` before the name.
  - The styles are inline, as mail clients need, and in the face the email's headings already use.

## Tests (`tests/amg/alerts/test_mail.py`)
- **The plain text:** the existing digest test's lines gain the word, "  • REPLACE Oil and filter: overdue since Jul 1 · ~$80", likewise "REPLACE Wiper blades" and "REPLACE Cabin air filter" in Coming up.
- **The HTML part:** it has the word before "Oil and filter".
- **The renewal, recall and warranty email tests** stay as they are: none of their lines gains a word.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the weekly email says each job's action`)
- **`docs/ROADMAP.md`, Phase 8:** an item "(added after the phase shipped, 2026-10-25)" saying the weekly email puts the job's action before each schedule job, in both of its parts.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-email-actions.md` with the header, and an index row. Its commit and an As built note are added when it ships.

## Not included
- **The ntfy pushes and the calendar file:** not asked for. A push's line is also how the alert log records it.

## Verification
- **Tests:** `pytest` passes.
- **The scratch garage** (`scratchpad/p16`, made-up car), with `AMG_DATA_DIR` pointed at it:
  - `amg alerts --dry-run` (sends nothing) shows the plain text with the words
  - the HTML part, rendered to a scratch file and opened in the browser, at desktop and phone widths
- **After you deploy (yours):** next Monday's email says what to do to each job.
