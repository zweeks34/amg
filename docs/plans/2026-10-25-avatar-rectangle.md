> **Approved** 2026-10-25 22:06 · **Roadmap** [Phase 1](../ROADMAP.md#phase-1--garage-manual-records-extraction-trial)
>
> **Built in** `e484c30` style(garage): the car avatar as a rounded rectangle, and the docs commit that adds this record
>
> **As built:** As planned. Checked in the browser on the scratch garage, with made-up cars:
> - **One screenshot** (the garage) showed both cards' rounded rectangles: the made-up car picture framed on "Hatch", and "B" for "Bolt". After it, the browser's screen capture timed out again, so the rest was checked by measuring the page.
> - **The sizes:** 80 × 60px with 10px corners on the cards; 120 × 90 (15px) on the car's page; 73 × 55 in the Fill-up picker; 224 × 168 (28px) to frame it on **Edit car**, with the 80 × 60 preview beside it.
> - **A real mouse drag** of 56 × 42px, a quarter of the frame's width and of its height, moved the photo by 25 sideways and 25 down, and the preview followed. It was left unsaved.
> - **At 360px:** nothing scrolls sideways on the garage, the car's page, **Edit car** or the Fill-up picker, and the framing area fits inside the form.
>
> The plan below is as it was approved; it isn't edited afterwards.

# The car avatar as a rounded rectangle

## Context
You'd like the car's avatar to be a rectangle with rounded corners, not a circle. A circle suits a face; a car is wide.

The avatar becomes a **4:3 landscape rectangle**, the shape of a phone's landscape photo. At "Whole photo" (zoom 1) a typical car shot then fills it edge to edge, with no tint showing around it.

## How it looks
| Where | Now (circle) | After (height × width) |
|---|---|---|
| Garage card | 60 × 60px | 60 × 80px |
| Car's page | 90 × 90px | 90 × 120px |
| Fill-up picker | 55 × 55px | 55 × 73px |
| Framing on **Edit car** | 176 × 176px | 168 × 224px |

- **The height stays** where it is now, so a card's name line keeps its height. The width grows by a third.
- **The corners:** about a sixth of the height, so 10px on the card and 28px on the framing area. A bigger avatar has rounder corners in proportion, so every size looks alike.
- **A car with no photo** shows its initial in the same rounded rectangle.
- **The framing you've set carries over.** Moves are now measured against the rectangle's width (sideways) and height (up and down), not the circle's. A framing saved in the circle shifts slightly; it can be redone on **Edit car**.
- **Sharpness:** the widest avatar is now 120px. It switches to the larger copy of the photo from 2× zoom, not 2.5×.

## Code (one commit: `style(garage): the car avatar as a rounded rectangle`)
- **`static/app.css`:**
  - `.avatar`: width `calc(var(--avatar) * 4 / 3)`, height `var(--avatar)`, `border-radius: calc(var(--avatar) / 6)`, in place of the circle.
  - The framing area's `--avatar` becomes 10.5rem (168 × 224px, which fits a 360px phone's form).
  - `--avatar` stays each avatar's height.
- **`static/app.js`:** a drag measures x against the frame's width and y against its height (`getBoundingClientRect()`), not the width for both.
- **`web/templating.py`:** `AVATAR_THUMB_ZOOM` becomes 2. Its comment says why: the thumbnail is 480px, the widest avatar 120px, so 240 device pixels.
- **`repo/vehicles.py`:** the `PhotoFrame` docstring says "a share of the avatar's width (x) and height (y)". Migration 0021's comment stays as it was, since that file has run on your server.
- **`templates/vehicle_form.html`:** the hint and the framing area's label say "frame", not "circle", where they mention the shape.

## Tests
- **The avatar's markup and framing values don't change,** so the existing photo tests stand.
- **A test for the new sharpness threshold:** zoom 2.25 now uses the larger copy (`tests/amg/web/test_vehicle_photos.py`).
- `.venv\Scripts\python -m pytest` passes.

## Docs (commit 2: `docs: the car avatar as a rounded rectangle`)
- **`docs/ROADMAP.md`, Phase 1:** the car-photo item says "a rounded rectangle", not "a round avatar".
- **The plan record:** this plan saved verbatim to `docs/plans/2026-10-25-avatar-rectangle.md` with the header, and an index row. Its commits and As built note are added when it ships.

## Verification
- **Tests:** `pytest` passes.
- **In the browser,** on the scratch garage (the made-up car picture on "Hatch", and "Bolt" with no photo), with screenshots this time if the browser can take them:
  - the garage cards, the car's page and the Fill-up picker
  - **Edit car**: drag sideways and up and down, and the "As in the garage" preview following
  - at 360px (no sideways scroll), on the desktop and in dark mode
- **After you deploy (yours):** your Elantra's avatar is a rounded rectangle. If it shifted, reframe it on **Edit car**.
