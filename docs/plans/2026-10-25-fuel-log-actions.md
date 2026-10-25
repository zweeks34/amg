> **Approved** 2026-10-25 18:19 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Built in** `544fc00` feat(fuel): edit, copy and delete a fill-up from the log, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The copied line is `row.line`, not `row.copy`.** Jinja reads `row.copy` as the dictionary's own `copy` method.
> - **The "Copy it from here" box is shown with a bound `hidden` attribute**, not `x-show`. With `x-show` it stayed up for about a second after a later copy worked. It reads "This browser wouldn't copy. Copy it from here:".
> - **The phone row's column gap went from 0.625rem to 0.5rem.** With the ▸ column, the tightest row (a date, a six-figure odometer and "3.30 mi/kWh") fit at 360px with only 4px to spare. Below that, the date broke at a hyphen. It now fits down to 350px.
> - **The ▸ is 1.125rem,** so it reads as something to tap.
> - **Checked in the browser** on the scratch car, with three made-up fill-ups and no Claude calls:
>   - A row opens and closes, and opening another closes the first.
>   - **Edit** opens the edit page.
>   - **Delete**, then **Keep it**, leaves the fill-up; **Delete fill-up** removes it and the log says "Fill-up deleted."
>   - At 360px (no sideways scroll; the confirm wraps beneath the buttons), on the desktop and in dark mode.
>   - **Copy** was checked with the browser's copy functions swapped for recorders, so the real clipboard wasn't touched:
>     - the clipboard API took the line, and the button said "Copied", then "Copy" again
>     - with the API refused, the older copy command copied the hidden box, whose selection held the line
>     - with both refused, the box showed the line, selected and focused, and hid again when a later copy worked
>     - with the page made insecure, as plain HTTP is, Copy went straight to the older command
>
> The plan below is as it was approved; it isn't edited afterwards.

# Edit, copy and delete a fill-up from the fuel log

## Context
You want to edit, delete and copy a fill-up from the fuel log. Two of those already exist, but nothing shows them. Tapping a row in the log opens its **Edit a fill-up** page, and **Delete this fill-up** sits at the bottom of that page. The row looks like plain text, though: it only changes colour under a mouse, never on a phone. Copying doesn't exist at all.

You chose:
- **Tapping a fill-up opens it in place**, with **Edit**, **Copy** and **Delete** under it.
- **Copy puts the fill-up on your clipboard** as one readable line, the way the log words it. It isn't a new fill-up.

## How it behaves for you
- **Under the log's heading:** "Tap a fill-up to edit, copy or delete it."
- **Each row** keeps its two lines on a phone (date, odometer, economy; then quantity, price, total) and gains a small ▸ at the end. Tapping it:
  - opens it: the ▸ turns to ▾ and the row is shaded
  - shows **Edit**, **Copy** and **Delete** beneath it

  Opening another row closes the first. Tapping the open row closes it.
- **Edit** opens the **Edit a fill-up** page you have today. Its **Delete this fill-up** stays.
- **Copy** puts the fill-up on the clipboard and the button says "Copied" for a moment. The line looks like this:

  `Oct 20, 2026 · 45,210 mi · 10.200 gal · $34.67 ($3.399/gal) · 32.4 mpg · Full tank · Costco on Main`

  - **Parts:** date · odometer · quantity · total (price) · economy · "Full tank" or "Partial fill" · Home or Public · "After one not logged" · the note.
  - **Missing parts are left out:** no cost, or no economy yet.
  - **The figures are the log's own,** so a quantity reads "10.200 gal" as the pump shows it, not "10.2 gal" as in the example you picked.
  - **A charge reads in its own units:** "Oct 20, 2026 · 12,040 mi · 31.5 kWh · $4.41 (14.0¢/kWh) · 3.85 mi/kWh · Full charge · Home".
- **Delete** asks in place: "Delete this fill-up? Its odometer reading goes with it." It offers **Delete fill-up** and **Keep it**, the same words as on the edit page. After deleting, the log says "Fill-up deleted." That notice now shows when you delete from the edit page too. A charge is worded as a charge.

### The clipboard on your server
AMG is served over plain `http://amg.home.arpa`, and browsers keep the modern clipboard for HTTPS pages only. So Copy:
1. uses the modern clipboard where the page is secure (`localhost`, or HTTPS if you add it later)
2. otherwise uses the older copy command, which works on plain HTTP
3. if the browser refuses both, shows the line in a box with the text selected and says "Copy it from here."

## Code (one commit: `feat(fuel): edit, copy and delete a fill-up from the log`)
- **`web/fuel_status.py`:** `log_rows` adds each row's `fill` (its own units' "fill-up" or "charge") and `copy`. The new `copy_words(row, units, stretch)` builds the line from:
  - `day_words` (from `recalls.py`, as `shop_sheet` uses it)
  - the odometer
  - `quantity_words`
  - `money` and `price_words`
  - `economy_words`
  - `units.full_noun`, capitalised ("Full tank", "Full charge"), or "Partial fill" / "Partial charge"
  - the place, missed-before and the note
- **`templates/fuel.html`:**
  - The hint line goes under "The log" heading.
  - Each `<li>` holds `<details class="fuellog__item" name="fuellog">`. The `name` attribute lets only one be open at a time, with no JavaScript.
  - Its `<summary>` wraps the existing row as a `<span class="fuellog__row">`, which was an `<a>`, plus the ▸ (`aria-hidden`).
  - Inside, `.fuellog__actions` holds:
    - **Edit**, a link to `/fuel/{id}/edit`
    - **Copy**, `x-data='copyLine({{ row.copy | tojson }})'`. A `role="status"` span says "Copied" to screen readers, and the fallback box sits beside it.
    - **Delete**, using the confirm pattern from `fuel_form.html` (`x-data="{ confirming: false }"`, a form posting to `/fuel/{id}/delete`).
  - Every button names its fill-up in its `aria-label` ("Copy the fill-up of Oct 20, 2026").
- **`static/app.js`:** a new `copyLine(text)` Alpine component, with `copied` and `failed` state and `copy()` using the three steps above. The legacy copy writes the text to a temporary read-only textarea, selects it, and runs `document.execCommand("copy")`.
- **`static/app.css`:**
  - The summary has no marker and a pointer cursor, the shade when open, and the same hover as today.
  - `.fuellog__row` gets a last column for the ▸ (desktop: `auto` after economy; phone: a third column spanning both lines). ▸ turns to ▾ via `details[open]`.
  - `.fuellog__actions` is a row of buttons with the gutter's padding, and the confirm wraps beneath them on a phone.
  - `.fuellog__copied` is the fallback box.
- **`web/routes_fuel.py`:**
  - `delete_fill` redirects to `/vehicles/{id}/fuel?deleted=1`.
  - `fuel_page` takes `deleted: int | None` and passes `deleted=bool(deleted)`.
  - `fuel.html` shows `notice--done` "{{ units.fill | capitalize }} deleted."

No change to the database, the repo or the edit form.

## Tests (`tests/amg/web/test_fuel_pages.py`)
- **`copy_words` / `log_rows[...]["copy"]`:**
  - a full fill with cost and economy, word for word
  - a partial fill
  - a fill with no cost (no cost part)
  - the first fill (no economy)
  - a fill after one not logged, with a note
  - an EV home charge in kWh, ¢/kWh and mi/kWh
- **The log page:** each fill-up is a `<details name="fuellog">` with the Edit link, the Copy component carrying its line, and a delete form posting to its `/fuel/{id}/delete`. The hint line shows. An EV's log says "charge".
- **Deleting:** it redirects to `?deleted=1`, and the log says "Fill-up deleted." The existing `test_edit_and_delete_a_fill` keeps passing.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: edit, copy and delete a fill-up from the log`)
- **`docs/ROADMAP.md`, Phase 6:** an item "(added after the phase shipped, 2026-10-25)": tapping a fill-up in the log opens **Edit**, **Copy** (one line to the clipboard, which works on plain HTTP) and **Delete**, which asks to confirm in place.
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-fuel-log-actions.md` with the header and an index row. Its commits and As built note are added when it ships.

## Not included
- **Copying as a new fill-up** (a prefilled **Log a fill-up**): not what you meant.
- **Copying several fill-ups at once:** the Fuel CSV in Reports already exports the whole log.

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (`scratchpad/p16`, made-up car, `ANTHROPIC_API_KEY=""`), after logging three made-up fill-ups:
  - a row opens and closes, and opening another closes the first
  - **Edit** opens the edit page
  - **Copy** says "Copied", and the clipboard holds the line (read back in the page)
  - the fallback box shows when the clipboard is refused (simulated)
  - **Delete**, then **Keep it**, leaves the fill-up; **Delete fill-up** removes it and the notice shows
  - at 360px (no sideways scroll; the ▸ column doesn't push the economy onto a new line), on the desktop and in dark mode
- **After you deploy (yours):** on `http://amg.home.arpa`, from your phone, copy a fill-up and paste it into a note.
