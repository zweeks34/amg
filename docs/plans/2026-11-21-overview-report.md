> **Approved** 2026-11-21 · **Roadmap** [Phase 9](../ROADMAP.md#phase-9--reports-and-exports)
>
> **Decided on approval:** Overview is the first view and what `/reports` opens to; the next 12 months are in. Added on approval: a month-to-month comparison that is honest about the gaps in the records (item 9).
>
> **Built in** `e515356` feat(reports): the Overview, what the cars cost to run, and the docs commit
>
> **As built:** As planned, with these details.
> - **Links:** a bare `/reports` opens the Overview; an address with filters but no view still opens History, so older links keep working, and every link the page makes names its view. The car page's Report button now says `view=history`.
> - **Order:** cheapest a mile first, but a car whose fuel isn't counted follows the cars whose is, since it only looks cheaper. A car with nothing recorded shows a dash, not 0¢, and goes last.
> - **Next 12 months** is left off a card when the budget has nothing priced and no fuel to go on.
> - **Hatching:** a year's fuel bar is hatched by the gap rule too (mostly estimated), while the year table keeps the car page's "est." for any estimate. A month the dates only partly cover (the current one, the month you got a car) is shown but not compared.
> - **The garage's months** count a car's fuel toward the gap rule only when that car's fuel is counted at all. The figures note which cars' fuel isn't counted.
> - **The printed heading** is "What it costs to run · …". On paper, months folded under "Show all" stay folded.

# Overview: what the cars cost to run

The car page already has a **Running cost** block for each car: fuel, service and fees, a cost per mile since you got it, a row per year, and the next 12 months. The Overview doesn't repeat that one car at a time. Its job is the view across the whole garage, and it follows the report filters (car and dates). It reuses the same arithmetic as that block (`engine/running_cost.py`), so the two pages agree.

## Proposed plan

1. **A fourth view, Overview,** next to History, Spending and Fuel. The car and date filters apply; service and shop don't, the same as Fuel. Sold (archived) cars are included, as in the other reports.

2. **Garage figures across the top:**
   - what it cost to run in the dates you picked
   - the cost per mile
   - the cost per month
   - a split into fuel, service and repairs, and fees (registration and inspections)

3. **One card per car, cheapest per mile first:**
   - its cost per mile in large type
   - a bar split into fuel, service and fees
   - miles driven, the total, and how long the dates cover

   Each card links to that car's Running cost block on its own page.

4. **Year bars:** each year split into fuel, service and fees, for the whole garage or for the car you pick. This reuses the Spending bars. They'd be drawn in shades of grey and ink rather than the category colours, so blue still only ever means Engine.

5. **A table by year:** miles, fuel, service, fees, total and cost per mile, with a total row. Fuel that's estimated is marked "est.", as on the car page. That happens when there are miles no logged fill-up measured, and those miles are counted at the car's usual fuel cost per mile.

6. **The next 12 months,** taken from the budget: what each car is expected to cost, so you can see the past next to the expected future. This only shows when no end date is picked, since it's about the future.

7. **A CSV** of the year table: a row per car and year, with cents.

8. **Tests:** dates clipped correctly; the totals match each car page's Running cost; estimated fuel is marked; a car with no odometer readings is listed with the reason; the page, the CSV and the filters.

9. **Month to month, with the gaps shown** (added on approval). Each month's fuel, service and fees, as bars and a table, newest first.
   - **Fuel a month** spreads each logged tank across the days it covered, so a fill-up on March 2 pays mostly for February's driving rather than landing in March. Miles no tank covers are estimated at the car's usual cost a mile, as the year table does.
   - **A gap month** is one where logged fill-ups cover less than half the miles the odometer says were driven. Its fuel is estimated: hatched on its bar, marked in the table, and left out of the typical month.
   - **The typical month** is the average over the months with records, and each month shows how it compares (▲/▼). A gap month shows no comparison rather than a misleading one.
   - The last 24 months show; the rest open under "Show all N months".
   - Because tanks are spread by day here and counted in the month they ended in the year table, the months can add up to a slightly different year total. The page says so.
