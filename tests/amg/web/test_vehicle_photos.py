"""A car's photo: added on its form, shown as its avatar, its initial when there's none."""

from __future__ import annotations

import html
from io import BytesIO

from PIL import Image

from amg.repo import documents, fuel, vehicles


def png(colour="red", size=(60, 40)):
    out = BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def page(signed_in, url):
    return html.unescape(signed_in.get(url).text)


def _add(signed_in, files=(), **fields):
    data = {"name": "Elantra GT", "year": "2019", "make": "Hyundai", "model": "Elantra GT", "powertrain": "gas",
            "photo": "", **fields}
    return signed_in.post("/vehicles", data=data, files=list(files), follow_redirects=False)


def _thumb(conn, car):
    row = vehicles.get(conn, car)
    return f"/documents/{row['photo_document_id']}/pages/1?v={row['photo_sha256'][:12]}&size=thumb"


def test_adding_a_car_with_a_photo_shows_it_as_its_avatar(signed_in, conn):
    response = _add(signed_in, files=[("photo_file", ("elantra.png", png(), "image/png"))])
    assert response.status_code == 303
    car = int(response.headers["location"].rsplit("/", 1)[1])
    thumb = _thumb(conn, car)
    assert documents.get(conn, vehicles.get(conn, car)["photo_document_id"])["filename"] == "elantra.png"
    car_page = page(signed_in, f"/vehicles/{car}")
    assert f'<img src="{thumb}" alt="" loading="lazy" style="--z: 1; --dx: 0%; --dy: 0%">' in car_page   # whole
    assert 'aria-label="Open the photo of Elantra GT full size" target="_blank"' in car_page
    assert f'<img src="{thumb}"' in page(signed_in, "/")                               # the garage card
    vehicles.create(conn, vehicles.VehicleFields(name="Bolt", powertrain="ev"))
    picker = page(signed_in, "/fuel/new")                                            # two cars: the picker
    assert f'<img src="{thumb}"' in picker and '<span class="avatar avatar--pick avatar--initial" aria-hidden="true">B</span>' in picker


def test_with_no_photo_its_initial_stands_in(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="'98 Outback"))
    assert '<span class="avatar avatar--card avatar--initial" aria-hidden="true">9</span>' in page(signed_in, "/")
    car_page = page(signed_in, f"/vehicles/{car}")
    assert (f'<a class="avatar avatar--page avatar--initial" href="/vehicles/{car}/edit#photo"'
            f' aria-label="Add a photo of \'98 Outback">9</a>') in car_page
    form = page(signed_in, f"/vehicles/{car}/edit")
    assert 'id="photo"' in form and 'enctype="multipart/form-data"' in form and "Take a photo" in form


def test_editing_replaces_or_removes_it(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Elantra GT"))
    first, _ = documents.store(conn, png("red"), "red.png")
    vehicles.set_photo(conn, car, first["id"])
    data = {"name": "Elantra GT", "powertrain": "gas"}
    form = page(signed_in, f"/vehicles/{car}/edit")
    assert f'name="photo" value="{first["id"]}"' in form and "Remove photo" in form

    signed_in.post(f"/vehicles/{car}/edit", data={**data, "photo": str(first["id"])},
                   files=[("photo_file", ("blue.png", png("blue"), "image/png"))])
    assert documents.get(conn, vehicles.get(conn, car)["photo_document_id"])["filename"] == "blue.png"

    signed_in.post(f"/vehicles/{car}/edit", data={**data, "photo": ""})               # Remove photo
    assert vehicles.get(conn, car)["photo_document_id"] is None
    assert "avatar--initial" in page(signed_in, f"/vehicles/{car}")


def test_a_kept_photo_survives_saving_the_form_without_a_new_one(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Elantra GT"))
    photo, _ = documents.store(conn, png(), "red.png")
    vehicles.set_photo(conn, car, photo["id"])
    signed_in.post(f"/vehicles/{car}/edit", data={"name": "Elantra GT Sport", "powertrain": "gas",
                                                  "photo": str(photo["id"])})
    assert vehicles.get(conn, car)["photo_document_id"] == photo["id"]
    assert vehicles.get(conn, car)["name"] == "Elantra GT Sport"


def test_a_pdf_is_refused_and_the_form_keeps_what_was_typed(signed_in, conn):
    response = _add(signed_in, files=[("photo_file", ("brochure.pdf", b"%PDF-1.4", "application/pdf"))])
    assert response.status_code == 422
    text = html.unescape(response.text)
    assert "brochure.pdf: add the photo as PNG, JPG or GIF." in text and 'value="Elantra GT"' in text
    assert vehicles.garage(conn) == ([], [])


def test_a_picked_photo_is_kept_when_something_else_is_wrong(signed_in, conn):
    response = _add(signed_in, year="19x9", files=[("photo_file", ("elantra.png", png(), "image/png"))])
    assert response.status_code == 422
    (stored,) = conn.execute("SELECT id, sha256 FROM documents").fetchall()
    text = html.unescape(response.text)
    assert f'name="photo" value="{stored["id"]}"' in text
    assert f'src="/documents/{stored["id"]}/pages/1?v={stored["sha256"][:12]}"' in text   # still shown, to frame
    response = _add(signed_in, photo=str(stored["id"]))                                 # the year put right
    car = int(response.headers["location"].rsplit("/", 1)[1])
    assert vehicles.get(conn, car)["photo_document_id"] == stored["id"]


def _framed(signed_in, conn, **frame):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Elantra GT"))
    photo, _ = documents.store(conn, png(), "red.png")
    signed_in.post(f"/vehicles/{car}/edit", data={"name": "Elantra GT", "powertrain": "gas", "photo": str(photo["id"]),
                                                  **frame})
    return car


def test_a_photo_framed_your_way_shows_so_everywhere(signed_in, conn):
    car = _framed(signed_in, conn, photo_zoom="1.5", photo_x="-10", photo_y="5")
    row = vehicles.get(conn, car)
    assert (row["photo_zoom"], row["photo_x"], row["photo_y"]) == (1.5, -10, 5)
    framed = f'<img src="{_thumb(conn, car)}" alt="" loading="lazy" style="--z: 1.5; --dx: -10%; --dy: 5%">'
    assert framed in page(signed_in, "/") and framed in page(signed_in, f"/vehicles/{car}")
    form = page(signed_in, f"/vehicles/{car}/edit")
    assert 'name="photo_zoom" type="range" min="1" max="4" step="0.05"' in form and 'value="1.5"' in form
    assert 'name="photo_x" value="-10.0"' in form and 'name="photo_y" value="5.0"' in form
    assert 'style="--z: 1.5; --dx: -10%; --dy: 5%"' in form and "Show the whole photo" in form


def test_framing_is_kept_in_range(signed_in, conn):
    car = _framed(signed_in, conn, photo_zoom="9", photo_x="-300", photo_y="sideways")
    row = vehicles.get(conn, car)
    assert (row["photo_zoom"], row["photo_x"], row["photo_y"]) == (4, -100, 0)


def test_zoomed_far_in_the_avatar_uses_the_larger_rendering(signed_in, conn):
    car = _framed(signed_in, conn, photo_zoom="3")
    row = vehicles.get(conn, car)
    larger = f'/documents/{row["photo_document_id"]}/pages/1?v={row["photo_sha256"][:12]}"'
    assert f'<img src="{larger} alt=""' in page(signed_in, "/") and "size=thumb" not in page(signed_in, "/")


def test_a_form_sent_back_keeps_its_framing_and_removing_the_photo_resets_it(signed_in, conn):
    car = _framed(signed_in, conn, photo_zoom="2", photo_x="12.5")
    photo = vehicles.get(conn, car)["photo_document_id"]
    response = signed_in.post(f"/vehicles/{car}/edit", data={"name": "Elantra GT", "year": "19x9", "powertrain": "gas",
                                                             "photo": str(photo), "photo_zoom": "2.5", "photo_x": "20"})
    assert response.status_code == 422
    assert 'style="--z: 2.5; --dx: 20%; --dy: 0%"' in html.unescape(response.text)
    signed_in.post(f"/vehicles/{car}/edit", data={"name": "Elantra GT", "powertrain": "gas", "photo": "",
                                                  "photo_zoom": "2", "photo_x": "12.5"})            # Remove photo
    row = vehicles.get(conn, car)
    assert (row["photo_document_id"], row["photo_zoom"], row["photo_x"], row["photo_y"]) == (None, 1, 0, 0)


def test_a_sideways_phone_photo_is_stored_upright(signed_in, conn):
    exif = Image.Exif()
    exif[0x0112] = 6                                       # "rotate 90° to show": how phones mark a portrait shot
    jpeg = BytesIO()
    Image.new("RGB", (60, 40), "green").save(jpeg, "JPEG", exif=exif)
    response = _add(signed_in, files=[("photo_file", ("IMG_0042.jpg", jpeg.getvalue(), "image/jpeg"))])
    car = int(response.headers["location"].rsplit("/", 1)[1])
    stored = documents.path(documents.get(conn, vehicles.get(conn, car)["photo_document_id"]))
    assert Image.open(stored).size == (40, 60)


def test_the_picker_and_the_garage_without_photos_look_as_before_but_for_the_initial(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Wagon"))
    fuel.create(conn, car, fuel.FillInput("2026-09-01", 1_000, "gas", 10.0))
    assert "<img" not in page(signed_in, "/").split('<ul class="cars">')[1]
