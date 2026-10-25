> **Approved** 2026-10-25 15:00 · **Roadmap** [Phase 5](../ROADMAP.md#phase-5--gap-engine-interval-chart-dashboard)
>
> **Built in** `08f6f5a` feat(schedule): show each next-up job's action, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The design reference gained a row**, "Brake inspection", so it shows an inspect stamp. Its four sample jobs were all replace or perform.
> - **At 360px wide the stamp's column costs a line on some rows.** "in 3,020 mi · ~Jan 2027" now wraps where it fitted before. The overdue rows already took three lines. Narrowing the status mark's column didn't win the line back, so the layout stayed as planned.
> - **The "N more" fold wasn't seen in the browser**, because the scratch car has five jobs. Its rows come from the same macro, so they carry the stamp too.
> - **Checked in the browser** on the scratch car, with made-up data and no Claude calls:
>   - R, I and P stamps lined up beside the names, with the key beneath
>   - at 360px (no sideways scroll; a wrapped name keeps its stamp on its first line)
>   - at desktop width (stamps in one column, names and dates in the next)
>   - in dark mode
>   - on the design reference
>
> The plan below is as it was approved; it isn't edited afterwards.

# Show each next-up job's action: replace, inspect or perform

## Context
Next up on a car's page shows each job's status mark, name, when it's due, its cost, and **Mark as done**. It doesn't say whether the job is to replace something, inspect it, or perform a procedure. So "Brake inspection" and "Engine oil and filter" look alike, and so do a job you can check in five minutes and one that needs parts.

The schedule page already shows this with the manual's own letters, as a stamp beside each job:
- **R** (replace): solid ink.
- **I** (inspect): dashed, like an inspected chip.
- **P** (perform): outlined.

A key ("R Replace · I Inspect · P Perform") sits above that list. The car page's next up should use the same stamp, so the same letters mean the same thing on both pages.

(I've read "recommend" as **replace**. Schedule jobs are replace, inspect or perform. A shop's recommendations have their own section, **Shop recommendations**, further down the car page.)

## How it looks
```
▲  [R]  Engine oil and filter        ~$85
        1,200 mi overdue · Oct 3     [Mark as done]
◐  [I]  Brake inspection             ~$40
        in 700 mi · by Nov 12
○  [P]  Tire rotation                ~$25
        in 4,300 mi · ~Feb 2027
R Replace   I Inspect   P Perform
```
- **The stamp:** the small stamp (`stamp--small`, the size the schedule editor's rows use) goes in its own column between the status mark and the name, on the name's line.
  - The names still line up under one another, and the stamps line up too, so you can scan down either column.
  - The status mark stays first and in colour, so how urgent a job is still reads first. The stamp is smaller and black and white.
- **The key:** the stamps' key from the schedule page goes beneath the list, small and muted. It shows all three letters, as on the schedule page.
- **The folded list:** rows under "N more" get the stamp too.
- **Screen readers:** the stamp is hidden from them. The name is read as "Replace: Engine oil and filter", as the schedule page reads it.

## Code (one commit: `feat(schedule): show each next-up job's action`)
- **`web/templating.py`:** a shared `ACTION_WORDS = {"replace": "Replace", "inspect": "Inspect", "perform": "Perform"}`, beside `STATUS_WORDS`, registered as the `action_words` global.
- **`web/routes_schedules.py`:** `ACTION_LABELS` becomes that dict, imported, so the words can't drift apart between pages. `ACTION_LETTERS` stays as it is.
- **`web/status.py`:** each `next_up` row gains `"action": item_status.item.action`.
- **`templates/_chart.html`:** in the `next_up` macro:
  - before the name, `<span class="stamp stamp--small stamp--{{ item.action }}" aria-hidden="true">{{ action_words[item.action][0] }}</span>`
  - in the name, `<span class="vh">{{ action_words[item.action] }}: </span>`
  - Both only `{% if item.action %}`.
- **`templates/vehicle.html`:** after the list (and its "N more" fold), `{{ legend(action_words) }}`, using the existing `legend` macro from `_schedule_editor.html`.
- **`static/app.css`:**
  - `.nextup__item` gets four columns, `1.5rem auto 1fr auto`, with areas `"mark stamp name side" "mark . when side"`.
  - `.nextup__item > .stamp { grid-area: stamp; align-self: start; }`, so a name that wraps keeps its stamp on its first line.
  - Spacing above the key.
- **`web/routes_design.py`:** `SAMPLE_NEXT_UP` rows gain an action each (one of each), so the design reference shows the stamps.

## Tests
- **`tests/amg/web/test_status.py`:** `next_up` rows carry each job's action. The steady car has all three: Engine oil and filter replace, Brake inspection inspect, Tire rotation perform.
- **`tests/amg/web/test_car_status_pages.py`:** the car page shows the stamps, the hidden words before the name ("Replace: " before Cabin air filter), and the key.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: next up shows each job's action`)
- **`docs/ROADMAP.md`, Phase 5:** an item "(added after the phase shipped, 2026-10-25)" saying next up shows each job's action with the schedule page's stamp, and the key beneath.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-next-up-actions.md` with the header and an index row. Its commits and As built note are added when it ships.

## Not included
- **The garage card's "Next:" line** and the **For the shop** sheet's "Due now" list use the same rows, but stay as they are. On the shop sheet, words would suit better than letters ("Replace", "Inspect"). Either can be added if you want.
- **The interval chart's item column.**

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (`scratchpad/p16`, made-up car, `ANTHROPIC_API_KEY=""`):
  - the car page's next up shows R, I and P stamps lined up, with the key beneath
  - the "N more" fold shows them too
  - at 360px wide, with no sideways scroll and the **Mark as done** button still fitting
  - on the desktop and in dark mode
  - the design reference page (`/design`)
- **After you deploy (yours):** the Elantra's next up shows each job's letter.
