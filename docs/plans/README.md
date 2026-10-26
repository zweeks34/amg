# Plans

Every plan approved while building AMG, kept as it was approved. The
[roadmap](../ROADMAP.md) is the living record (what's built, the decisions, what
changed later); these are the proposals each step started from, so you can see
what was asked for, what was agreed, and how the build turned out against it.

Each file opens with when it was approved, the roadmap section it belongs to,
the commits that built it, and, where the build differed from the plan, an
**As built** note. The plan text under that header is never edited: later
changes go in the roadmap, or in a new plan.

| Approved | Plan | Roadmap | Commits |
|---|---|---|---|
| 2026-09-29 | [AMG — Build Plan](2026-09-29-build-plan.md) | Phases 0–3, and the roadmap | `5b19c0b`…`8fcc5d9` |
| 2026-10-02 | [Phase 4: Baseline schedules](2026-10-02-phase-4-baseline-schedules.md) | Phase 4 | `7960750`…`9228e11` |
| 2026-10-02 | [Phase 5: Gap engine, interval chart, dashboard](2026-10-02-phase-5-gap-engine.md) | Phase 5 | `0237463`…`3abfdcb` |
| 2026-10-03 | [Phase 6: Fuel and energy](2026-10-03-phase-6-fuel-and-energy.md) | Phase 6 | `93253d7`…`3bb6706` |
| 2026-10-03 | [Phase 7: Forecast and budget](2026-10-03-phase-7-forecast-and-budget.md) | Phase 7 | `6ea6004`…`fdc4b72` |
| 2026-10-03 | [Find confirmed receipts: sort, filter, search](2026-10-03-receipt-search.md) | Phase 9 (came forward) | `c844ad6`…`69fd80f` |
| 2026-10-03 | [Phase 8: Outbound alerts](2026-10-03-phase-8-outbound-alerts.md) | Phase 8 | `3d60cf2`…`ea63c7a` |
| 2026-10-04 | [Phase 9: Reports and exports](2026-10-04-phase-9-reports-and-exports.md) | Phase 9 | `308b6e7`…`2bc8563` |
| 2026-10-05 | [Phase 10: Inspections and registration](2026-10-05-phase-10-inspections-and-registration.md) | Phase 10 | `b31f72a`…`c1b354d` |
| 2026-10-05 | [Inspection and registration fees in the budget](2026-10-05-fees-in-the-budget.md) | Phase 10 | `8a07141`…`1f6dd31` |
| 2026-10-05 | [The budget, by type of work](2026-10-05-budget-by-type.md) | Phase 7 | `340a197`…`025f310` |
| 2026-10-05 | [Month bars by type: stacked colours with a type picker](2026-10-05-month-bars-by-type.md) | Phase 7 | `a46e363`…`d221869` |
| 2026-10-06 | [Washer fluid as a standard service, and a count-from date for schedule items](2026-10-06-washer-fluid-and-count-from.md) | Phases 1 and 5 | `7cc9516`…`b97d883` |
| 2026-10-07 | [Wiper blades count from the day you deploy, on cars with none on record](2026-10-07-wiper-blades-count-from.md) | Phase 5 | `910d540` |
| 2026-10-07 | [Shop recommendations, recalls and odometer readings](2026-10-07-recommendations-recalls-readings.md) | Phase 11 | `62bbc80`…`05bc3c4` |
| 2026-10-08 | [Specs card](2026-10-08-specs-card.md) | Phase 12 | `7ef5778`…`68bbef4` |
| 2026-10-08 | [Issues list, and a sheet for the shop](2026-10-08-issues-list.md) | Phase 13 | `8bfe8eb`…`12bdff8` |
| 2026-10-09 | [Warranties](2026-10-09-warranties.md) | Phase 14 | `d55a24a`…`5fbb16d` |
| 2026-10-09 | [Running cost](2026-10-09-running-cost.md) | Phase 15 | `8f7bd00`…`2c56175` |
| 2026-10-25 | [Tie a logged service to the schedule job it did](2026-10-25-services-to-schedule-jobs.md) | Phase 5 | `4c18760`…`4735345` |
| 2026-10-25 | [Show each next-up job's action](2026-10-25-next-up-actions.md) | Phase 5 | `08f6f5a` |
| 2026-10-25 | [Edit, copy and delete a fill-up from the fuel log](2026-10-25-fuel-log-actions.md) | Phase 6 | `544fc00` |
| 2026-10-25 | [The action words on the For the shop sheet](2026-10-25-shop-sheet-actions.md) | Phase 13 | `895a998` |
| 2026-10-25 | [The action word on the garage card's Next line](2026-10-25-garage-next-action.md) | Phase 5 | `32b0981` |
| 2026-10-25 | [The action words in the weekly email](2026-10-25-email-actions.md) | Phase 8 | `df4eb09` |
| 2026-10-25 | [The action words in the ntfy pushes](2026-10-25-push-actions.md) | Phase 8 | `57df82c` |
| 2026-10-25 | [The action words in the calendar file](2026-10-25-calendar-actions.md) | Phase 8 | `5997dd8` |
| 2026-10-25 | [A photo for each car, shown as its avatar](2026-10-25-car-photos.md) | Phase 1 | `2bf6d40`…`b31db2e` |
| 2026-10-25 | [Frame a car's photo in its avatar](2026-10-25-car-photo-framing.md) | Phase 1 | `0dc0765` |
| 2026-10-25 | [The car avatar as a rounded rectangle](2026-10-25-avatar-rectangle.md) | Phase 1 | `e484c30` |

Also here: [the budget chart options](2026-10-05-budget-chart-options.html), the
four month-bar designs drawn so one could be chosen (open it in a browser; the
figures are made up).

Phases 0–3 were built straight from the build plan, without plans of their own.

## Adding one

When a plan is approved, save it here as `YYYY-MM-DD-short-name.md` with the
header above, add a row to the table, and commit it with the work
(`docs(plans): …`). Add the **As built** note and the commits once it ships.
