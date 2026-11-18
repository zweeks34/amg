> **Approved** 2026-11-17 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Decided on approval:** items 1–3; no car switcher on the log page (item 4). Item 4 was approved the next day, 2026-11-18.
>
> **Built in** `01b3320` feat(fuel): reach the fill-up log from the car page, the form and the picker, `b11d9c7` feat(fuel): switch cars on the fill-up log, keeping the filters, and the docs commits
>
> **As built:** As planned. The form's link also shows when editing a fill-up.
> - **Item 4, the car switcher:** a row of pills under the log's heading, one for each car with a fill-up or charge, in name order, with the car you're on filled in. It shows only when there's more than one. An archived car's log still shows its own pill. A link keeps the filters and sort, and the log it opens drops a state, city or station it doesn't hold, as it does for any address.

# Easier to reach the fill-up log

Today the only way to the fill-up log is: Garage → the car → scroll past schedule, recalls, issues, follow-ups, warranties and renewals to the fuel section → the "The fill-up log" button. The masthead's **Fill-up** link always opens the *new fill-up form*, and with one car it skips the picker entirely, so there's no route to the log from there.

## Proposed plan

1. **Vehicle page header:** add a **Fill-up log** button (or **Charge log** for an EV) to the top action row, next to Edit car, Specs and For the shop. It only appears once the car has at least one fill-up, the same rule as the existing button. This gets you to the log in one click from the car, with no scrolling.
2. **Fill-up form:** add a **The fill-up log** link in the page header. This fixes the one-car path: masthead **Fill-up** → form → log, without going through the vehicle page.
3. **"Which car?" picker** (when you have several cars): give each car a small **Log** link next to it, so the masthead also gets you to any car's log in two clicks. It sits beside the car's tile rather than inside it, because a link can't sit inside another link.
4. **Switching cars on the log page** (with several cars): a small row of the other cars' names under the heading, so you can compare logs without going back. Each link keeps your current filters and sort if they still apply.
5. **Tests:** route tests checking each link appears, or doesn't, by fill-up count and number of cars. Then save the plan to `docs/plans/2026-11-17-fill-up-log-access.md`, add it to the index, and tick it off in the ROADMAP.

I'm leaving the garage card alone. The whole card is one link, so putting a log link inside it would mean rebuilding the card.

**What I recommend:** items 1–3 are the core. Item 4 only matters if you often compare cars, so I'd drop it unless you want it.
