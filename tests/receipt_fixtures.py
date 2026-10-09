"""Builders shared by the receipt tests. tests/ is on pytest's path, so: import receipt_fixtures as fx."""

from __future__ import annotations

from amg.ingest.claude import Usage
from amg.ingest.receipts import ReceiptExtraction, ReceiptLine, ReceiptWarranty, Recommendation

USAGE = Usage("claude-opus-5-5", 8_000, 1_000, 0, 0, 12.0, "req_test")


def line(description="Synthetic oil and filter change", amount=67.15, codes=("engine_oil", "oil_filter"),
         action="replace", kind="labor"):
    return ReceiptLine(description=description, kind=kind, part_number=None, quantity=None,
                       amount=amount, service_codes=list(codes), action=action)


def warranty(description="36-month free replacement", months=36, miles=None, codes=("battery_12v",),
             provider=None, lifetime=False):
    return ReceiptWarranty(description=description, provider=provider, months=months, miles=miles,
                           lifetime=lifetime, service_codes=list(codes))


def extraction(**overrides) -> ReceiptExtraction:
    fields = dict(
        document_kind="invoice", shop_name="Corner Garage", invoice_number="A100", date="2016-08-15",
        odometer=3_610, vin=None, plate=None, vehicle="2016 Subaru Outback", delivery_date=None,
        next_service_date=None, next_service_miles=None,
        lines=[line(), line("Shop supplies", 7.88, (), "perform", "fee")],
        recommendations=[Recommendation(description="Brake fluid flush", service_codes=["brake_fluid"],
                                        quoted_amount=129.95)],
        warranties=[], subtotal=75.03, tax=2.76, total=77.79, uncertain="",
    )
    fields.update(overrides)
    return ReceiptExtraction(**fields)
