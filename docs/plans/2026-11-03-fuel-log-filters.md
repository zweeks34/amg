> **Approved** 2026-11-03 19:39 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Decided on approval:** no Home or public filter (decision 1), and add the "Download these" CSV button for the filtered rows (decision 2).
>
> **Built in** `61a3624` feat(fuel): filter, sort and download the log, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **Download these sits beside the totals line,** so it shows only when a filter is on. It gives the rows as shown, in the same order, as `amg-fuel-log-<car>-<date>.csv`, with each row's price, economy and Unusual flag as well as what `fuel.csv` holds. A text cell that a spreadsheet would read as a formula is made safe, as in the other CSVs.
> - **Two fields to a row on a phone.** Built one to a row, the open panel filled a 360px by 800px screen, so what the filters found was out of view after **Show fill-ups**. Two to a row, as the plan's sketch had it, makes the panel 453px tall and puts the totals line at 549px. A check now pins that it's in view.
> - **On a narrowed or sorted log, the Saved and Deleted notices sit under the log's heading,** not at the top of the page, because that's where the page opens. The whole log keeps them at the top.
> - **State, City and Station only appear once the log has one to offer.** Every log starts with no State or City until a fill-up has a location.
> - **The label is "State or province",** matching the fill-up form. From after To is swapped, as Reports does. **Clear filters** keeps the sort.
> - **The log's heading has 1rem above it** where the page lands, so it isn't flush with the top of the screen.
>
> **Checked on a scratch garage** (made-up stations, separate data directory), with headless Chrome against a scratch copy of the app, 46 checks:
> - **The panel:** it starts folded, opens, stays open when filtered, and says how many filters are on.
> - **City narrowing:** a state narrows City, another swaps it, a city not in the new state lets go, and Any brings them all back. State and City still show what was chosen after the page reloads.
> - **Two Newarks:** the name alone finds both, and adding the state finds one.
> - **Landing:** Show fill-ups and Clear filters land on the log, with the heading and totals in view and uncovered.
> - **Totals and sorting:** the line matches the sums, a missing cost is said, and sorting alone keeps every row and shows no totals.
> - **The to-do list:** **No location** finds two; editing one comes back with it gone and the notice in view; deleting the other comes back to "No fill-ups match these filters."; Clear filters brings the log back.
> - **The download:** the link carries the filters and the file has a row a fill-up.
> - **A charge log:** a home charge isn't missing a location, and totals are in kWh.
> - **Layout:** no sideways scroll at 360px or 320px, and the screenshots at 360px, in dark mode and at 1280px read properly.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Filter and sort the fuel log

## How it behaves for you

**The Filter panel**

A **Filter** panel sits at the top of **The log**. It stays folded until you open it, and it stays open while any filter or sort is on.

```
▾ Filter · 2 on
  From [          ]    To [          ]
  State [NJ ▾]         City [Trenton ▾]
  Station [Any ▾]      Needs a look [All fill-ups ▾]
  Fill [Any ▾]         Note [          ]
  Sort [Newest first ▾]
  [SHOW FILL-UPS]  Clear filters

12 of 48 fill-ups · 124.3 gal · $412.10 · $3.315/gal
```

**The filters**
- **From and To:** dates, as on Reports. Either one works alone.
- **State, City and Station:** dropdowns of only what this car's log contains. Picking a state narrows City to that state's cities.
- **Needs a look:** one dropdown with these choices:
    - Anything missing or unusual
    - No location, meaning neither a city nor a state
    - No station
    - No cost
    - Unusual
- **Home charges in Needs a look:** a home charge never counts as missing a location or station, because you know where it was.
- **Fill:** Full tank or Partial fill (Full charge or Partial charge for an electric car).
- **Note:** searches your notes, ignoring capitals. Every word you type has to appear in the note.

**Sorting**
- **Choices:** Newest first, which stays the default, then Oldest first, Lowest price, Highest price, Highest cost, Best MPG and Lowest MPG. An electric car says mi/kWh.
- **Missing figures:** fill-ups without the figure you're sorting by go last.

**The totals line**
- **When it shows:** only when a filter is on. Sorting alone doesn't count.
- **What it covers:** the count, gallons or kWh, what you spent, and the average price.
- **Missing costs:** matches with no cost are counted and the line says how many, for example "2 have no cost". They're left out of the average price, as they are elsewhere on the page.
- **No average MPG:** each row keeps its own MPG, worked out from the whole log, so a filter can't change it.

**Moving around**
- **After Show fill-ups:** the page lands on the log, not at the top.
- **After editing or deleting:** you return to the same filtered log. So **No location** works as a to-do list: each fill-up you fix drops off it.
- **Saved links:** a filtered log has its own link you can bookmark. Anything in a link that doesn't fit this car's log is ignored.
- **No matches:** the log says "No fill-ups match these filters." with **Clear filters**.

**What stays the same**
- **The rest of the page:** the figures, charts, Tank to tank and Where you fill up all stay whole-car.
- **Other places:** the car page, Reports and the Copy button are untouched.
- **Under the hood:** no database changes and no new dependencies.

## Code
- **New `web/fuel_finder.py`:** follows `receipt_finder.py`. It holds the sorts, the Needs a look choices, reading the filters from the address, dropping what doesn't fit, building links, and the filtering and sorting itself.
- **`web/fuel_status.py`:** `log_rows` adds the raw figures filtering and sorting need. A new `log_totals()` uses the existing `spent()` and `unit_price()`.
    - Filtering runs after the log is worked out, not in SQL, because each row's MPG and Unusual flag depend on the whole log.
    - A fill-up in other units, from a car's powertrain being corrected later, stays listed but isn't added to the totals.
- **`web/routes_fuel.py`:** the fuel page reads the filters. Edit and delete carry them through and rebuild the link from the checked values, never from a raw address.
- **`fuel.html`, a new `_fuel_filters.html`, and `fuel_form.html`:** the panel, the totals line, the no-matches message, and links that keep the filters, including Cancel.
- **`app.js`:** a small `fuelFilters` that narrows City by State.
- **`app.css`:** reuses the Reports filter styles, plus a little for the panel.

## Tests and checks
- **New `tests/amg/web/test_fuel_finder.py`:**
    - each filter alone and combined
    - two Newarks in different states
    - each sort, with missing figures last
    - bad values in a link ignored
    - home charges in Needs a look
- **`tests/amg/web/test_fuel_pages.py`:**
    - the totals line, worked by hand
    - figures and row MPG unchanged by a filter
    - coming back to the filtered log after edit, delete and Cancel
    - no matches
- **Browser:** I'll try it on made-up fill-ups, including City narrowing and landing on the log, at 360px, in dark mode and at desktop width. The full test suite runs before I call it done.
- **Records:** on approval I'll save this to `docs/plans/` with its index row, and add it to Phase 6 of the roadmap.

## Decisions for you
1. **Do you want the Home or public filter for electric cars?** It was neither Build nor Optional, so it's not in this plan. I'd add it if you have an electric car, since it's one more dropdown shown only on charges, and leave it out otherwise.
2. **Do you want a "Download these" CSV button for the filtered rows?** I've left it out because you didn't pick it. I'd skip it for now unless you need it for expenses or taxes.
