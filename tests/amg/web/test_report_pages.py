"""The Reports page: its three views, the filters in the address bar, the CSVs, and the ways in."""

from __future__ import annotations

import html
import io
import zipfile
from datetime import date

import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import fuel


def test_nothing_to_report_says_how_to_start(signed_in):
    page = signed_in.get("/reports").text
    assert "Nothing to report yet. Add a car" in page and "Show the report" not in page
    assert 'href="/reports" aria-current="page"' in page                     # the footer link
    assert "Confirm receipts or log services" in signed_in.get("/reports?view=history").text
    assert "Log a fill-up or a charge" in signed_in.get("/reports?view=fuel").text


def test_the_history_with_its_filters_in_the_form(signed_in, conn):
    ids = rf.garage(conn)
    page = signed_in.get(f"/reports?car={ids['outback']}&from=2019-01-01&service=category%3ABrakes&shop=midas").text
    assert f'<option value="{ids["outback"]}" selected>Outback</option>' in page
    assert 'value="2019-01-01"' in page and 'value="midas"' in page
    assert '<option value="category:Brakes" selected>Any brakes work</option>' in page
    assert "Midas #1234" in page and "Front brake pads" in page and "Oil and filter change" not in page
    assert "and 1 other line" in page and "On brakes" in page and "$200.00" in page
    assert "Service history · Outback · Brakes · at “midas” · from Jan 2019 · printed" in page   # the printed heading
    assert 'href="/reports/history.csv?car=' in page and "Clear filters" in page


def test_every_service_without_filters(signed_in, conn):
    rf.garage(conn)
    page = signed_in.get("/reports?view=history").text
    assert page.count('class="visit__head"') == 5 and "Your own work" in page and "Done, no receipt" in page
    assert "Clear filters" not in page and "$640.00" in page                    # what the five came to


def test_nothing_matching_offers_to_clear(signed_in, conn):
    rf.garage(conn)
    page = signed_in.get("/reports?shop=nowhere").text
    assert "No services match." in page and '<a href="/reports?view=history">Clear filters</a>' in page


def test_spending_by_year(signed_in, conn):
    ids = rf.garage(conn)
    page = signed_in.get(f"/reports?view=spending&car={ids['civic']}").text
    assert '<th scope="col" class="num">2021</th>' in page and "Brakes" in page and "$300.00" in page
    assert "Other is lines with no service type" in page
    assert 'href="/reports?view=history&amp;car=' in page and 'aria-current="page">Spending</a>' in page   # the view switch


def test_fuel_month_by_month(signed_in, conn):
    car = rf.car(conn, "Outback")
    for day, odometer, gallons in (("2026-08-02", 1_000, 12.0), ("2026-08-16", 1_300, 10.0), ("2026-09-01", 1_590, 10.0)):
        fuel.create(conn, car, fuel.FillInput(day, odometer, "gas", gallons, cost_cents=3_500))
    page = signed_in.get("/reports?view=fuel").text
    assert "Aug 2026" in page and "Sep 2026" in page and "29.5 mpg" in page     # 590 miles on 20 gallons
    assert "mpg each month" in page                                             # the trend, a dot a month
    assert 'name="service"' not in page                                         # fuel has no service or shop


def test_csv_downloads(signed_in, conn):
    ids = rf.garage(conn)
    response = signed_in.get(f"/reports/history.csv?car={ids['outback']}")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert f'filename="amg-history-outback-{date.today().isoformat()}.csv"' in response.headers["content-disposition"]
    assert response.text.startswith("﻿Car,Date,Odometer") and "Front brake pads" in response.text
    spending = signed_in.get("/reports/spending.csv").text
    assert spending.startswith("﻿Category,2019,") and "amg-spending-all-cars" in signed_in.get(
        "/reports/spending.csv").headers["content-disposition"]
    assert signed_in.get("/reports/fuel.csv").text.startswith("﻿Car,Month,Fill-ups")
    assert signed_in.get("/reports/budget.csv").status_code == 404


def test_the_car_page_links_to_its_report(signed_in, conn):
    ids = rf.garage(conn)
    assert f'href="/reports?view=history&amp;car={ids["outback"]}">Report</a>' in signed_in.get(f"/vehicles/{ids['outback']}").text
    empty = rf.car(conn, "Bare")
    assert "/reports?car=" not in signed_in.get(f"/vehicles/{empty}").text


def test_reports_need_a_session(client, conn):
    rf.garage(conn)
    assert client.get("/reports", follow_redirects=False).status_code == 303
    assert client.get("/reports/history.csv", follow_redirects=False).status_code == 303


def test_the_sale_packet_downloads_for_a_chosen_car(signed_in, conn):
    car = rf.car(conn, "Outback", year=2016, make="Subaru", model="Outback")
    rf.receipt(conn, car, rf.pdf_bytes("MIDAS"), "midas.pdf", date="2017-08-09", shop_name="Midas")
    page = signed_in.get(f"/reports?car={car}").text
    assert f'href="/vehicles/{car}/sale-packet.pdf" download>Download the sale packet (PDF)</a>' in page
    assert "your name and address on a receipt show" in page
    assert "sale-packet.pdf" not in signed_in.get("/reports").text                       # no car chosen
    assert "sale-packet.pdf" not in signed_in.get(f"/reports?view=spending&car={car}").text
    response = signed_in.get(f"/vehicles/{car}/sale-packet.pdf")
    assert response.headers["content-type"] == "application/pdf" and response.content.startswith(b"%PDF")
    assert (f'filename="2016-subaru-outback-service-history-{date.today().isoformat()}.pdf"'
            in response.headers["content-disposition"])
    assert signed_in.get("/vehicles/999/sale-packet.pdf").status_code == 404


def test_the_sale_packet_needs_a_session(client, conn):
    car = rf.car(conn, "Outback")
    assert client.get(f"/vehicles/{car}/sale-packet.pdf", follow_redirects=False).status_code == 303


def test_your_data_downloads_from_the_reports_page(signed_in, conn):
    car = rf.car(conn, "Outback")
    rf.receipt(conn, car, rf.pdf_bytes("MIDAS"), "midas.pdf", date="2017-08-09", shop_name="Midas")
    assert 'href="/reports/your-data.zip" download>Download your data (.zip)</a>' in signed_in.get("/reports").text
    assert 'href="/reports#data-heading">Download your data</a>' in signed_in.get("/backup").text
    response = signed_in.get("/reports/your-data.zip")
    assert response.headers["content-type"] == "application/zip"
    assert f'filename="amg-your-data-{date.today().isoformat()}.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert "receipts/2017-08-09 Midas - Outback.pdf" in zf.namelist()


def test_your_data_needs_a_session(client, conn):
    assert client.get("/reports/your-data.zip", follow_redirects=False).status_code == 303


def test_the_history_by_year_with_stripes_and_gaps(signed_in, conn):
    rf.garage(conn)
    page = signed_in.get("/reports?view=history").text
    assert page.count('class="visityear"') == 4 and 'id="year-2021"' in page
    assert "2 services · <span class=\"mono\">$340.00</span>" in page        # 2021: the oil change and the rotors
    assert 'class="visit visit--2" title="Mostly brakes"' in page and "2 yr 2 mo" in page


def test_spending_shows_the_bars_the_kinds_the_shops_and_the_cars(signed_in, conn):
    rf.garage(conn)
    page = signed_in.get("/reports?view=spending").text
    assert 'class="mbars' in page and "Spending each year" in page and "Put aside" not in page
    assert "▼ 100% on 2023" in page and "--heat: 1.0" in page
    assert "Labor, parts and fees" in page and "Who did the work" in page and "MIDAS Auto" in page
    assert 'id="spend-cars"' in page and 'href="/reports?view=spending&amp;car=' in page


def test_one_cars_spending_has_no_by_car_table(signed_in, conn):
    ids = rf.garage(conn)
    page = signed_in.get(f"/reports?view=spending&car={ids['civic']}").text
    assert 'id="spend-cars"' not in page and 'class="mbars' not in page      # one car, one year


def test_spending_a_mile_once_the_odometer_says(signed_in, conn):
    from amg.repo import odometer
    ids = rf.garage(conn)
    for day, miles in (("2019-01-01", 40_000), ("2025-01-01", 100_000)):
        odometer.add(conn, ids["outback"], day, miles)
    page = signed_in.get(f"/reports?view=spending&car={ids['outback']}&to=2024-12-31").text
    assert "A mile" in page and "0.6¢" in page and "mi driven" in page        # $340 over about 60,000 miles


def test_fuel_marks_the_best_and_worst_and_charts_the_price(signed_in, conn):
    car = rf.car(conn, "Outback")
    for day, odo in (("2026-01-02", 1_000), ("2026-01-20", 1_300), ("2026-02-20", 1_550), ("2026-03-20", 1_830)):
        fuel.create(conn, car, fuel.FillInput(day, odo, "gas", 10.0, cost_cents=3_000))
    page = signed_in.get("/reports?view=fuel").text
    assert 'class="tag tag--best">Best' in page and 'class="tag tag--worst">Worst' in page
    assert "Price paid" in page and "$/gal each month" in page


# ---------- The Overview ----------


def _driven(conn):
    from amg.repo import odometer
    ids = rf.garage(conn)
    for car, readings in ((ids["outback"], (("2019-01-01", 40_000), ("2024-12-31", 100_000))),
                          (ids["civic"], (("2021-01-01", 10_000), ("2024-12-31", 50_000)))):
        for day, miles in readings:
            odometer.add(conn, car, day, miles)
    car = ids["outback"]
    for day, odo in (("2024-09-01", 97_000), ("2024-09-15", 97_300), ("2024-10-01", 97_600)):
        fuel.create(conn, car, fuel.FillInput(day, odo, "gas", 10.0, cost_cents=3_500))
    return ids


def test_reports_open_on_the_overview(signed_in, conn):
    ids = _driven(conn)
    page = signed_in.get("/reports").text
    assert 'href="/reports" aria-current="page">Overview</a>' in page
    assert "Car by car" in page and "Year by year" in page and "Month by month" in page
    assert f'href="/vehicles/{ids["outback"]}#running-cost">Outback</a>' in page
    assert 'class="tag tag--gap">Gap</span>' in page and "mostly estimated" in page
    assert "Show all" in page                                                 # years of months: the rest folded
    assert 'name="service"' not in page and 'name="shop"' not in page        # neither applies
    assert 'href="/reports/overview.csv"' in page


def test_the_overview_for_one_car_and_some_dates(signed_in, conn):
    ids = _driven(conn)
    page = signed_in.get(f"/reports?view=overview&car={ids['civic']}&from=2024-01-01&to=2024-12-31").text
    assert "Civic" in page and 'href="/vehicles/' + str(ids["outback"]) + '#running-cost"' not in page
    assert "Next 12 months" not in page                                       # an end date: no future
    assert "What it costs to run · Civic · Jan 2024 – Dec 2024 · printed" in html.unescape(page)


def test_the_overview_csv(signed_in, conn):
    _driven(conn)
    response = signed_in.get("/reports/overview.csv")
    assert response.status_code == 200 and "amg-overview-all-cars-" in response.headers["content-disposition"]
    assert response.text.lstrip("﻿").startswith("Car,Year,From,To,Miles,Fuel,")
