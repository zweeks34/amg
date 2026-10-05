"""The Reports page: its three views, the filters in the address bar, the CSVs, and the ways in."""

from __future__ import annotations

from datetime import date

import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import fuel


def test_nothing_to_report_says_how_to_start(signed_in):
    page = signed_in.get("/reports").text
    assert "Nothing to report yet. Confirm receipts or log services" in page and "Show the report" not in page
    assert 'href="/reports" aria-current="page"' in page                     # the footer link
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
    page = signed_in.get("/reports").text
    assert page.count('class="visit"') == 5 and "Your own work" in page and "Done, no receipt" in page
    assert "Clear filters" not in page and "$640.00" in page                    # what the five came to


def test_nothing_matching_offers_to_clear(signed_in, conn):
    rf.garage(conn)
    page = signed_in.get("/reports?shop=nowhere").text
    assert "No services match." in page and '<a href="/reports">Clear filters</a>' in page


def test_spending_by_year(signed_in, conn):
    ids = rf.garage(conn)
    page = signed_in.get(f"/reports?view=spending&car={ids['civic']}").text
    assert '<th scope="col" class="num">2021</th>' in page and "Brakes" in page and "$300.00" in page
    assert "Other is lines with no service type" in page
    assert 'href="/reports?car=' in page and 'aria-current="page">Spending</a>' in page   # the view switch


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
    assert f'href="/reports?car={ids["outback"]}">Report</a>' in signed_in.get(f"/vehicles/{ids['outback']}").text
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
