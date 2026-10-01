from __future__ import annotations

from amg.ingest import evaluate
from amg.ingest.drafts import Draft


def _draft(**fields) -> Draft:
    base = dict(
        document_kind="invoice", shop="Corner Garage", invoice_number="A-100", performed_on="2016-08-15",
        odometer=3610, tax_cents=276, total_cents=7779, printed_vin="",
        lines=[{"description": "Oil", "kind": "labor", "amount_cents": 6715,
                "covers": [{"code": "engine_oil", "action": "replace"}]},
               {"description": "Fee", "kind": "fee", "amount_cents": 788, "covers": []}],
        recommendations=[],
    )
    base.update(fields)
    return Draft(**base)


def test_identical_drafts_match_everywhere():
    assert all(evaluate.compare(_draft(), _draft()).values())


def test_cosmetic_differences_dont_count():
    result = evaluate.compare(_draft(shop="CORNER GARAGE.", invoice_number="a100"), _draft())
    assert result["shop"] and result["invoice"]


def test_each_field_is_judged_separately():
    truth = _draft()
    read = _draft(odometer=3612, lines=list(reversed(truth.lines)),
                  recommendations=[{"description": "x", "codes": [], "quoted_cents": None}])
    result = evaluate.compare(read, truth)
    assert not result["odometer"] and not result["recommendations"]
    assert result["line amounts"] and result["services"]        # order of lines doesn't matter


def test_summary():
    scores = evaluate.summarize([{"date": True, "total": False}, {"date": True, "total": True}])
    assert (scores["date"].right, scores["date"].total) == (2, 2)
    assert scores["total"].percent == 50.0
