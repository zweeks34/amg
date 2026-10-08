> **Approved** 2026-10-08 15:23 · **Roadmap** [Phase 13](../ROADMAP.md#phase-13--issues-and-the-sheet-for-the-shop)
>
> **Built in** `8bfe8eb` feat(issues): note what's wrong with a car, with photos, until a visit fixes it, `12bdff8` feat(issues): a sheet for the shop: your issues, what's due and what was recommended, and the docs commit that adds this record
>
> **As built:** As planned, except:
> - **Photo thumbnails** load a 480px render: page images gained `size=thumb` (`documents.THUMB_LONG_EDGE`, `page_url(..., thumb=True)`), rather than a 1600px preview shrunk to 6rem (`8bfe8eb`).
> - **`repo.issues.photos()`** isn't a function of its own: `everything()` gives each issue its photos and checks, and the export reads them from there. The README's count line adds "N photo(s)".
> - **The service page's block** is headed "Your issues", with one **All of them** link to the car's issues rather than a link per row; it asks "Did this visit fix it?".
> - **Fixing by a visit you'd said it was still there after** removes that check, so a visit is never both.
> - **Checked in the browser** on the scratch garage with made-up issues and generated photos: still there and fixed then from the car's and the service's pages, the garage count, and the sheet at 360px, on the desktop, in dark mode and in print. Nothing needed changing.
>
> The plan below is as it was approved; it isn't edited afterwards.

# Issues list, and a sheet for the shop

## Context
You picked idea 6: notes like "rattle at 40 mph" to take to the next shop visit, closed by the service that fixes them. Today the only record of what's wrong with a car is your memory until a receipt says something. You chose:
- **AMG asks after visits** whether a later service fixed it, and keeps "still there", so the shop sees what's been tried
- **photos** of a leak, a warning light or a worn part
- **a visit sheet** for the shop: your open issues, plus what's due and what was recommended, on one page that prints

It ships as roadmap Phase 13: two feature commits and a docs commit. There are no Claude calls and no new dependencies.

## How it behaves for you

### Noting an issue
- **Where:** a new **Issues** section on the car's page, between Recalls and Shop recommendations, with **Note an issue** in its heading. It always shows. Empty, it says: "Noises, leaks, warning lights: note them here to show the shop on your next visit."
- **The form** (its own page, made for the phone):
  - **What's wrong** (required, under 120 characters), e.g. "Rattle from the front at 40 mph"
  - **Details** (optional), hinted: "When it happens (speed, cold or warm, turning, braking), where it seems to come from, how often."
  - **Noticed on** (today by default, never in the future)
  - **Photos:** **Choose photos** or **Take a photo**, several at once, up to 10 on an issue. Each photo is stored on its own, as receipt scans are, so each shows as its own picture. Photos stay attached if the form comes back with an error.
  - **Save issue** and Cancel
- **Edit** opens the same form, where you can remove photos or add more, plus **Delete issue** (with a confirm).

### On the car page
- **Each open issue shows:**
  - its title, and "Noticed Sep 2, 2026, at about 91,800 mi". The miles are estimated from your readings and left out when there are none.
  - its details and photo thumbnails (tap for full size)
  - what's been tried: "Still there after Valley Honda on Sep 20, 2026"
- **The question:** once a confirmed service is logged on or after the day you noticed it, the issue asks about the newest one: "Did Valley Honda fix it on Sep 20?" With no shop: "Did your work on Sep 20 fix it?"
  - **Yes, fixed then** closes the issue with that visit.
  - **No, still there** records the try, and the question goes away until the next visit.
  - Services marked "Done, no receipt" aren't visits and are never asked about.
- **Actions:**
  - **It's fixed** opens a small form like the recalls' one: **When** lists your visits since you noticed it, newest first, plus "Another time" with a **Fixed on** date. The date can't be before you noticed it.
  - **Edit**
  - **Drop it**, for one that went away or that you'll live with
- **Closed issues** fold under "N fixed or dropped", each with "Fixed Sep 20, 2026 at Valley Honda" (linked to the service), "Fixed Oct 1, 2026" or "Dropped Oct 8, 2026", and **Undo** to reopen it.

### On a service's page
- **Fixed on this visit:** the issues closed by this service, each linked to the car's issues.
- **The question appears here too,** for each open issue it would ask about this visit. Logging a service by hand lands on this page, so you're asked right away. A confirmed receipt goes on to the next receipt, and the car's page asks instead.

### The garage card
- "2 issues" in its tally, next to "N recommended".

### For the shop: the visit sheet
- **Where:** **For the shop** in the car page's header, beside Specs. It opens `/vehicles/{id}/for-the-shop`.
- **What it shows, in order:**
  - **The car:** year, make, model and trim, engine, VIN, plate, and the odometer ("about 92,400 mi today", or the last reading and its date)
  - **Please look at:** your open issues, numbered so you can say "number 2". Each has its details, when you noticed it, what's been tried, and its photos.
  - **Due now:** schedule jobs overdue or due soon, with when ("1,200 mi overdue", "by Nov 12")
  - **Recommended before:** open shop recommendations from the last 12 months, with the shop and date
- **No prices.** It's the page you hand over; the budget stays on the car's page.
- **When there's nothing to ask for:** it says so ("No open issues, nothing due, and no open recommendations").
- **Printing:** **Print** prints just the sheet, headed with the car's name, with photos small and a "From AMG, Oct 8, 2026" line at the foot. On the phone you can just show the screen.

### Not included
- **No pushes or email lines.** You wrote these down yourself, and nothing about them falls due.

### Download your data
- **`issues.csv`:** car, issue, details, noticed, status, closed on, fixed by (date and shop), still there after, and photo count
- **A `photos/` folder:** each issue's photos, named by date, issue and car

## Code

### Commit 1: `feat(issues): note what's wrong with a car, with photos, until a visit fixes it`
- **New `src/amg/migrations/0017_issues.sql`:**
  - **`issues` table:**
    - `id`, `vehicle_id` (CASCADE)
    - `title` (`CHECK <> ''`), `details`, `noticed_on`
    - `status`: open, fixed or dropped
    - `closed_on`, and `fixed_by_event_id` (→ service_events, SET NULL, so deleting the service keeps the fix and its date)
    - `created_at`, `updated_at`
  - **`issue_photos` table:** `issue_id` (CASCADE), `document_id` (CASCADE), `position`; primary key `(issue_id, document_id)`
  - **`issue_checks` table** (a visit you said didn't fix it): `issue_id` (CASCADE), `event_id` (CASCADE), `created_at`; primary key `(issue_id, event_id)`
- **New `src/amg/engine/issues.py`** (pure, no I/O):
  - `Visit(id, day, shop)`
  - `since(noticed_on, visits)`: visits on or after that day, newest first
  - `to_ask(noticed_on, visits, checked) -> Visit | None`: the newest of those, unless you've already said it was still there after it
- **New `src/amg/repo/issues.py`:**
  - **Writing an issue:** `IssueInput(title, details, noticed_on)`; `create(conn, vehicle_id, input, photo_ids)`, `update(conn, issue_id, input, photo_ids)` (the photo list replaced whole, in order) and `delete`
  - **Reading:** `get`, and `for_car(conn, vehicle_id)` with photos (document rows), checks (with each visit's date and shop) and the fixing service's date and shop
  - **Closing:** `fix(conn, issue_id, day, event_id=None)`, `drop(conn, issue_id, day)`, `reopen` and `still_there(conn, issue_id, event_id)`
  - **Visits:** `visits(conn, vehicle_id)`: confirmed services that aren't "Done, no receipt", newest first
  - **Elsewhere:** `fixed_by(conn, event_id)` for the service page, `open_counts(conn)` for the garage, and `everything(conn)` and `photos(conn)` for the export
- **New `src/amg/web/issues.py`:** words and form parsing
  - `load(conn, car, odometer=None) -> Section(open, closed)`. Each row carries:
    - its noticed words and estimated miles
    - photo URLs, built with `templating.page_url`, a preview and full size
    - its "still there after" words and the question
    - the visits for **It's fixed**, and its closed words
  - `question(visit)`, and `day_words` reused from `web/recalls.py`
  - `parse(form) -> (IssueInput, raw, errors)`, with these messages:
    - "Say what's wrong, such as Rattle at 40 mph."
    - "Keep it under 120 characters. The details can say more."
    - "Keep the details under 2,000 characters."
    - "That's before you noticed it, on Sep 2, 2026."
  - `store_photos(conn, form, kept)`:
    - stores each upload with `documents.store`
    - takes PNG, JPG and GIF only: "{name}: add photos as PNG, JPG or GIF."
    - at most 10: "An issue holds up to 10 photos."
    - keeps photos already attached via hidden `photo` ids, which must be image documents
- **New `src/amg/web/routes_issues.py`:**
  - GET `/vehicles/{id}/issues/new`, POST `/vehicles/{id}/issues`
  - GET and POST `/issues/{id}/edit`, POST `/issues/{id}/delete`
  - POST `/issues/{id}/fixed`: a `service_event_id` from the car's visits since noticed, else a `fixed_on` date. Errors come back on the car page, as `recall_form` does.
  - POST `/issues/{id}/still-there`, `/issues/{id}/drop` and `/issues/{id}/reopen`
  - Redirects go to `/vehicles/{id}#issues`, or back to `/services/{event}#issues` when posted from a service's page (`back=service`, the only other target taken)
  - registered in `app.py`
- **Templates:**
  - **New `issue_form.html`:** the file inputs as on the specs card; kept photos as thumbnails with **Remove**, an Alpine list of hidden `photo` inputs
  - **New `_issues.html`:** the row, question and fixed-form macros, shared by the car's page and the service's page
  - **`vehicle.html`:** the Issues section, and the **For the shop** button (it gets its route in commit 2, so the button lands then)
  - **`service.html`:** the Issues block
  - **`garage.html`:** "N issues"
- **`routes_vehicles.car_page`:** passes `issues=issue_words.load(conn, car, state.odometer)` and `issue_form` for errors
- **`routes_services.service_page`:** passes the fixed and asked issues
- **`routes_garage`:** `car["issues"]`
- **`app.css`:** `.issues`, `.issue__*`, and `.issue__photos`, a thumbnail grid that wraps at phone width
- **`src/amg/reports/export.py`:** `issues.csv`, the `photos/` folder, and the README and docstring lines

### Commit 2: `feat(issues): a sheet for the shop: your issues, what's due and what was recommended`
- **New `src/amg/web/shop_sheet.py`:** `load(conn, car, today=None)`, built from existing pieces:
  - the car's facts
  - the odometer, from `status.load` (`today_miles`, `vehicles.latest_odometer`)
  - the open issues, from `issue_words.load`
  - `status.next_up(state, limit=0)`, which gives only the overdue and due-soon rows
  - `follow_up_words.load(...).recent`
- **Route:** GET `/vehicles/{id}/for-the-shop` in `routes_issues.py`
- **New template `for_the_shop.html`:** the printhead, a Print button, the four blocks, the empty state and the footer line
- **`vehicle.html`:** the **For the shop** button in `pagehead__actions`
- **`app.css`:** `.shopsheet__*`, and print rules: the sheet's buttons hidden, `.shopsheet__issue` kept whole on a page, photos 4 cm wide

## Tests
- **`tests/amg/engine/test_issues.py`:**
  - `to_ask`:
    - asks about the newest visit on or after the noticed day, including one that same day
    - never asks about one before it
    - stays quiet once you've said "still there" after the newest
    - asks again after a newer visit
- **`tests/amg/repo/test_issues_repo.py`:**
  - create, update and delete, with the photo list replaced in order
  - fix, drop and reopen
  - `still_there`
  - deleting the fixing service keeps the issue fixed on its date
  - deleting a service drops its check
  - `visits` leaves out "Done, no receipt" and unconfirmed ones
  - deleting the car takes its issues
- **`tests/amg/web/test_issue_pages.py`:**
  - the empty section and **Note an issue**
  - saving with photos, including one taken as a PNG (`rf.image_bytes`)
  - errors: no title, too long, a PDF as a photo, more than 10 photos, a date in the future
  - photos kept when the form comes back with an error
  - edit: removing a photo, and delete
  - the question after a later visit: **Yes, fixed then** closes it with the visit; **No, still there** shows "Still there after…" and the question goes until the next visit
  - **It's fixed** with a visit, or with a date, and a date before noticing refused
  - drop and undo
  - the service page's "Fixed on this visit" and its question, posting back to the service
  - the garage count
- **Visit sheet** (in the same file, commit 2):
  - the car's facts and odometer
  - the issues numbered, with their photos
  - only overdue and due-soon jobs
  - only recent open recommendations
  - no dollar amounts anywhere on it
  - the empty state
- **`tests/amg/reports/test_export.py`:** `issues.csv` and `photos/`
- **Every commit:** `.venv\Scripts\python -m pytest` passes.

## Docs (commit 3: `docs: Phase 13, issues and the sheet for the shop`)
- **`docs/ROADMAP.md`:** **Phase 13 — Issues and the sheet for the shop**, in the usual shape:
  - For, and the checklist (ticked)
  - **Decisions:**
    - AMG asks, it doesn't decide: a later visit closes nothing by itself, because a shop can look at a rattle and miss it
    - "still there" is kept as what's been tried
    - no prices on the sheet
    - no pushes
  - Data owned, Can go wrong, Tests pin, Done when
- **The plan:** saved to `docs/plans/2026-10-08-issues-list.md` with the header, and an index row

## Verification
- **Tests** pass after every commit.
- **The scratch garage** (`scratchpad/p11/data`, made-up data, no Claude calls):
  - note an issue on the Civic with a generated photo, and log a service by hand after it, so the service page asks
  - **No, still there**, then a second service and **Yes, fixed then**; drop and undo
  - the garage count
  - the visit sheet with an issue, an overdue job and a recommendation
- **Layout:** the car page section, the form, the service page block and the sheet at 360px and on the desktop, in light and dark, plus the sheet's print preview.
- **Done when (yours), after you deploy:**
  - the next thing you notice goes in as an issue, with a photo if it shows
  - the sheet goes to the next shop visit
  - the visit after it gets asked about and answered
