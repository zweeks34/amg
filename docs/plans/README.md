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

Also here: [the budget chart options](2026-10-05-budget-chart-options.html), the
four month-bar designs drawn so one could be chosen (open it in a browser; the
figures are made up).

Phases 0–3 were built straight from the build plan, without plans of their own.

## Adding one

When a plan is approved, save it here as `YYYY-MM-DD-short-name.md` with the
header above, add a row to the table, and commit it with the work
(`docs(plans): …`). Add the **As built** note and the commits once it ships.
