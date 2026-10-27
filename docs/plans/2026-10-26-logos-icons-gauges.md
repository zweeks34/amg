> **Approved** 2026-10-26 20:50 · **Roadmap** [Phase 16](../ROADMAP.md#phase-16--logos-icons-and-gauges)
>
> **Built in** `447039a` feat(fuel): the station on each fill-up · `d025693` feat: logos for stations and shops ·
> `9deaea2` feat: an icon for each kind of service · `ff119a4` feat(schedule): interval gauges in Next up ·
> `c21b239` feat(garage): the odometer as rolling drums · `83a58f0` feat(garage): an economy sparkline on each card ·
> and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The fuel log on a phone.** The logo sits at the right of the first line, above the open arrow, not at the row's start: a column of its own wrapped an electric car's date at 360px. The two-line layout now runs to 56rem (it was 48rem), because the logo and seven figures need about 880px on one line. On the desktop each row still starts with its logo.
> - **The station chips** offer the stations for the car's fuel: pumps for a fill-up, chargers for a charge.
> - **Stations and shops** counts fill-ups and charges apart ("3 fill-ups and 1 charge"), gives the day nothing was found in local time, and on a phone puts Change under the words.
> - **The brand table** has 116 brands, not about 80. A few words count only as the whole name, a store number aside ("Gulf", "Irving", "Pilot", "Blink"), so "Gulf Coast Auto Repair" isn't Gulf.
> - **Icons fetched from this machine** on 2026-10-26:
>   - From the site itself: Mobil, Exxon, Sunoco, Wawa (it answered AMG, although it had refused a plain script), Shell, Sheetz, Speedway, Costco, Citgo, Circle K, Electrify America, Jiffy Lube, Valvoline, Midas, Goodyear, Discount Tire, Hyundai, Toyota and Subaru.
>   - By way of DuckDuckGo: Marathon, Firestone, EVgo, Ford and Honda.
>   - A letter: BP (and Amoco, Chevron and BP's other sites) and Pep Boys, which refuse scripts and which the service doesn't have.
> - **Done with no shop** gets the wrench in the History report and on the garage card too, not only in service history. A service's lines and history chips now carry their service type's category, so your own types get their category's icon.
> - **The engine** records where each occurrence's interval was counted from (`Occurrence.from_day`, `from_miles`); `used()` reads the gauge from that.
> - **Screenshots.** The browser extension's screen capture timed out on most pages. So pages were shot with headless Chrome against a scratch copy of the app with the login switched off, on the made-up garage, each in an iframe at the exact width (360px, and desktop), light and dark. The shop sheet was printed to PDF.
>   - Headless Chrome's virtual clock caught the drums mid-roll, so their final digits were checked in the real browser after the roll ("35330"), and shot with reduced motion.
>   - The made-up garage's one odd tank (81.4 mpg, flagged unusual) flattens its sparkline, as it does the fuel page's chart.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Logos, service icons, gauges, a rolling odometer and economy sparklines

## Context
AMG works, but it looks plain. You asked for three things:
- the logos of the fuel brands you fill up at (Mobil, Exxon, Sunoco, Wawa, Shell, Sheetz, Marathon…)
- the logos of the shops that service the cars
- a small icon for each job in Next up: a drop of oil and a filter for an oil change, a spark plug for spark plugs

You chose to have AMG fetch each brand's own website icon. You also chose all four extras I suggested:
- interval gauges
- a rolling odometer
- the service icons everywhere
- an economy sparkline on each garage card

Two things shape the plan:
- **Fill-ups don't record a station today.** That has to be added first, so the logos have something to show.
- **AMG's own paint stays as it is.** Green, yellow and red still mean status only. Brand colours appear only inside a brand's own icon, and the service icons are drawn in ink.

## 1. A station on each fill-up
- **Migration 0022:** `fuel_logs.station`, text, blank when not given.
- **The fill-up form:**
  - A **Station** field, with your five most recent stations above it as one-tap chips that show their logos. Tapping one fills in the field.
  - A list of every station you've used, as typing suggestions.
  - It's optional, and a new fill-up starts blank.
- **The log:**
  - Each row starts with the station's logo. The station's name is the logo's label and also shows when the row is open.
  - **Copy** includes the station: "Oct 20, 2026 · Shell · 45,210 mi · …".
- **Download your data:** `fuel.csv` gains a Station column.
- **Code:**
  - `repo/fuel.py`: `FillInput.station` and `stations(conn)`, recent first, each once whatever its capitals.
  - `routes_fuel.py`.
  - `fuel_form.html`, `fuel.html`.
  - `web/fuel_status.py`: the log row and the copy line.
  - `reports/export.py`.

## 2. Logos for stations and shops
**Recognised from the name** (`web/brands.py`, pure). It's a table of about 80 brands and their websites:
- fuel brands: yours plus BP, Citgo, Valero, Chevron, Speedway, Circle K, QuikTrip, Costco, Royal Farms and others
- EV networks: Tesla, Electrify America, EVgo, ChargePoint
- shop chains: Jiffy Lube, Valvoline, Take 5, Firestone, Goodyear, Pep Boys, Midas, Meineke, Monro, Mavis, Discount Tire, NTB, Les Schwab and others
- car makes, for dealers: "Hyundai of Wesley Chapel" gets Hyundai's icon

How names match:
- Whole words, ignoring capitals and punctuation. "ExxonMobil" and "Mobil 1 Lube Express" match; "Automobile" doesn't.
- A shop chain wins over a car make in the same name.

**Stations and shops** is a new page (`/places`), linked in the footer beside Service types:
- It lists every station on your fill-ups and every shop on your confirmed services, each with its logo, its visit count and what it was recognised as.
- Each one has a **Website** field. Use it to give your local garage its own site, or to correct a match.
- **Show the letter instead** turns a logo off.
- **Fetch again** retries one icon.

**Fetching** (`ingest/site_icons.py`, using stdlib `urllib` and `html.parser` with Pillow; PyMuPDF only for a site that offers just an SVG icon):
1. **The site's own home page:** the icons it declares, largest first (apple-touch-icon, then by `sizes`), then `/apple-touch-icon.png` and `/favicon.ico`. Today Shell, Exxon, Mobil, Sunoco, Sheetz, Speedway, Jiffy Lube, Pep Boys and Hyundai answer this way.
2. **If the site turns AMG away,** DuckDuckGo's public icon service (`icons.duckduckgo.com`) is asked instead. It learns only the site's name, such as `wawa.com`; nothing about you or your cars is sent. Wawa, Marathon and Firestone block scripts today, and the service has all three.
3. **If neither has one,** the logo is a lettered tile. BP refuses both today.
- **Safeguards:**
  - Whatever comes back has to open as an image (some sites answer "200" with a web page).
  - HTTPS only, a 5-second limit and a 1 MB cap.
  - Never an address on your home network, so a website can't point AMG inside your LAN.
  - An honest user agent.
- **Stored as** a 96px square PNG in a new table (migration 0023). A site where nothing was found is tried again after 30 days. Saving a website on Stations and shops fetches it straight away.

**Kept and shown:**
- **Tables** (migration 0023):
  - `places`: a name, its website and "show the letter instead". It only holds the ones you changed.
  - `site_icons`: a site, its PNG and when it was fetched.
- **Pages never wait on the internet:**
  - A logo is an `<img>` from `/logos/<site>.png` over a lettered tile.
  - The first time a site is asked for, that route fetches its icon. If there's none, the image hides itself and the letter shows.
- **The tile:** a 24px rounded square with the same corner proportions as the car avatar. Its background stays white in dark mode too, because brand icons are drawn for white.
- **Without a station or shop:**
  - "Your own work" gets a wrench tile.
  - A fill-up with no station shows nothing.

**Where logos show:**
- the fuel log
- the fill-up form's chips
- the car page's service history and shop recommendations
- the service page's heading
- the receipts list
- the History report
- the garage card's Last service line
- the Stations and shops page

**Download your data:** gains `places.csv`, the websites you typed. The icons themselves aren't included; they can be fetched again.

## 3. Service icons
**`static/icons.svg`** is one sprite of about 30 icons drawn for AMG:
- a 24px grid with 1.75px strokes
- `currentColor`, so ink, or steel where the text is muted
- where a car's dashboard already has a warning light for the thing, the icon borrows its shape: oil can, battery, coolant thermometer in waves, brake "(!)", washer spray, headlamp, check-engine. Drivers read those at a glance.
- the rest drawn in the same line: spark plug, filters, belt, tire, spring, gear and the others

| Icon | Used for |
|---|---|
| oil change (a drop and a filter) | a job covering both engine oil and the oil filter |
| oil can · oil filter · air filter · cabin filter | engine oil · oil filter · engine air filter · cabin air filter |
| spark plug · belt · valve · engine | spark plugs · drive and timing belts · valve clearance · Engine's other types |
| coolant · fuel pump | coolant, cooling system, inverter and battery coolant · fuel lines, fuel filter |
| gear | transmission, differential and transfer case fluid, clutch |
| brake "(!)" · brake disc | brake fluid, brake lines · pads, rotors |
| tire · rotation · alignment | tires, repair, balance, bearings · tire rotation · wheel alignment |
| spring · steering wheel | shocks and struts, axle boots · steering and suspension |
| battery · high-voltage battery | 12-volt battery · hybrid and EV battery items |
| wiper · washer · headlamp · snowflake | wiper blades · washer fluid · lights · air conditioning |
| clipboard · exhaust · flag · chip | inspections · exhaust, emissions test · recall · software update |
| wrench | other repair, and anything unrecognised |

- **`web/service_icons.py`** picks a job's icon from its service types:
  - the oil-and-filter pair gets the oil change icon
  - otherwise it's the first type in catalogue order
  - your own custom service types get their category's icon
- **Drawn by** an `icon()` macro in `_icons.html`, via `<svg><use href="{{ asset('icons.svg') }}#…">`, hidden from screen readers.
- **Where they show** (icons everywhere):
  - Next up, between the R/I/P stamp and the name
  - the garage card's Next line
  - the schedule page
  - the interval chart's names (16px)
  - the service history's chips
  - the service page's lines
  - the shop sheet, which prints in ink
  - the design reference
- **Not in** the email, the pushes or the calendar file: mail apps don't show SVG, and the other two are text.

## 4. Interval gauges in Next up
- **The gauge:** under each job, a 3px track filled to the share of its interval that has gone by.
- **Its colour** follows the job's status:
  - steel when later
  - safety yellow when due soon
  - signal red, full, when overdue
- **Screen readers** hear "62% of the interval gone".
- **The share** is a new pure function in `engine/schedule.py`:
  - It runs from the last time the job was done (that service's day and miles) to when it's next due. Where there's no earlier occurrence, it runs from where the schedule counts from.
  - It goes by miles or by months, whichever is further along, just as the schedule's "whichever comes first" does.
  - It's capped at 100%.
- **Code:** `web/status.py` adds the share to each `next_up` row. `_chart.html` draws it.

## 5. A rolling odometer
- **The drums:** the Odometer figure on the car page and on the garage card (the latest reading) is drawn as odometer drums.
  - Each digit sits in an ink cell in IBM Plex Mono, with the comma kept and "mi" after.
  - On load each drum rolls up to its digit, the right-hand ones turning furthest, in under a second.
  - There's no motion when your phone or computer asks for less.
- **CSS only:** each cell is a 0–9 strip moved to its digit.
- **Screen readers** read the plain figure. The drums are hidden from them.
- **The estimate stays in words.** "Today, estimated ~45,900" is an estimate, not a reading off the dial, so it isn't drawn as drums.
- **Code:** an `odometer()` macro in `_odometer.html`.

## 6. Economy sparklines on the garage cards
- **What it shows:** a car with at least three measured tanks gets an **Economy** fact on its card. It has the last tank's figure (32.4 mpg, or mi/kWh) and a 72 × 20 line of its last 12 tanks.
- **How it's drawn:**
  - by the server, as SVG, like the fuel page's chart
  - a 1.5px ink line, with the latest tank as a dot and the average as a faint dashed line
  - a text summary for screen readers: "from 29.8 to 32.4 mpg, average 31.1"
- **Code:** `engine/fuel.stretches` supplies the tanks, and a helper in `web/fuel_status.py` turns them into the line. `routes_garage.py` hands it to `garage.html`.

## Commits
1. `feat(fuel): the station on each fill-up`
2. `feat: logos for stations and shops`
3. `feat: an icon for each kind of service`
4. `feat(schedule): interval gauges in Next up`
5. `feat(garage): the odometer as rolling drums`
6. `feat(garage): an economy sparkline on each card`
7. `docs: …`, with the roadmap and the plan record

## Tests
No test touches the internet: the fetcher takes its opener as an argument.

| Area | What the tests check |
|---|---|
| **Station** | Saved, kept on edit and shown in the log; the recent-station chips; the copy line; `fuel.csv` |
| **Brands** | Whole-word matching (ExxonMobil, "Automobile"); dealers by make; a chain beating a make |
| **Fetching** | Declared icons ranked; a "200" web page refused; a 403 falling back to the icon service; home-network addresses refused; ICO and SVG made into a 96px PNG |
| **Keeping** | A miss retried after 30 days; the logo route serving a kept icon with caching, and a 404 when there's none |
| **Stations and shops** | Lists stations and shops; saving a website; Show the letter instead |
| **Icons** | Every catalogue type maps to a symbol that exists in `icons.svg` (the sprite is parsed); oil and filter gives the oil change icon; custom types use their category's |
| **Gauges** | Hand-worked cases: miles further along, months further along, overdue capped, no earlier service |
| **Odometer** | The drums' digits and the screen-reader figure |
| **Sparkline** | The line's points; nothing with fewer than three tanks |

`.venv\Scripts\python -m pytest` passes.

## Docs
- **`docs/ROADMAP.md`:** a new **Phase 16 — Logos, icons and gauges**, written the way the phases above it are:
  - For
  - the items
  - Data owned (`fuel_logs.station`, `places`, `site_icons`)
  - Can go wrong (a site changes its icon or blocks AMG; a wrong match)
  - Tests pin
  - Done when
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-26-logos-icons-gauges.md`, with its header, its index row, its commits and an As built note.

## Verification
- **Tests:** `pytest` passes.
- **Real icons:** fetched from this machine for your brands (Mobil, Exxon, Sunoco, Wawa, Shell, Sheetz, Marathon) plus Jiffy Lube, Valvoline and a dealer. The As built note lists which came from the site, which from the icon service, and which got a letter.
- **In the browser,** on the scratch garage with made-up cars, stations and shops, checked at 360px and on the desktop, light and dark:
  - the fuel log
  - the fill-up chips
  - Next up with icons and gauges
  - the schedule page and the chart
  - service history
  - the garage cards with drums and sparklines
  - the shop sheet's print preview
  - Stations and shops
- **Layout:** nothing scrolls sideways at 360px. The fuel log's row has the least room, so it's measured, not guessed.
- **Motion:** the rolling odometer stays still with reduced motion.
- **After you deploy (yours):**
  - Add a station on your next fill-up.
  - Check that your shops' logos look right on Stations and shops, and give your local garage its website.
