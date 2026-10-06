> **Approved** 2026-10-04 21:29 · **Roadmap** [Phase 9](../ROADMAP.md#phase-9--reports-and-exports)
>
> **Built in** `308b6e7` feat(reports): filters, history, spending and fuel reports, as CSV too, `1c5d738` feat(web): the reports page, `d3f3ec1` feat(reports): the sale packet, `855e48a` feat(reports): download your data, `2bc8563` docs(roadmap): phase 9
>
> The plan below is as it was approved; it isn't edited afterwards.

# Phase 9: Reports and exports

## Context
The SPEC asks for "flexible, on-demand reports so that I can review prior maintenance history". Today, history shows up in three places:
- each car's page
- one service at a time
- the receipts search, which came forward from this phase

Phase 9 is the last phase on the roadmap. It adds:
- a reports page you can filter, print and download as CSV, with three views (the roadmap's presets)
- a sale packet: a car's history plus every receipt, as one PDF to hand a buyer
- "Download your data": everything as spreadsheets and the original files

**Missing receipts don't block any of it.** Reports read only what's confirmed, so they fill in as you add receipts. The sale packet is built fresh each time you download it.

**Rules every report follows:**
- **Confirmed services only:** sources diy, shop, receipt and attested, all from `service_events` with `confirmed = 1`. A receipt that's still waiting never counts.
- **Archived cars stay in:** you can report on a car you've sold, and the car list labels it "(archived)".

## How it behaves for you

### The Reports page (`/reports`)
**Getting there:**
- a new **Reports** link in the footer, next to Alerts and Back up
- a quiet **Report** button in each car's "Service history" header, which opens the page filtered to that car

**Views:** a segmented control at the top, styled like the budget's horizon switch: **History · Spending · Fuel**. Switching views keeps the car and dates.

**Filters** (a GET form, so every report has a URL you can bookmark):
- **Car:** All cars, or one car.
- **From / To:** dates, both ends included. If From is after To, they're swapped.
- **Service:** Any; or a category ("All brakes"); or one service type. Only types that appear in your history are listed, grouped by category.
- **Shop:** text. Partial, case-insensitive matches: "midas" finds "MIDAS #1234" and "Midas Auto". The suggestion list holds your shops plus "Your own work".
- Every filter you set must match. A car or service that isn't on offer is dropped rather than left filtering out of sight, the same rule as the receipts finder.
- The Fuel view uses only the car and the dates, so it hides the other two filters.

**History view:**
- **Summary:** "14 services · Mar 2016 – Sep 2026 · $3,412.80". With a service filter it adds "$1,240.55 of it on brakes".
- **Each visit:** the date, miles, who did it (shop, "Your own work", or "Done, no receipt"), the car (when showing all cars), the total, and the lines with their amounts.
- **With a service filter:** only the matching lines are shown, then "and 4 other lines, $212.40". Each visit links to its service page.
- **Order:** newest first.

**Spending view (spend by year and category):**
- **The table:** categories down the side, years across (oldest to newest), with a total row and a total column.
- **Visits with a total:** each line's amount goes to its category, tax goes to "Tax", and whatever's left goes to "Other charges". That covers shop supplies, lines with no service type, and discounts that aren't itemized. So each year's column adds up to what you actually paid.
- **Visits without a total:** lines plus tax.
- **A line covering two categories:** it counts under the first one in the catalogue's order. That's rare, and the order is fixed so the result is too.
- **With a service filter:** only matching lines count, and the Tax and Other charges rows drop out.
- **On a phone:** the table scrolls sideways inside its own box, with the category column pinned. The page itself never scrolls sideways.

**Fuel view (fuel economy trend):** one section per car that has fill-ups or charges:
- a row per month: fill-ups, miles, gallons or kWh, mpg or mi/kWh, ¢ a mile, spent, and average price
- the month's economy is miles over quantity for the stretches that ended that month, never an average of averages (`engine/fuel.py`'s rule)
- spent includes partial fills, the same as `engine.fuel.spent`
- above the table, the fuel page's trend chart with one dot per month, using the same `trend_chart` macro
- months with no fills are left out

**Under each view:**
- **Print:** prints this report on clean paper. The masthead, footer, filters and buttons are hidden, and a printed heading says what the report is, e.g. "Service history · Outback · Brakes · 2019–2026 · printed Oct 4, 2026".
- **Download CSV:** what the view shows.
- With one car chosen, **Sale packet (PDF)**.

**Empty state:** "Nothing to report yet. Confirm receipts or log services and they show up here." When filters match nothing, the page says so and offers **Clear filters**.

### CSV files
- **Encoding:** UTF-8 with a byte-order mark, so Excel shows accents correctly. Google Sheets doesn't care.
- **Amounts:** plain numbers (`1234.50`, `-12.00`), so spreadsheets add them. Dates are ISO.
- **Text that starts with `=`, `+`, `-` or `@`** gets a leading `'`, so a spreadsheet shows it rather than running it as a formula. For example, OCR'd text "-Oil filter" would otherwise show as #NAME?.
- **History CSV:** one row per line, with the visit's columns repeated:
  - Car, Date, Odometer, Where, Invoice, Source, Line, Kind, Part number, Quantity, Amount, Services, Category, Visit total, Visit tax, Notes, Visit #
  - summing Amount gives line spend; Visit # lets a pivot table count each visit once
  - a visit with no lines gets one row
- **Spending CSV:** the table as shown.
- **Fuel CSV:** the monthly rows, per car.
- **Names:** `amg-history-outback-2026-10-04.csv`, `amg-spending-all-cars-…`, and so on.

### Sale packet (`/vehicles/{id}/sale-packet.pdf`)
**Front pages** (Letter size), built with PyMuPDF's HTML `Story` from a Jinja template:
- the car: year, make, model and trim; VIN; the latest odometer reading and its date
- "Prepared Oct 4, 2026 from the owner's records"
- **Summary:** "41 services, Mar 2016 – Sep 2026; 37 with the receipt attached"
- **Table:** date, miles, who did it, work done, paid, and "Receipt p. 7"
  - Work done is the service type names, or the line text when a line has no types.
  - Your own work shows as "Owner's own work"; an attested service as "Done, no receipt".

**Then every confirmed receipt for the car**, oldest first like a car's life story:
- as stored: PDFs page for page, photos converted the way `documents.combine` already does
- the table's page numbers are worked out in two passes: count the front pages, then render again with the numbers in

**Bookmarks:** "History", then one per receipt ("2021-03-04 · Midas · 45,120 mi").

**Left out on purpose:** your notes (they're for you, not a buyer) and receipts still waiting to be checked.

**Scans go in as they are.** Your name, address and phone on a receipt are visible. AMG can't black those out, so the Reports page says so next to the button.

**Delivery:** built in the temp directory and deleted once sent, like the backup download.

### Download your data (`/reports/your-data.zip`, on the Reports page)
- **Spreadsheets:**
  - `cars.csv`
  - `service-history.csv`: the History CSV for all cars, no filters
  - `fuel.csv`
  - `odometer.csv`: every reading and where it came from
  - `schedules.csv`: each car's items, intervals, services and source
  - `prices.csv`: your prices and Claude's estimates, labelled
- **Files:**
  - `receipts/2021-03-04 Midas - Outback.pdf`: every confirmed receipt as uploaded, named by date, shop and car. A clash gets ` (2)`. Characters a file name can't hold are removed.
  - `manuals/…`: the owner's manual files that schedules were read from
- **`README.txt`** explains each file. It also says this is a copy to read, not a backup: to put AMG back, use **Back up**.
- **Delivery:** temp file, deleted after sending, as with the sale packet.
- **The Back up page** gets one line pointing here for a copy you can open in a spreadsheet.

## Code
- **`src/amg/repo/reports.py`** (all the SQL):
  - `visits(conn, car_id, start, end)`: confirmed services with their lines, each line's service types and categories, and the car's name and whether it's archived
  - `shops(conn)`
  - `used_types(conn)`
  - export queries: cars, fuel, odometer points, schedules, prices, confirmed receipts with their documents, schedule documents
  - Reuse `repo/fuel.log`, `repo/services.list_types` and `repo/documents.path`.
- **New package `src/amg/reports/`** (pure except `packet.py` and `export.py`):
  - **`filters.py`:** `Filters(view, car, start, end, service, shop)`.
    - `read(**query)` reads the address bar forgivingly, swapping From and To if needed.
    - `within(options)`, `url(view=…)`, `csv_url()`, and `words()` for the printed heading.
    - The pattern is the receipts page's `web/receipt_finder.Finder`.
  - **`history.py`:** `select(visits, filters, type_names) -> History`, the shop and service matching. Each visit carries its matching lines, `others_count` and `others_cents`, plus totals and the date span. Shop matching runs on `web.templating.who(event)`.
  - **`spending.py`:** `table(history) -> Spending` (rows by category, year columns, totals) with the allocation rules above.
  - **`fuel.py`:** `months(stretches, fills) -> rows`, using `engine/fuel.stretches`, `economy` and `spent`.
  - **`csvs.py`:** `history_csv`, `spending_csv`, `fuel_csv`, plus the BOM and the formula guard. They return `str`.
  - **`packet.py`:** `build(conn, car, today) -> Path` (PyMuPDF `Story`, `insert_pdf`, `set_toc`).
  - **`export.py`:** `write(conn, path)`, which writes the zip (stdlib `zipfile`).
- **`src/amg/web/routes_reports.py`:**
  - `GET /reports`
  - `GET /reports/{view}.csv`
  - `GET /vehicles/{id}/sale-packet.pdf`
  - `GET /reports/your-data.zip`
  - All behind the login guard, like every page.
- **Templates:**
  - `reports.html`, plus the partials `_report_history.html`, `_report_spending.html` and `_report_fuel.html`
  - `pdf/packet.html`, the HTML the PDF is built from
  - `base.html` gets the footer link, `vehicle.html` the Report button, and `backup.html` its line
- **`app.css`:**
  - a "Reports" section, reusing `.horizon`, `.figures`, `.sheet`, `.chip` and the ledger's row rhythm
  - `.tablewrap` for the spending table
  - the app's first `@media print` block
  - checked at 360px
- **`app.js`:** **Print** is a button calling `window.print()`, wired in `app.js` (there's no CSP to stop it). With JavaScript off, the button is hidden.
- **No new dependencies or migrations:** PyMuPDF (already used), `csv`, `zipfile` and `tempfile`.

## Tests (the roadmap's pins, then the rest)
- **`tests/amg/reports/test_filters.py`, filters combine correctly:**
  - car × dates × service (type and category) × shop, each alone and together
  - dates inclusive at both ends, and From after To swapped
  - unconfirmed services never count
  - a car or service not on offer is dropped
  - shop matches partially, case-insensitively, and "your own work" finds DIY
- **`test_csvs.py`, the CSV round-trips:**
  - write it, read it back with `csv.DictReader`, and every value matches the report: amounts back to the same cents, and text with commas, quotes, line breaks and "°/é" intact
  - guarded cells carry their `'`
  - the BOM is present
  - the Amount column sums to the report's line total
- **`test_packet.py`, the packet holds every confirmed receipt for the car:**
  - a car with three confirmed receipts (a 2-page PDF, a PNG, a JPG), one waiting, one on another car, and a DIY service
  - page count = front pages + 4
  - one bookmark per confirmed receipt, and no others
  - the history text lists the DIY service as "Owner's own work"
  - the table's page numbers point at the right pages
  - notes are absent
- **`test_history.py`:** matching lines, the others count and amount, totals, the newest-first order.
- **`test_spending.py`:**
  - with "Other charges" taking the remainder, columns add up to the visit totals
  - a two-category line counts under the first category
  - with a service filter, only matching lines count
  - a visit with no total counts lines plus tax
- **`test_fuel_report.py`:**
  - the month's economy is miles over quantity, not an average of averages
  - a partial fill counts toward spent
  - an EV in kWh
  - a car with no fills is skipped
- **`test_export.py`:**
  - the README and every CSV are there
  - receipt names are dated and clashes are handled
  - archived cars are included
  - a receipt that's waiting or discarded is left out
  - no database or `.env` in the zip
- **`tests/amg/web/test_report_pages.py`:**
  - each view renders, and filters come back into the form
  - the CSV has the right type and file name
  - the empty and no-match states
  - the packet and zip need a session
  - the footer link and the car page's Report button

## Commits
1. `feat(reports): filters, history, spending and fuel reports, as CSV too`: `repo/reports.py`, `reports/{filters,history,spending,fuel,csvs}.py` and tests
2. `feat(web): the reports page`: the routes, templates, footer and car-page links, CSS including print, `app.js` and tests
3. `feat(reports): the sale packet`: `packet.py`, its template, the route and tests
4. `feat(reports): download your data`: `export.py`, the route, the Back up page line and tests
5. `docs(roadmap): phase 9`: ticks, the decisions above, tests-pin and done-when

## Verification
- **Tests:** `.venv\Scripts\python -m pytest` passes.
- **A local run on a scratch database** (`AMG_DATA_DIR` in the scratchpad), never `samples/`, which is personal:
  - **Seed data:** two cars, about a dozen confirmed services over several years (some with synthetic receipt PDFs and photos made in the scratchpad), a DIY job, an attested job and a few months of fill-ups.
  - Each view at desktop width and at 360px, and in print preview.
  - Each CSV opened back in Python.
  - The sale packet opened with PyMuPDF: page count, bookmarks and the page numbers in the table.
  - The zip listed and its README read.
- **Proposed done-when (yours, on the server):**
  - **History:** the History report for each car matches its car page.
  - **Spending:** the yearly totals look right against what you remember paying.
  - **CSV:** a CSV opens in Excel or Google Sheets with amounts as numbers.
  - **Print:** a printed (or print-to-PDF) report reads cleanly.
  - **Sale packet:** the Outback's packet opens, with a bookmark for every confirmed receipt.
  - **Your data:** the zip opens and its receipts are named sensibly.
