> **Approved** 2026-10-25 21:47 · **Roadmap** [Phase 1](../ROADMAP.md#phase-1--garage-manual-records-extraction-trial)
>
> **Built in** `0dc0765` feat(garage): frame a car's photo in its avatar, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **No screenshots were taken.** The browser's screen capture timed out on every page, including ones without an avatar, so how the whole photo sits in the circle wasn't seen. The behaviour was checked instead by driving the page on the scratch garage (the made-up car picture on "Hatch") and reading back what it did:
>   - **A real mouse drag** of 44px across the 176px framing circle moved the photo 25% of a circle width, and the small "As in the garage" circle followed.
>   - **The keys:** the arrow keys moved it 2 (Shift: 10) without scrolling the page; three typed "+" and one "−" took the zoom to 1.2×, and the slider followed.
>   - **The slider** set 3.2×, and **Show the whole photo** put it back to 1×, centred.
>   - **Saving** a framing of 1.6×, moved left and down: the car's page, the garage card and the Fill-up picker all carried it.
>   - **At 360px** nothing scrolls sideways, the framing circle and the zoom row fit, and dragging doesn't scroll (`touch-action: none`).
> - **"+" and "−" were checked as typed characters.** The browser tool's named "plus" and "minus" keys never reached the page.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Frame a car's photo in its avatar: the whole photo by default, zoom and move to adjust

## Context
The avatar crops the photo to fill its circle (`object-fit: cover`). A car photo is wide, so the circle keeps the middle and cuts off both ends, and you can't see enough of the car. You asked for zoom in and out, or some adjustment.

The fix has two parts:
1. **The whole photo by default.** At zoom 1 the circle shows the whole photo, whatever its shape, on the circle's tint (`object-fit: contain`). A wide car shows nose to tail.
2. **Your own framing, kept with each car.** On **Edit car** you can zoom in, from the whole photo to 4×, and drag the photo to sit where you like. The garage card, the car's page and the Fill-up picker all show it framed your way.

Photos already on your server change from the crop to the whole photo when this deploys, because that's the new default. Each can then be framed as you like.

## How it behaves for you
On **Add a car** and **Edit car**, once there's a photo, the Photo section shows:

```
PHOTO
 ╭─────────────╮      ╭──╮
 │             │      │  │  As in the garage
 │   (photo)   │      ╰──╯
 │             │
 ╰─────────────╯
 Zoom  Whole photo ●────────── Close up
 [Choose a photo] [Take a photo] Remove photo   Show the whole photo
 Drag the photo to move it, or select it and use the arrow keys.
```
- **A bigger framing circle** (11rem) to work in, with a small circle beside it, "As in the garage", showing the same framing at card size.
- **Zoom:** a slider from "Whole photo" (1×) to "Close up" (4×).
- **Move:** drag the photo with a finger or the mouse. While you drag, the page doesn't scroll.
- **The keyboard:**
  - Tab to the circle, then use the arrow keys to move (Shift moves further) and + and − to zoom.
  - The circle is labelled "Photo framing", with how to use it.
- **Show the whole photo** puts it back to 1×, centred.
- **A new photo starts whole and centred**, and so does **Remove photo**.
- **Nothing changes until you save.** If another field sends the form back, your framing comes back with it.
- **Sharpness:** a photo zoomed past 2.5× is shown from the larger rendering, not the small thumbnail. The framing circle always uses the larger one.

## Code (commit 1: `feat(garage): frame a car's photo in its avatar`)
- **`migrations/0021_vehicle_photo_frame.sql`:** three columns on `vehicles`:
  - `photo_zoom REAL NOT NULL DEFAULT 1 CHECK (photo_zoom BETWEEN 1 AND 4)`
  - `photo_x`, `photo_y REAL NOT NULL DEFAULT 0 CHECK (… BETWEEN -100 AND 100)`, how far it's moved, as a share of the circle's width
  - It's a new migration, not an edit to 0020, which may already have run on your server.
- **`repo/vehicles.py`:**
  - `PhotoFrame(zoom=1.0, x=0.0, y=0.0)`.
  - `set_photo(conn, vehicle_id, document_id, frame=PhotoFrame())` writes the photo and its framing. Removing the photo resets the framing.
  - The rows from `get`, `garage` and `fuel.cars_by_last_fill` already bring `v.*`.
- **`web/templating.py`:**
  - `avatar_url(car)` asks for the thumbnail up to 2.5×, else the preview size.
  - New `frame_style(car)` gives `--z: 1.5; --dx: -10%; --dy: 5%`.
- **`templates/_avatar.html`:** the `<img>` carries `style="{{ frame_style(car) }}"`.
- **`static/app.css`:**
  - `.avatar img` becomes `object-fit: contain; transform: translate(var(--dx, 0%), var(--dy, 0%)) scale(var(--z, 1))`, so the zoom is about the centre and the move is in circle widths.
  - `.avatar--frame` is 11rem, `touch-action: none`, with a grab cursor and a focus ring.
  - The zoom row and the "As in the garage" pair.
- **`templates/vehicle_form.html`:** the Photo section's circle becomes the framing circle, with:
  - the small "As in the garage" circle
  - the Zoom slider (`type="range"`, labelled, 1–4, step 0.05) and **Show the whole photo**, shown only while there's a photo
  - hidden `photo_zoom`, `photo_x` and `photo_y` inputs
  - the circle's image from the preview size
- **`static/app.js`:** `carPhoto` gains `zoom`, `x` and `y`.
  - **Dragging:** `pointerdown`, `pointermove` and `pointerup` with pointer capture move it by the pointer's distance as a share of the circle's width, kept within −100…100.
  - **Keys:** the arrow keys move it 2 (10 with Shift), and + and − zoom 0.1.
  - **Resetting:** `whole()` puts it back to 1×, centred. Picking a photo and **Remove photo** call it.
  - **The style:** a `frame` getter gives the style both circles bind.
- **`web/routes_vehicles.py`:**
  - `_frame(form) -> PhotoFrame`: each value a number clamped to its range; anything unreadable is the default (the values come from a slider and a drag, not typing).
  - `create_vehicle` and `update_vehicle` pass it to `set_photo`.
  - `raw` keeps the three values, so a form sent back keeps the framing.
  - `edit_vehicle` fills them from the car.

## Tests
- **`tests/amg/repo/test_garage_repo.py`:**
  - a car's framing defaults to whole and centred (1, 0, 0)
  - `set_photo` stores a frame
  - removing the photo resets it
  - the database refuses a zoom of 5
- **`tests/amg/web/test_vehicle_photos.py`:**
  - saving zoom 1.5, x −10, y 5: the garage card's and car page's `<img>` carry `--z: 1.5; --dx: -10%; --dy: 5%`
  - values out of range are clamped (zoom 9 → 4, x −300 → −100), and an unreadable one is the default
  - at zoom 3 the avatar's image is the preview size (no `size=thumb`), at 1.5 the thumbnail
  - the form shows the slider at the saved zoom and the hidden values
  - a bad year sends the form back with its framing
  - **Remove photo** resets the framing
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: frame a car's photo in its avatar`)
- **`docs/ROADMAP.md`, Phase 1:** the car-photo item gains "the whole photo by default; zoom (to 4×) and drag to frame it on Edit car, kept with the car". **Data owned** names the three framing columns (migration 0021).
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-car-photo-framing.md` with the header, and an index row. Its commits and As built note are added when it ships.

## Not included
- **Rotating the photo.** Phone photos are already turned upright when stored.
- **A blurred copy of the photo behind the whole-photo view.** The circle's tint fills around it.

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (made-up cars, the made-up car picture already on "Hatch"):
  - the whole made-up car shows in the garage card's circle by default
  - on **Edit car**: drag, the slider, the arrow keys and + / −, with the small circle following, and **Show the whole photo**
  - save, and the card, the car's page and the Fill-up picker show the framing
  - a zoom past 2.5× still looks sharp
  - at 360px (dragging doesn't scroll the page), on the desktop and in dark mode
- **After you deploy (yours):** migration 0021 runs when the app starts. Your Elantra's avatar shows the whole photo; on **Edit car**, zoom and drag it until it looks right, then save.
