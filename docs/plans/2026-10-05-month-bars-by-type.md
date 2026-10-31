> **Approved** 2026-10-05 21:43 · **Roadmap** [Phase 7](../ROADMAP.md#phase-7--forecast-and-budget)
>
> **Built in** `e9bc694` feat(budget): month bars by type, with a type picker, `08af1e3` docs(roadmap): month bars by type
>
> **As built:** Chosen from the four options drawn in [budget-chart-options.html](2026-10-05-budget-chart-options.html) (A's colours with B's picker). On a phone the type buttons take one row that scrolls sideways, its far edge faded, instead of wrapping into five rows.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Month bars by type: stacked colours with a type picker

## Context
You picked a mix from the [chart options page](https://claude.ai/artifact/GEnRoUH996dzvcN4JcPEeJ):
- **from A**, colours for the three big types
- **from B**, a picker that brings any type forward

The month bars on the car's budget page and the garage budget page will show what each month's money goes on, not just how much it is.

## How it behaves for you

### At rest: stacked colours
- **Each month's column is split by type.** Its height is unchanged: still the month's maintenance and fees.
- **Three types get a colour, the same on every car and every page:**

  | Type | Light | Dark |
  |---|---|---|
  | Engine | blue `#2a78d6` | `#3987e5` |
  | Brakes | orange `#eb6834` | `#d95926` |
  | Tires and wheels | aqua `#1baf7a` | `#199e70` |

- **Every other type is grey:** light `#a3adb7`, dark `#5d6976`.
- **These hues were run through the palette validator** against AMG's own panel colours in both themes. They avoid safety yellow (the put-aside tape), signal red (overdue) and service green (done). A fourth colour failed the check, which is why the rest share grey.
- **Stacking order is fixed, bottom up:** Engine, Brakes, Tires and wheels, then the grey types in catalogue order, fees last.
  - A thin gap of the panel colour separates differently coloured parts.
  - Grey types sit together with no gap between them.
- **A legend under the bars** shows the coloured types present, "Other types" if any, and the put-aside tape.
- **Hovering over a part** names it, as the bars' tooltips do now: "January 2027 · Brakes: $140".

### The picker
- **Above the bars, a row of buttons:** "All types" and each priced type with its total, in By type order. They're the same totals as the By type section.
- **Picking a type:**
  - its part of each month stays coloured, in its own colour, or ink for a grey type so it stands out
  - everything else in the column fades to the pale rule colour
  - the legend changes to "{type}" and "Everything else"
  - the put-aside tape stays
- **"All types"** brings back the stacked colours.
- **No JavaScript:** the buttons stay hidden (`x-cloak`) and the stacked chart works on its own.
- **Switching the horizon** reloads the page and starts back at "All types".

### Unchanged
- the month list, which stays the table view naming every job and price
- the By type section
- the figures

## Code

### `src/amg/web/budget.py`
- **New `type_of(due, categories)`:** a `Fee` → "Inspections and registration"; a `Due` → its item's category. It's shared with `breakdown()`, which switches to it.
- **New `COLOURED = ("Engine", "Brakes", "Tires and wheels")`.**
- **`chart(months, per_month, count, categories=None)`:** each bar gains `segs`, one per type with money that month, in stacking order. Each seg holds `type`, `colour` (`1`–`3` or `other`), `cents`, a `gap` flag (set when the colour differs from the part below) and a `title`.
  - Existing fields (`h`, `label`, `title`, `ticks`, `line`, `per_month`, `what`) are unchanged.
  - New: `types` (picker rows: label, total, colour) and `colours` (the legend entries present).
- **`CarBudget.categories`** already exists. The garage merges every car's into one dict; item ids are unique across cars.

### `src/amg/web/routes_budget.py`
Both pages pass the categories to `chart()`.

### `src/amg/web/templates/_budget.html`, `bars(chart)` macro
- **Each `.mbars__bar` becomes a stack:**
  - its height stays `--h`
  - its parts are `<span class="mbars__seg mbars__seg--{colour}" data-type="…" style="flex: {cents}">`, so they share the bar in proportion
- **The picker:** `x-data="{ picked: 'all' }"`, buttons with `aria-pressed`, and one `x-effect` that marks each part `is-picked` or `is-dim`.
- **The legend:** two versions, swapped with `x-show`.

### `src/amg/web/static/app.css`
- **New tokens on `:root` and in the dark block:** `--type-1`, `--type-2`, `--type-3`, `--type-other`, `--type-dim`, plus `--on-type` for the text on a pressed button.
- **New `.mbars__seg` rules:**
  - flex column-reverse inside the bar
  - the panel-coloured gap when `gap` is set
  - `is-dim` and `is-picked` for a grey type
- **New `.typepick` button row**, in the style of the horizon switch's small-caps buttons.
- **The rise animation** stays on the bar.

**No new dependencies.** Alpine is already vendored.

## Tests
In `tests/amg/web/test_budget_pages.py`.

**`chart()` on hand-built months.** One month holds Brakes $140, Engine $37, Cabin $36 and Registration $41.
- The parts come out in this order:

  | Part | Colour | Gap below |
  |---|---|---|
  | Engine | 1 | no |
  | Brakes | 2 | yes |
  | Cabin | other | yes |
  | Inspections and registration | other | no |

- The parts' cents add up to the bar.
- The legend lists Engine, Brakes and Other types.
- Existing `h`, ticks and line values are unchanged.

**Pages.**
- The worked Outback's bars carry Tires and wheels and Engine parts.
- The picker has an "All types" button and a button for each priced type, in By type order with totals.
- The garage page's chart mixes two cars' parts.
- A car with no priced work has no picker.

## Commits
1. `feat(budget): month bars by type, with a type picker`: `budget.py`, the route, the templates, the CSS and the tests.
2. `docs(roadmap): month bars by type`: a ticked item under Phase 7, and a decision recording:
   - why only three colours (the palette validator's limit)
   - fixed colours per type
   - the picker in place of more colours

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run** on the seeded scratch copy (`scratchpad/p11/data`, made-up data):
  - the car's budget and the garage budget, at 12 months and 3 years
  - picking types, including a grey one such as Electrical
  - light and dark themes, desktop and 360px
  - screenshots if Chrome's window is visible; otherwise measured in the page, as last time, and I'll say so
- **Done when (yours):** on the server, the Outback's bars show their colours, and picking Brakes shows when brake money lands.
