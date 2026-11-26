> **Approved** 2026-11-25 · **Roadmap** [Phase 9](../ROADMAP.md#phase-9--reports-and-exports)
>
> **Decided on approval:** donuts, not full pies; the lists stay beside them.
>
> **Built in** `c102b35` feat(reports): donuts on Spending, each beside its list, and the docs commit
>
> **As built:** As planned, with these changes.
> - **Four slices at most, not five.** No four shades of one colour could be told apart (the closest pair was ΔE 11; the floor is 15), so it's three blues, darkest for the biggest, then grey for the fourth part or for Everything else. All pairs were checked at 15 or more in light and dark. Rows that went into Everything else wear its grey, and pointing at one lights them all.
> - **The category donut is grouped as the year bars' key is:** Engine, Brakes, and Tires and wheels in their colours, then Everything else in grey, with the categories in it named under its row. So a category keeps one colour all down the page, though a big category without a colour of its own (Steering and suspension, say) is in Everything else.
> - **Labor, parts and fees now lists the biggest first**, as its donut goes.
> - Each car's share is its own section. The By car table, year by year, stays below it.
> - In the half-width cards the donut sits above its list, which keeps names from wrapping. They sit side by side only where there's room.

# Pie charts on Spending

## Proposed plan

1. **Three donut charts** (a pie with a hole in the middle, where I'd put the total), one for each breakdown the page already has:
   - **By category** (oil changes, brakes, tires…) across the whole date range
   - **Labor, parts and fees**: this is where a pie works best, since it's usually 3–5 parts of one bill
   - **Who did the work**: each shop, your own work, and work with no receipt

   **By car** gets one too when there's more than one car. With a single car, or with the car filter set, it doesn't show.

2. **At most five slices each**: the four biggest, then "Everything else" combining the rest, since thin slices side by side can't be told apart.
   - The category chart uses the same colours as the year bars and table above it, so each category keeps its colour across the page.
   - The others use shades of one colour, darkest for the biggest slice.

3. **The lists stay, beside each donut.** They give the exact amounts and percentages and serve as its legend. Hovering a slice or its row highlights both. On a phone, each donut sits above its list.

4. **Drawn by AMG** as plain SVG, like the map, with no chart library. They print, work offline, and each has a text description for screen readers.

5. **Tests:**
   - the slices add up to the total
   - "Everything else" appears only past five parts
   - no chart for one car
   - a refund or discount never makes a negative slice
