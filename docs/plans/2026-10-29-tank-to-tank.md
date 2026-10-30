> **Approved** 2026-10-29 20:38 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Built in** `fe072c4` feat(fuel): tank to tank — lowest, highest, mean and std deviation · `ff869c8` feat(fuel): the usual band on the economy chart · `30679c5` feat(fuel): price paid over time · `8057141` feat(fuel): where you fill up, compared, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **A tie for cheapest marks each station in it.** Stations are compared by the price as shown, so three at $3.299 are all marked, though one was 0.05¢ cheaper. When every station with a price shows the same, none is marked.
> - **The line under Tank to tank** reads "…the Last 12 months figure above weighs each by its miles", naming the figure it means.
> - **Lowest and Highest name the fill that ended the tank**: its date and station, the row in the log where that figure shows.
> - **Four figures sit two by two from 40rem** until there's room for four across. This applies here and on the budget pages, which had three and one.
> - **Three logo tests** now count a fuel page's logos in its log, since Where you fill up shows them too.
>
> **Checked on the scratch garage** (made-up fill-ups), with headless Chrome against a scratch copy of the app:
> - **Hatch, gas:** Tank to tank reads 29.8 to 34.0 mpg, mean 31.9, ±1.4 with 5 of 8 within; the unusual 81.4 mpg tank is left out and said so. The band sits under the eight usual dots. The price chart runs $3.20–$3.40, and three stations tie for Cheapest at $3.299.
> - **Bolt, EV:** Charge to charge waits for a third charge. The price chart is in cents a kWh, and Where you charge lists Electrify America (Cheapest) and EVgo.
> - At 360px and on a desktop, in light and dark, nothing scrolls sideways.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Tank to tank: lowest, highest, mean and std deviation, the usual band, price over time, and stations compared

## Context
Each car's fuel page shows these figures, then Over time, then the log:
- Last tank, Last 12 months and All time
- Cost a mile, Spent and Price paid

You asked for the lowest, highest, mean and standard deviation of mpg alongside the average, and for other suggestions. Your answers:
- Leave unusual tanks out of the new figures.
- Use the last 12 months.
- Add the usual band on the chart, Price over time, and Stations compared.

**Mean and average differ, on purpose.** The existing figures are miles over gallons (Phase 6's rule), so a long tank counts for more. The mean you asked for is each tank's own figure averaged, so every tank counts alike. Both will show, and a line on the page says which is which. In the hand-worked test log, the plain mean is 29.67 and miles over gallons is 29.28.

## What you'll see on the fuel page (gas and EV alike)
**1. Tank to tank** ("Charge to charge" for an EV): a new section under the figures with four figures, two by two on a phone and four across on a desktop.

| Figure | Example value | Example note |
|---|---|---|
| Lowest | 25.0 mpg | 2026-09-20 at Shell #4 |
| Highest | 30.0 mpg | 2026-06-15 at Wawa |
| Mean | 27.0 mpg | of 4 tanks |
| Std deviation | ±2.4 mpg | 3 of 4 tanks within 24.6–29.4 |

- **The muted line under the heading** says three things:
  - which tanks: the last 12 months, or all time when the last year has fewer than 3
  - how many unusual tanks were left out: "1 unusual tank left out"
  - that the mean counts every tank alike, while Last 12 months above weighs each by its miles
- **When it shows:** the section needs at least 3 usual tanks.
- **Ties:** when two tanks tie for lowest or highest, the more recent one is named.
- **Std deviation** is the sample standard deviation. Its note counts the actual tanks inside mean ± 1 std deviation; it doesn't assume a bell curve. When every tank is the same, the note says so ("all 3 tanks at 30.0").

**2. Over time gains the usual band.** A light shaded strip shows mean ± 1 std deviation, behind the dots and the dashed average.
- It covers only the months it describes: from 12 months ago to now, or the full width when it's all time.
- The legend gains "Usual: 24.6–29.4 mpg, mean ± 1 std deviation".
- The chart's scale stretches so the band is never clipped.
- The band is drawn in ink at low opacity, so it works in both themes and keeps green, yellow and red for status.

**3. Price over time.** A second chart under the economy one, inside Over time, drawn the same way:
- One dot for each fill-up with a cost, partial ones included, joined by a line.
- A dashed line for the average price paid over the last 12 months, which matches the Price paid figure.
- Gridlines at round prices: $3.40 / $3.50 for gas, 15¢ / 20¢ for kWh.
- Each dot's tooltip gives the date and the price. For an EV it also says Home or Public, since those prices differ a lot.
- It shows from two priced fill-ups.
- Each chart gets a small label: "Economy" and "Price paid".

**4. Where you fill up** ("Where you charge" for an EV): one row for each station named in the last 12 months (all time if none).
- **Each row:** the station's logo and name, "4 fill-ups · $152.40", and its average price paid ("$3.459/gal").
- **Order:** most visits first.
- **Cheapest:** a "Cheapest" tag in ink marks the lowest average price, once at least two stations have prices.
- **Grouping:** stations go by the name as written, ignoring case and extra spaces. "Shell #4" and "Shell Route 9" stay separate, since comparing them is the point.
- **EV home charges** with no station named are counted as **Home**.
- **Unnamed fills:** other fills with no station are left out, and a line says so ("2 fill-ups don't name a station").

**Order on the page:** figures, Tank to tank, Over time (economy, then price), Where you fill up, The log.

## Code
**`src/amg/engine/fuel.py`** (pure; no stations' names beyond grouping):
- **`spread(found, flagged, since=None)`** returns a `Spread`, or None with fewer than 3. `Spread` holds:
  - `count` and `left_out`
  - `lowest` and `highest` (Stretches; on a tie, the later one)
  - `mean`, `stdev` (`statistics.stdev`) and `within`
- **`MIN_FOR_SPREAD = 3`.**
- **`Fill` gains `station: str = ""`.**
- **`stations(fills, since=None)`** returns a list of `StationSum(name, fills, spent, unit_price)`:
  - grouped on the name lower-cased with spaces collapsed, showing the most recent spelling
  - most fills first, then by name
  - plus the count of fills with no station, returned beside the list

**`src/amg/web/fuel_status.py`:**
- **`_fill(row)`** passes the station; an EV home charge with none counts as "Home".
- **`spread_span(state)`:** the last 12 months when they hold 3 or more usual tanks, else all time.
- **`spread_figures(state)`** returns the four `_figure`s and the muted line, worded with `economy_words`.
- **`trend(state)`** adds `band`: its y range, the x where it starts, and the label.
- **`chart()`** is split so an economy chart and a price chart share one drawing function: `_chart(points, average, span, unit, per, words, steps, tick)`.
  - `chart()` keeps its signature and output, so the Fuel report is untouched.
  - **`price_trend(state)`** uses the shared function, with price steps `{"gal": (10, 20, 25, 50, 100), "kWh": (1, 2, 5, 10, 20)}` in cents.
- **`where_you_fill(state)`** returns rows with the cheapest marked and the unnamed count.

**`src/amg/web/routes_fuel.py`:** `fuel_page` passes `spread`, `price_trend` and `stations`.

**Templates:**
- `fuel.html` gets the Tank to tank section, the second chart, and Where you fill up. The station rows reuse `logo()` from `_logo.html`.
- `_fuel_chart.html` draws the band as a `<rect class="trend__band">` before the gridlines, with its legend key, and adds an optional label above each chart.

**`static/app.css`:**
- the Tank to tank grid reuses `.figures .figures--four`
- `.trend__band` and its key: ink at about 8% opacity
- `.fuelsum__*` for the station rows, phone first: logo, name and counts, price right-aligned
- the "Cheapest" tag in ink
- no sideways scroll at 360px

## Tests
- **`tests/amg/engine/test_fuel.py`**, worked by hand on the existing log:
  - **Last 12 months** (B to F, with E left out as unusual): 25, 28, 30, 25.
    - lowest 25 is F, the later of the tie; highest 30 is D
    - mean 27.0, sample std deviation √6 = 2.449
    - 3 of 4 within 24.55–29.45; 1 left out
  - **All time:** 25, 25, 28, 30, 25. Mean 26.6, std deviation √5.3 = 2.302.
  - **Fewer than 3:** returns None.
  - **`stations()`** on the log with stations added: grouping across case and spacing, the most recent spelling, the order, spent and price, and the unnamed count.
- **`tests/amg/web/test_fuel_pages.py`:**
  - the Tank to tank figures and line on the `_steady` car, which has every tank the same plus one unusual
  - the band's y and x on the trend
  - the price chart's points, ticks and average
  - Where you fill up with a Cheapest tag, an EV's Home row, and the unnamed line
  - nothing shows below the minimums
- **Existing fuel and report tests** pass unchanged; the report's chart output must not change.

## Commits
1. `feat(fuel): tank to tank — lowest, highest, mean and std deviation`
2. `feat(fuel): the usual band on the economy chart`
3. `feat(fuel): price paid over time`
4. `feat(fuel): where you fill up, compared`
5. `docs: …`
   - Phase 6 gains these items ("added after the phase shipped, 2026-10-29").
   - Phase 6's decision "never a mean of each tank's figure" gains "except Tank to tank's Mean, which says so".
   - Phase 16's decision "The estimate stays in words" is corrected, now that today's estimate has drums (`f937b8a`).
   - The plan's record goes in `docs/plans/2026-10-29-tank-to-tank.md` with a README row.

## Verification
- **Tests:** `pytest` passes.
- **Screenshots:** headless Chrome on the scratch garage (made-up fills, with stations added for the trial), of Hatch (gas) and Bolt (EV):
  - at 360px and on a desktop, light and dark
  - no sideways scroll
  - the band lines up with the dots it describes
  - the Cheapest tag and the Home row read right
- **Real browser:** check by reading the page, as before.
