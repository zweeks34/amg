> **Approved** 2026-10-25 19:49 · **Roadmap** [Phase 13](../ROADMAP.md#phase-13--issues-and-the-sheet-for-the-shop)
>
> **Built in** `895a998` feat(issues): say each due job's action on the sheet for the shop, and the docs commit that adds this record
>
> **As built:** As planned. Checked in the browser on the scratch car's sheet, with made-up data:
> - **INSPECT** Brakes and **REPLACE** Cabin air filter, with the names lined up
> - at 360px (the word on the name's line, the due line beneath, no sideways scroll)
> - with the print rules applied (plain black ink)
> - in dark mode
>
> The plan below is as it was approved; it isn't edited afterwards.

# The action words on the For the shop sheet

## Context
Next up now stamps each job R, I or P (`08f6f5a`). The **For the shop** sheet's "Due now" list, which you show on your phone or print for the shop, still names each job without saying what to do. For a mechanic a word reads better than a letter, so each job there gets its action as a word: **Replace**, **Inspect** or **Perform**. The rows already carry the action (`status.next_up` gives each one `action`), and the words are the shared `action_words` from `web/templating.py`.

## How it looks
```
Due now
▲  REPLACE  Engine oil and filter        4,800 mi overdue · due Apr 20
▲  INSPECT  Brakes                       5,160 mi overdue · due May 17
◐  PERFORM  Tire rotation                in 300 mi · by Nov 12
```
- **The word** is a small capitalised label before the job's name, in the display face the sheet's headings use, in ink.
- **The three words are all seven letters,** and the label has a fixed width, so the names line up under each other.
- **On paper** it's plain black text, so it prints in black and white.
- **On a phone** the word stays on the name's line and the due line wraps beneath, as now.
- **A screen reader** reads it as "Replace Engine oil and filter".
- **Only "Due now" changes.** "Under warranty", "Please look at" and "Recommended before" aren't schedule jobs.

## Code (one commit: `feat(issues): say each due job's action on the sheet for the shop`)
- **`templates/for_the_shop.html`:** in "Due now", `shopsheet__what` becomes `{% if job.action %}<span class="shopsheet__action">{{ action_words[job.action] }}</span> {% endif %}{{ job.name }}`.
- **`static/app.css`:** `.shopsheet__action`, an inline-block `min-width` of about 4.5rem, `font: 600 0.8125rem/1 var(--display)`, uppercase with the eyebrow's letter-spacing.

## Tests
- **`tests/amg/web/test_issue_pages.py`:** the sheet's due-now rows carry the word before the name. On the steady car, the overdue Cabin air filter and Engine oil and filter read `Replace` before their names.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the sheet for the shop says each due job's action`)
- **`docs/ROADMAP.md`, Phase 13:** an item "(added after the phase shipped, 2026-10-25)": "Due now" says each job's action, Replace, Inspect or Perform.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-shop-sheet-actions.md` with the header, and an index row. Its commit and an As built note are added when it ships.

## Not included
- **The garage card's "Next:" line, the weekly email's job list, and the ntfy pushes.**

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch car's For the shop sheet (`scratchpad/p16`, made-up data):
  - the words line up before the names
  - at 360px wide
  - in dark mode
  - in the print preview's layout (print media rules applied)
- **After you deploy (yours):** the Elantra's sheet says Replace, Inspect or Perform before each due job.
