> **Approved** 2026-11-03 18:39 · **Roadmap** [Phase 6](../ROADMAP.md#phase-6--fuel-and-energy)
>
> **Decided on approval:** the same station in two towns gets separate rows in Where you fill up, and the list holds Canada's provinces and territories as well as the 50 states and DC.
>
> **Built in** `4cfaaba` feat(fuel): the city and state of a fill-up's station, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **The field and the CSV column are "State or province",** not "State", since the list now holds Canada's. The dropdown groups its codes under United States and Canada.
> - **"Your last visit" means the last visit that gave a location.** A later fill-up at the same station with none doesn't forget it.
> - **Clearing City and State by hand** lets the next station you pick fill them in again.
> - **The State column is 8rem.** At 9rem it left City narrower than State at 360px (126px against 144px); now City is 142px and State 128px, with the label still on one line.
> - **One feature commit** covers both the fields and the grouping, as they share the same files.
>
> **Checked on a scratch garage** (made-up stations, separate data directory), with headless Chrome against a scratch copy of the app, 18 checks:
> - **Autofill:** a new fill-up starts blank; a recent station fills in its location, a Canadian one included; another station swaps it; one with no location clears it; a station typed with odd capitals and spacing fills it, and typing on past the name clears it.
> - **What's kept:** a city you typed and a state you chose aren't overwritten, and a location saved on a fill-up stays when you pick another station on its edit page.
> - **Saved through the real form,** the log reads "At Maple Street Service Center in Halifax, NS".
> - **A charge** fills in the same way.
> - **Layout:** no sideways scroll at 360px on the form or the fuel page, City and State line up, and the screenshots at 360px, in dark mode and at 1280px read properly.
>
> The plan below is as it was approved; it isn't edited afterwards.

# City and state on a fill-up

## How it behaves for you

**On the form**
- **New fields:** **City** and **State** sit on one row right under **Station**. Both are optional, like Station. State is a dropdown of two-letter codes.
- **Filling in by station:** when you tap a recent station or type one you've used before, City and State fill in from your last visit there.
    - Picking a different station swaps them, or clears them if that station has no location saved.
    - Anything you typed yourself is never overwritten, and neither is a location already saved on a fill-up you're editing.
- **No copying from your last fill-up:** on a road trip that would quietly save the wrong town, so a new station starts blank.
- **City suggestions:** the City field suggests cities you've used before, as Station does.
- **Charges:** they use the same form, so they get the same fields. A home charge can leave them blank.

**Where it shows**

| Place | How it reads |
|---|---|
| Open log row | "At Shell in Trenton, NJ" ("In Trenton, NJ" if no station is named) |
| Copied line | `Oct 20, 2026 · Shell in Trenton, NJ · 45,210 mi · …` |
| Tank to tank lowest and highest | "2026-10-20 at Shell in Trenton, NJ" |
| Where you fill up | See decision 1 |
| Download your data (fuel CSV) | New **City** and **State** columns after Station |

**What stays the same**
- **Existing fill-ups:** they stay blank until you edit them, and AMG won't guess their location.
- **Logos:** they still go by station name, so two Shells share one logo and one row on Stations and shops.
- **Figures:** economy, the price charts and the Fuel report's monthly numbers don't change.
- **Backups:** older backups still restore, and their fill-ups come in with these fields blank.

**Not included:** detecting your location automatically. Browsers only share location with HTTPS pages, and AMG runs on plain HTTP.

## Code
- **Migration `0025`:** adds `station_city` and `station_state` to `fuel_logs`, both text and blank by default. I'm avoiding a plain `state` because `fuel_status.py` already uses that name for something else.
- **`repo/fuel.py`:**
    - Add the new fields to `FillInput`, and a `STATES` list that `_check` validates against.
    - Add `station_places()` for each station's last location, and `cities()` for the suggestions.
- **`web/routes_fuel.py`:** read, tidy and check the two fields. A bad state gets a plain error message.
- **`fuel_form.html`, `app.js`, `app.css`:** add the City and State row. `fuelForm` watches the station and fills in the location, using the same "don't overwrite what you typed" approach as the home-charge cost.
- **`web/fuel_status.py`:** one `where_words()` helper builds the wording for the log, Copy and Tank to tank.
- **`fuel.html`:** the "At…" line currently shows only when a station is named, so it also needs to show for a location on its own.
- **`reports/export.py`:** add the two CSV columns.
- **If you choose separate rows in decision 1:** `engine.stations()` groups by name, location and state. `where_you_fill` also has to stop keying on name, because its cheapest marker would otherwise break when two rows share a name.

## Tests and checks
- **Tests:**
    - saving and editing a location, spaces tidied, a bad state refused
    - the last location per station
    - the wording with each part missing
    - the CSV columns
    - the grouping, including a tie for cheapest across two locations
- **Browser:** I'd try it on made-up fill-ups, including the autofill, at 360px and in dark mode. The full test suite runs before I call it done.
- **Records:** on approval I'll save this to `docs/plans/` with its index entry, and add the feature to Phase 6 of the roadmap.

## Decisions for you
1. **Should the same station in two towns get separate rows in Where you fill up?** I recommend yes, because it lets you compare prices between locations, and the cheapest marker then applies to each location. The catch is that older fill-ups with no city form their own plain "Shell" row until you edit them. The alternative keeps one row per name and doesn't show the location there at all.
2. **Is a US-only state list OK?** I recommend the 50 states plus DC, because a dropdown means no typos at the pump. If you ever fill up in Canada, I'd add the provinces to the same list.
