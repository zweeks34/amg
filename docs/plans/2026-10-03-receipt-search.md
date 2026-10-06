> **Approved** 2026-10-03 20:49 · **Roadmap** [Phase 9 (came forward)](../ROADMAP.md#phase-9--reports-and-exports)
>
> **Built in** `c844ad6` feat(web): sort, filter and search confirmed receipts, `69fd80f` docs(roadmap): receipt search came forward from phase 9
>
> The plan below is as it was approved; it isn't edited afterwards.

# Find confirmed receipts: sort, filter, search

## Context
The receipts page lists every confirmed receipt in one long ledger, ordered by when you **confirmed** it (`repo/receipts.inbox`: `confirmed_at DESC`). After loading years of Outback history, that order is arbitrary, and there is no way to find "the brake job at Midas" or "that $412.37 charge". You asked for:
- sort, filter and search on the confirmed list
- the newest **receipt date** at the top by default

This brings forward one item from phase 9: "Search across receipts: what Claude read and you confirmed — shops, line descriptions, notes". The rest of phase 9 (the report builder, CSV, the sale packet) stays where it is.

## How it behaves for you
Above the confirmed ledger, under "Confirmed (52)":

```
[ Search: shop, work, notes or amount ................ ]
[ Car: All cars ▾ ]  [ Year: Any year ▾ ]  [ Sort: Newest first ▾ ]
12 of 52 match. Show all
──────────────────────────────────────────────────────────
2024-03-11   Midas            Outback          $412.37
             Front brake <mark>pads</mark> and rotors · Recommended: Rear <mark>pads</mark> at 3 mm
```

- **Sort:**
  - **Newest first** (the default): by receipt date, with the same day ordered by most recently added.
  - **Oldest first**
  - **Highest total**
  - **Recently confirmed**: today's order, kept for after you've confirmed a batch.
- **Car:** all cars, or one. The list includes archived cars that have receipts, marked "(archived)". The filter only appears when your receipts cover more than one car.
- **Year:** any year, or one of the years your receipts cover. It only appears when they span more than one year.
- **Search:**
  - Every word has to appear somewhere in the receipt, so "midas brake" means both.
  - It matches without regard to case, and on parts of words.
  - It searches the shop, invoice number, line descriptions, the service types each line covers (so "coolant" finds a line called "Fluid flush"), recommendations, notes, the car's name and the file name.
  - A word like `412.37` or `$1,234` also matches the total.
- **What matched:** each row shows up to three matching lines, recommendations or notes, with the words highlighted and "+N more" after that. A long note is trimmed to the part around the match. The shop and the car are already on the row, so a match there needs no extra line.
- **Results:** the list updates as you type, about a quarter of a second after you stop. Focus stays in the box. The address bar keeps the search (`/receipts?q=brake&car=3`), so refreshing, Back and bookmarks all work.
  - With a filter on, a status line says "12 of 52 match." with **Show all**.
  - When nothing matches: "No confirmed receipts match. Show them all."
- **Polling:** the confirmed list leaves the region that refreshes every 2 seconds while receipts are read. Today, that refresh would wipe the search box mid-word. The confirmed list never changes while reading happens, since confirming is done on the review screen, so it doesn't need to refresh.

## Code
- **`src/amg/repo/receipts.py`, `inbox()`:**
  - Confirmed items also carry what the search reads from the draft: `lines`, `recommendations`, `notes` and `invoice_number`, plus `vehicle_archived` from the vehicles join.
  - Confirmed items are sorted by receipt date (`performed_on DESC, id DESC`), so the repo's default matches the page's.
- **New `src/amg/web/receipt_finder.py`:** pure functions over the inbox's confirmed dicts, which turn the request into words, as `budget.py` and `status.py` do.
  - **`Finder` dataclass:**
    - fields: `q`, `car`, `year`, `sort`
    - `Finder.read(q, car, year, sort)`: lenient parsing; an unknown sort means newest, a non-number car means all
    - `.active`
    - `.url()`: the canonical URL, defaults left out
  - **`SORTS`:** `{"newest": "Newest first", "oldest": "Oldest first", "total": "Highest total", "confirmed": "Recently confirmed"}`
  - **`choices(confirmed)`:** the cars (active first, then archived) and the years, newest first.
  - **`find(confirmed, finder, type_names)`:** returns the rows to show, in order, each with its `found` snippets.
  - **`highlight(text, words)`:** returns `Markup`. Each piece is escaped first, then the matches are wrapped in `<mark>`, so a `<` in a line description stays text.
- **`src/amg/web/routes_receipts.py`:**
  - `GET /receipts` takes `q`, `car`, `year` and `sort`.
  - `_inbox` passes `finder`, `found`, `choices` and `sorts`.
  - On an htmx request, the response sets `HX-Push-Url` to `finder.url()`, so the address bar shows `/receipts?q=brake` and not the empty fields.
  - It reuses `services.list_types` for the type names.
- **Templates:**
  - **`_receipt_list.html`:** keeps reading, to check and couldn't read, the region that polls.
  - **New `_confirmed_receipts.html`:**
    - the confirmed section, with the finder form, the status line and the results ledger
    - the discarded list and the "No receipts yet" empty state, which move with it so the page order stays the same
  - **The finder form:**
    - a GET form to `/receipts`
    - `hx-get="/receipts" hx-trigger="input delay:250ms, submit" hx-select="#confirmed-results" hx-target="#confirmed-results" hx-swap="outerHTML" hx-select-oob="#confirmed-count" hx-sync="this:replace"`
    - htmx is 2.0.11, which supports all of these.
    - Enter submits it even without htmx.
    - The status line is `role="status"`, so a screen reader hears "12 of 52 match".
- **`src/amg/web/static/app.css`:**
  - `.finder`: a wrapping flex row, with the search `flex: 2 1 16rem` and the selects `flex: 1 1 8rem`. At 360px the search takes its own line and the selects wrap two and one.
  - `.finder__count`
  - `.ledger__found`: full width under the row (`grid-column: 1 / -1`), small and muted, with `mark` in safety yellow.
  - It reuses `.field` and the existing ledger rows.
- **`docs/ROADMAP.md`:** phase 9's search item ticked, noting it came forward onto the receipts page.

## Tests
- **New `tests/amg/web/test_receipt_finder.py`** (pure):
  - every word must match, across fields (shop + line)
  - a service type's name finds its line
  - `412.37`, `$412.37` and `1,234` match totals
  - `<mark>` highlighting, with HTML in a description escaped
  - a long note trimmed around the match
  - each sort, with an unknown sort falling back to newest
  - `Finder.read` on bad input
  - the canonical URL leaving defaults out
  - `choices` only offering cars and years that are there
- **`tests/amg/web/test_receipt_pages.py`:**
  - confirmed receipts listed newest receipt date first, even when confirmed in another order
  - `?q=` showing only matches, with "1 of 3 match"
  - car and year filters combining
  - the car and year selects hidden when there's only one of each
  - an htmx request getting `HX-Push-Url`
  - the no-match message
  - `/receipts/list` no longer carrying the confirmed list, so polling can't wipe a search
- **`tests/amg/repo/test_receipts_repo.py`:** the inbox's confirmed order is by receipt date.

## Commits
1. `feat(web): sort, filter and search confirmed receipts`: the repo tweak, the finder, the route, templates, CSS and tests
2. `docs(roadmap): receipt search came forward from phase 9`

## Verification
- `.venv\Scripts\python -m pytest`: everything passes.
- A local run on a scratch database (`AMG_DATA_DIR` in the scratchpad, no `--reload`), with about 12 confirmed receipts across two cars and four years, confirmed out of date order. Nothing goes to Claude: the receipts are written straight through the repo.
  - **Order:** the default is newest receipt date first.
  - **Searching:** type "brake"; focus stays in the box, the URL updates, and the matching lines are highlighted. Back restores the earlier list.
  - **Filters:** car + year + search combine; each sort works; the no-match message shows when nothing matches.
  - **Polling:** with a receipt left queued, the 2-second poll runs and a search in progress survives it.
  - **Widths:** desktop and 360px (iframe), with no horizontal overflow.
