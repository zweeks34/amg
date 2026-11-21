> **Approved** 2026-11-21 · **Roadmap** [Phase 9](../ROADMAP.md#phase-9--reports-and-exports)
>
> **Decided on approval:** A (looks) and B items 1–4 (information) together; the Overview view (C) left for a plan of its own.
>
> **Built in** `7b15c99` feat(reports): richer, better-looking History, Spending and Fuel, and the docs commit
>
> **As built:** As planned, with these details.
> - **Colours:** the budget's three (Engine, Brakes, Tires and wheels); every other category is grey, as on the budget, so a big grey category can lead a year. The cell shading and the share bars are ink, not a category colour.
> - **Figures:** Spending shows the latest year only when there are two or more years, and A mile only once the cars went 500 miles in the dates. With all cars, A mile counts every car's miles, serviced in those dates or not.
> - **History:** a visit's main category is where most of its shown lines' money went; with no amounts, its first typed line's. Narrowed to a service, the gap is to the matching visit before.
> - **By car** rows link to the same report for that car. The year bars and the type picker are hidden for one year, and the picker on paper.

# Richer, better-looking reports

The three report views (History, Spending, Fuel) are each a row of figures and then a plain table or list. AMG
already has visual pieces the reports don't use: the type-of-work colours and stacked month bars from the budget, shop
logos, chips, and the fuel trend chart. This brings those in, and adds figures from data AMG already keeps. No
schema change.

## A — Looks

**Spending**
- A stacked bar for each year above the table, coloured by category (the budget's bars and type picker, without the
  put-aside tape), so picking Brakes shows only brakes across the years.
- Each table cell shaded by its size, so the expensive years and categories stand out. Grey on paper.
- A small bar in the Total column for each category's share of the whole.

**History**
- Visits grouped under year headings, each with that year's count and total.
- A coloured stripe on each visit for its main category (where most of its money went), in Spending's colours.
- The miles and time since the visit before it for the same car ("+5,210 mi · 6 mo").

**Fuel**
- Best and worst months marked in the table, once there are three months measured.
- A second chart beside the economy chart for the price paid each month.

**Everywhere**
- The figure tiles get more weight: a coloured top rule and bigger numbers. Spending compares the latest year with the
  one before ("▲ 12% on 2025").

## B — More information

1. **Maintenance cost a mile** on Spending: what was paid over the miles the cars went in the report's dates (the
   odometer model, clipped to when you had each car), once there are 500 miles behind it.
2. **Labor, parts and fees:** where the money went by line kind, with tax, and what a printed total leaves over, as
   their own rows, so it adds up to what was paid.
3. **Top shops:** spend and visit count for each shop, and your own work, with their logos.
4. **Comparing cars:** with All cars picked and more than one car in the report, Spending adds a table with one row
   per car, years across, and each car's cost a mile.

The CSVs stay as they are: each still holds what its table shows.

## Tests

The new arithmetic in `reports/` (year groups and gaps, kind split, shops, cars, cost a mile, best and worst months,
the year-on-year change), and the pages showing each piece, or not, by what's there. Then the roadmap's Phase 9
section gets the additions.
