> **Approved** 2026-10-26 22:23 · **Roadmap** [Phase 16](../ROADMAP.md#phase-16--logos-icons-and-gauges)
>
> **Built in** `fffdca7` feat: upload your own logo for a station, shop or brand, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **A name you've given its own website** takes an upload for itself, not its brand: its website would otherwise come before the brand's logo, and the upload wouldn't show. The upload hint says which ("For every BP station or shop", "For Shell on Main").
> - **Picking a logo while "Show the letter instead" is ticked** unticks it, so the logo you picked is the one shown.
> - **Migration 0024** also adds `places.added`, which keeps a place you set up listed until a fill-up or service names it.
>
> **Checked on the scratch garage**, with made-up pictures (a green circle on a clear ground, and a lettered square), not real brands' logos:
> - The circle uploaded on "BP #4" shows on every BP row and in the fuel log, on the tile's white in dark mode as well as light, and nothing is fetched from bp.com.
> - The square shows for Joe's Gas only, and "Corner Tire & Lube" added before a visit sits under Not visited yet.
> - At 360px, Stations and shops, with BP's Change panel open, doesn't scroll sideways. Its labels are Upload a logo, Remove your logo for every BP, Website and Show the letter instead.
> - The browser extension's screen capture still timed out, so the pages were shot with headless Chrome against a scratch copy of the app, and the open panel was checked in the real browser by reading the page.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Upload your own logos for stations and shops

## Context
Some stations and shops have no logo:
- AMG doesn't recognise your local garage.
- BP and Pep Boys refuse to hand over their icons.
- You might want a different picture for one AMG fetched.

You asked for a place to upload logos yourself. You had no preference on where it lives or how far an upload reaches, so this plan uses the recommended choices:
- **Where:** on the **Stations and shops** page you already have (footer).
- **Reach:** a logo uploaded for a brand AMG recognises covers every station of that brand.

## What you'll see
**On Stations and shops**, each row's **Change** panel gains:
- **Upload a logo** (PNG, JPG or GIF), beside Website and Show the letter instead. The hint says what it covers:
  - "For every BP station or shop" on a name AMG recognises as BP. One upload covers "BP #4", "BP Route 9" and any BP logged later.
  - "For Joe's Garage" on a name it doesn't recognise.
- **Remove your logo**, once there is one. The logo goes back to the fetched icon, or the letter.
- The row's sentence says where the logo comes from: "Your logo, for every BP." or "Your logo."

**Add a station or shop** is a new form at the foot of the page:
- It takes a name and a logo or a website, so a place is ready before your first fill-up or visit there.
- Places you've set up but not visited yet are listed under **Not visited yet**, with the same controls.

**Wherever logos show** (the fuel log and its chips, service history, receipts, reports, the garage card), your upload appears in the same white tile.

**Which logo a name gets**, first match wins:
1. Show the letter instead, if you chose it for that name.
2. Your logo for that name.
3. The website you gave that name.
4. For a recognised brand: your logo for the brand, else the brand's fetched icon.
5. Its letter.

## Code
**Data (migration 0024):**
- `places.logo_document_id`: your logo for one name.
- A new `brand_logos` table (brand, document, when): your logo for a recognised brand.
- Uploads are stored like car photos (`repo/documents.store`), so they're in backups.

**`repo/logos.py`:**
- `set_place` keeps a row that has a logo or that you added.
- `set_logo` and `remove_logo`, for one name or for a brand.
- `brand_logos` and `added()` (places not visited yet).

**`web/logos.py`:**
- `Logo` carries the upload (its document id and fingerprint) and whom it's for.
- `Book` applies the order above, reading `places` with each logo's document, and `brand_logos`, once a page.

**`templates/_logo.html`:** an upload is shown from the stored file's small rendering (`page_url(..., thumb=True)`), not `/logos/<site>.png`.

**`routes_logos.py`:**
- `POST /places` takes the multipart form: website, letter, a picked logo, or Remove your logo.
- `POST /places/add` takes a name, plus a logo or a website.
- It refuses anything but PNG, JPG and GIF the way the car photo does: "logo.pdf: add the logo as PNG, JPG or GIF."

**`places.html`:** the upload control, the Add form, and the Not visited yet section, styled like the rest of the page, phone first.

**Download your data:**
- A `logos/` folder with your uploads, named for what they cover ("BP.png", "Joe's Garage.jpg").
- `places.csv` gains a Logo column, and lists brand logos too.

## Tests (`tests/amg/web/test_logos_pages.py`, `tests/amg/reports/test_export.py`)
- **Covering a brand:** a logo uploaded on "BP #4" shows for "BP Route 9" and in the fuel log, and the route never fetches bp.com for it.
- **One name:** a logo uploaded for an unrecognised name shows for that name only.
- **The order:** letter-only beats your logo; your logo for a name beats your logo for its brand; your brand logo beats the fetched icon.
- **Removing** goes back to the fetched icon.
- **Refused:** a PDF, with the message, and the page comes back with nothing changed.
- **Adding** a place before visiting: it's listed under Not visited yet, and moves to Stations once a fill-up names it.
- **Download your data:** the `logos/` folder and the csv's Logo column.

## Commits
1. `feat: upload your own logo for a station, shop or brand`
2. `docs: …`, with Phase 16 gaining the item ("added after the phase shipped, 2026-10-26") and this plan's record

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage with made-up pictures (plain coloured squares with letters, not real brands' logos):
  - Upload one for BP #4 and see it on every BP row and in the fuel log.
  - Upload one for Joe's Gas.
  - Add a not-yet-visited shop.
  - Remove a logo.
  - Check at 360px and on the desktop, light and dark, with no sideways scroll.
- **A transparent PNG** sits on the tile's white, not on black.
- **After you deploy (yours):** upload BP's and Pep Boys' logos, and your local garage's.
