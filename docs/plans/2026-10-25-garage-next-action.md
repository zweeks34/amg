> **Approved** 2026-10-25 20:17 · **Roadmap** [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `a2f8204` feat(garage): say the next job's action on each car's card, and the docs commit that adds this record
>
> **As built:** As planned. Checked in the browser on the scratch garage, with made-up data:
> - the card reads "Next: INSPECT Brakes 5,323 mi overdue · due May 17", on the desktop and at 360px (no sideways scroll), in dark mode too
> - the For the shop sheet's word kept its look, with its names still lined up
>
> The plan below is as it was approved; it isn't edited afterwards.

# The action word on the garage card's Next line

## Context
The For the shop sheet now says each due job's action as a word (`7ba5039`). The garage card's "Next:" line still names the job alone: "Next: Cabin air filter · 1,283 mi overdue". It should say what to do, the same way: "Next: **REPLACE** Cabin air filter". The line comes from `status.summary`, whose `next` is the first `next_up` row, so it already carries `action`. The words are the shared `action_words` from `web/templating.py`.

## How it looks
```
▲ Next: REPLACE Cabin air filter  1,283 mi overdue · due Sep 20
```
- **The word** looks as it does on the For the shop sheet: small, capitalised, in the display face, in ink, between "Next:" and the name.
- **On a narrow card** the line wraps as it does today, and the word stays with the name.
- **A screen reader** reads it as "Next: Replace Cabin air filter".

## Code (one commit: `feat(garage): say the next job's action on each car's card`)
- **`static/app.css`:** the For the shop sheet's word styling moves to a shared `.actword` class (display face, 600, 0.8125rem, uppercase, 0.1em letter-spacing). `.shopsheet__action` keeps only what lines the names up (`display: inline-block; min-width: 4.5rem`).
- **`templates/for_the_shop.html`:** the word's span becomes `class="actword shopsheet__action"`. It looks the same as now.
- **`templates/garage.html`:** in the "Next:" line, `{% if s.next.action %}<span class="actword">{{ action_words[s.next.action] }}</span> {% endif %}` goes before `{{ s.next.name }}`.

## Tests
- **`tests/amg/web/test_car_status_pages.py`:** the garage card says `Next:` and then the word `Replace` before "Cabin air filter" (the steady car's first next-up job).
- **`tests/amg/web/test_issue_pages.py`:** the sheet's assertion follows the new class.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the garage card says the next job's action`)
- **`docs/ROADMAP.md`, Phase 5:** the existing next-up action item gains "the garage card's Next line says it as a word".
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-garage-next-action.md` with the header, and an index row. Its commit and an As built note are added when it ships.

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (`scratchpad/p16`, made-up car):
  - the card's Next line, on the desktop and at 360px
  - in dark mode
  - the For the shop sheet unchanged
- **After you deploy (yours):** the Elantra's garage card says what's next and what to do to it.
