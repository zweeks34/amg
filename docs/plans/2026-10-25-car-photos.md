> **Approved** 2026-10-25 21:21 · **Roadmap** [Phase 1](../ROADMAP.md#phase-1--garage-manual-records-extraction-trial)
>
> **Built in** `2bf6d40` feat(garage): a photo for each car, shown as its avatar, `b31db2e` style(garage): make the car avatar 25% larger, and the docs commits
>
> **As built:** As planned, except:
> - **The circle is 25% larger** (`b31db2e`), at your request once you'd seen it: 3.75rem on the garage card (not 3rem), 5.625rem on the car's page and its form, and 3.4375rem in the Fill-up picker. The initial grows with it. Checked at 360px, with nothing scrolling sideways.
> - **Garage cards now line up their names.** The cards in a row share a height, and a shorter card spread its spare height between its rows, which pushed a car's name (and now its avatar) about 25px below its neighbour's. `.carcard` now puts the spare height below (`align-content: start`).
> - **`[hidden]` always hides.** A `.btn` sets its own `display`, so **Remove photo** stayed visible after it was used. One rule beside `[x-cloak]` now makes the `hidden` attribute win everywhere, and the fuel log's own rule for its copy box is dropped.
> - **`avatar_url` checks that the row brought the photo's hash**, so a car row from a query that doesn't join it shows the initial rather than failing.
> - **Checked in the browser** on the scratch garage, with made-up cars. The photo was a made-up car drawn on a canvas in the page and handed to the **Choose a photo** input, so no file from disk, and nothing from `samples/`, was used.
>   1. It showed in the circle before saving, then on the car's page and the garage card.
>   2. A second made-up car with no photo showed "B", now level with the first car's photo.
>   3. The Fill-up picker showed both.
>   4. A bad year sent the form back still holding a newly picked photo, served as its thumbnail. **Remove photo** cleared it, and the form was left unsaved.
>   5. At 360px (no sideways scroll) and in dark mode.
>
> The plan below is as it was approved; it isn't edited afterwards.

# A photo for each car, shown as its avatar

## Context
You'd like to give each car a photo that stands for it around AMG. There's nowhere to put one today. You chose:
- **A round avatar beside the car's name.**
- **The car's initial in that circle when it has no photo**, so every card lines up.

Most of what this needs exists already:
- **Storage:** uploads go into `repo/documents.py`, stored once by content under `data/files/`. A JPEG from a phone is turned upright before it's stored (Pillow, `_upright`).
- **Thumbnails:** `documents.page_image` renders and caches a small JPEG (`/documents/{id}/pages/1?size=thumb`, 480px on the long edge, kept by the browser for good). The garage page never loads full-size phone photos.
- **The picker:** issues already have **Choose photos** and **Take a photo** (`issue_form.html`, `.upload__pick`).
- **Backups:** the Back up zip already holds every stored file.

## How it behaves for you
- **Adding a photo:** **Add a car** and **Edit car** get a **Photo** section.
  - **Choose a photo** or, on a phone, **Take a photo**.
  - The circle shows the photo you picked straight away, before you save.
  - **Remove photo** takes it off.
  - PNG, JPG or GIF. Anything else (a PDF, say) is refused with "add the photo as PNG, JPG or GIF", and the rest of the form stays as you typed it.
  - If something else on the form is wrong, the photo you picked is kept and still shown when the form comes back.
- **Where it shows:**
  - **The garage card:** a 3rem circle beside the name.
  - **The car's page:** a larger circle beside its name. Tapping it opens the photo full size.
  - **The Fill-up car picker** (with more than one car): a small circle beside each name, so you can find the car at the pump at a glance.
- **The crop:** the photo fills the circle, cropped about its centre.
- **No photo:** the circle holds the car's initial in the display face on a tinted ground ("E" for Elantra GT, the first letter or digit of its name). On the car's page it's a link, "Add a photo of Elantra GT", to the Photo section of **Edit car**.
- **Screen readers:** the photo is decorative beside the name it stands for, so it has empty alt text and the name isn't read twice. The page's link says what it does.
- **Download your data:** gains each car's photo in `photos/`, as "Elantra GT, car photo.jpg", and the README says so.
- **A replaced or removed photo's file is kept**, as a discarded receipt's and an issue's removed photos are.

## Code (commit 1: `feat(garage): a photo for each car, shown as its avatar`)
- **`migrations/0020_vehicle_photo.sql`:** `ALTER TABLE vehicles ADD COLUMN photo_document_id INTEGER REFERENCES documents (id);`.
- **`repo/vehicles.py`:**
  - `set_photo(conn, vehicle_id, document_id | None)`.
  - `get` and `garage` join the photo's `documents.sha256 AS photo_sha256`.
- **`repo/fuel.py`:** `cars_by_last_fill` adds the same column.
- **`web/templating.py`:** a global `avatar_url(car)`: `page_url(car.photo_document_id, car.photo_sha256, 1, thumb=True)`, or `None`; and `initial(name)`.
- **New `templates/_avatar.html`:** a macro `avatar(car, size, href=None)` giving the photo or the initial, with `avatar--card`, `--page` and `--pick` sizes.
- **Templates:**
  - `garage.html`: the name and avatar on one line.
  - `vehicle.html`: the heading; with no photo, the initial is a link to `/vehicles/{id}/edit#photo`.
  - `fuel_pick.html`: beside each name.
- **`templates/vehicle_form.html`:**
  - The form becomes `multipart/form-data`.
  - A Photo fieldset (`id="photo"`) goes after `#vehicle-fields`, outside it, so the VIN lookup's swap can't drop a picked file.
  - It reuses `.upload__pick`, with a hidden `photo` (the kept document id) and two file inputs named `photo_file`.
- **`static/app.js`:** a small `carPhoto` component.
  - **Picking a file:** it previews the file (`URL.createObjectURL`) and clears the other input.
  - **Remove photo:** it clears the preview, the hidden id and both inputs.
  - **Showing and hiding:** done with bound `hidden`, as in the fuel log.
- **`static/app.css`:** `.avatar` (a circle with a hairline ring, the image `object-fit: cover`), its three sizes, the initial's type, and the form row.
- **`web/routes_vehicles.py`:**
  - **`_photo(conn, form)`:** gives the document to use and any error. An uploaded file wins, stored with `documents.store` and checked against `issue_words.PHOTO_TYPES`. Otherwise it keeps the hidden id if it names an image; otherwise there's none.
  - **Saving:** `create_vehicle` and `update_vehicle` call `vehicles.set_photo`.
  - **On an error:** the stored photo's id goes back in `raw`, so it's kept.
  - **`_form`** passes the preview's URL.
- **`reports/export.py`:** each car's photo goes in `photos/` as "{car}, car photo", and the README line becomes "your issues' photos, and each car's photo".

## Tests
- **`tests/amg/repo/test_garage_repo.py`:** `set_photo` and clearing it; `get` and `garage` carry `photo_sha256`. **`test_fuel_repo.py`:** `cars_by_last_fill` too.
- **`tests/amg/web/test_vehicle_photos.py`** (new):
  - adding a car with a photo (a small PNG made in the test): the car page, the garage card and the Fill-up picker show its thumbnail
  - **Edit car:** a new photo replaces it, and **Remove photo** brings back the initial
  - a PDF as the photo is refused with the message, and the name typed is kept
  - a bad year with a photo picked: the form comes back keeping the photo, and saving the corrected form keeps it
  - **No photo:** the garage card shows the initial; the car's page links "Add a photo of …" to `/vehicles/{id}/edit#photo`
  - a sideways phone JPEG (EXIF orientation 6) is stored upright
- **`tests/amg/reports/test_export.py`:** the car's photo is in `photos/` and the README mentions it.
- **Existing car-form tests** keep passing; they post without a file.
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: a photo for each car`)
- **`docs/ROADMAP.md`, Phase 1:** an item "(added after the phase shipped, 2026-10-25)": a photo for each car, shown as a round avatar on the garage card, the car's page and the Fill-up picker, the car's initial when there's none. **Data owned** gains `vehicles.photo_document_id`.
- **`CLAUDE.md`:** nothing changes (no new command or setting).
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-car-photos.md` with the header, and an index row. Its commits and As built note are added when it ships.

## Not included
- **Choosing the crop or zoom:** the photo is centred. That could come later if a car sits off-centre in your photos.
- **The photo on the sale packet PDF, the For the shop sheet, the weekly email or the pushes.**
- **Several photos per car, a gallery.**

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (`scratchpad/p16`, made-up cars, and a made-up image generated for the test, never one from `samples/`):
  1. Add a photo on **Edit car**: it previews before saving, then shows on the car's page and the garage card.
  2. Add a second made-up car with no photo: its initial lines up with the first car's photo.
  3. The Fill-up picker shows both.
  4. **Remove photo.**
  5. A bad year keeps the picked photo.
  6. At 360px, on the desktop and in dark mode.
- **After you deploy (yours):** the deploy applies migration 0020 when the app starts. Add your Elantra's photo from your phone with **Take a photo** or **Choose a photo**.
