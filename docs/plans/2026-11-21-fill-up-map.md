> **Approved** 2026-11-21 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Decided on approval:** the map drawn by AMG (outlines and dots, offline), not Leaflet with OpenStreetMap tiles; the place and outline data downloaded and kept in the repo, trimmed.
>
> **Built in** `7412b5c` feat(geo): town list and state outlines for the fill-up map, `5247601` feat(fuel): where you filled up, on a map, and the docs commit
>
> **As built:** As planned, with these details.
> - **Outlines:** Natural Earth 1:50m for the US as well as Canada (public domain, one source), not the Census's. At that scale a border can be off by 10–20 km, so the map never zooms closer than 200 km across. A picked state zooms to its dots, not its whole outline.
> - **A name a state has twice** (Hamilton, NJ is two townships): both are kept, and a fill-up goes at the one nearest the middle of your fill-ups whose town is certain. Its row says "Nearest of several".
> - **Fuel and charging** are never on one map, since a gallon's price and a kWh's don't share a scale. A switch shows when you have both. Brands are "Network" for charging.
> - **Close in** (600 km across or less), towns are named beside their dots, the busiest first, and a name that would overlap one already placed is left off. Picking a state on the map zooms to it, and picking it again shows the whole map.
> - **Data:** 57k towns (`places.tsv.gz`, 650 KB) and 64 outlines (`regions.json`, 160 KB), built by `scripts/build_places.py`; sources and licences in `src/amg/geo/SOURCES.md`, with GeoNames credited on the page.

# Fill-up map

Each fill-up has a station name, city and state or province, but no street address or GPS position. So "approximate" here means the middle of the town. AMG already recognises station brands from their names.

## Proposed plan

1. **A new page, Where you filled up** (`/fuel/map`), covering all your cars. Links to it would go on the Fuel report and on each car's fuel page.

2. **Finding each town on the map without sending anything out.** AMG would carry a list of US and Canadian towns with their coordinates (roughly 1–2 MB) and look up each fill-up's city and state in it.
   - The US list would come from the Census Bureau's place-name files, which are public domain. They include townships, which matters in places like NJ, where many towns are townships rather than cities.
   - The Canadian list would come from GeoNames, which requires a credit line.
   - A city the list doesn't know, a typo say, goes at the middle of its state and is marked as such.
   - Fill-ups with no city or state at all aren't placed. The page counts them and links to the log's existing **No location** filter, so you can fill them in.
   - Nothing about where you've been is sent to a geocoding service, and there's no new Python package.

3. **One dot per town** where you've filled up, sized by how many fill-ups it had and tinted by your average price there. Clicking a dot lists that town's fill-ups (date, car, station logo, gallons or kWh, price) and links to the log filtered to that town.

4. **Filters, kept in the address like the other pages:**
   - car
   - from and to dates
   - brand (Shell, Wawa and so on, with unrecognised stations under their own names)
   - state or province
   - city (narrowed to the state you picked)
   - fuel or charging

   A line would say what's showing, e.g. "47 fill-ups in 12 towns across 3 states · 2 placed at their state's middle · 5 with no location".

5. **A table under the map** with the same towns: fill-ups, money spent, average price, and the last visit. It's sortable, and on a phone it's what you'd mostly use.

6. **Tests:**
   - looking up towns, including different capitalisation, "St." versus "Saint", townships, and unknown towns falling back to their state
   - each filter, alone and combined
   - the counts of placed, state-only and unplaced fill-ups
   - the page

There's no database change. Locations are worked out when the page is shown, from the city and state you've already typed.

**The map** is drawn by AMG: state and province outlines with your dots on them, and you zoom by picking a state. It's fully offline.

**Data downloaded and kept, trimmed:** the Census Gazetteer place and county-subdivision (township) files; US state and Canadian province outlines; GeoNames' Canadian places (`CA.zip`), credited on the page.
