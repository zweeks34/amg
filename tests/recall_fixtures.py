"""A stand-in for NHTSA's recall service. tests/ is on pytest's path, so: import recall_fixtures as nf.

Shaped like its answers for a 2016 Subaru: the models with recalls, then two
recalls for the Outback, one that says not to drive it. The wording is made up.
"""

from __future__ import annotations

from amg.ingest import recalls

MODELS = {"count": 3, "message": "Results returned successfully", "results": [
    {"modelYear": "2016", "make": "SUBARU", "model": "LEGACY"},
    {"modelYear": "2016", "make": "SUBARU", "model": "OUTBACK"},
    {"modelYear": "2016", "make": "SUBARU", "model": "OUTBACK"},       # NHTSA lists some twice
]}

AIR_BAG = {
    "Manufacturer": "Subaru of America, Inc.", "NHTSACampaignNumber": "19V910000", "parkIt": False,
    "parkOutSide": False, "overTheAirUpdate": False, "ReportReceivedDate": "19/12/2019",
    "Component": "AIR BAGS: AIR BAG/RESTRAINT CONTROL MODULE",
    "Summary": "A replacement air bag control module may not match the passenger air bag.",
    "Consequence": "The passenger air bag may not deploy as it should in a crash.",
    "Remedy": "Dealers will replace the module free of charge.",
    "Notes": "", "ModelYear": "2016", "Make": "SUBARU", "Model": "OUTBACK",
}
STEERING = {
    **AIR_BAG, "NHTSACampaignNumber": "16V292000", "parkIt": True, "ReportReceivedDate": "11/05/2016",
    "Component": "STEERING:COLUMN", "Summary": "The steering column may have been machined wrongly.",
    "Consequence": "The car may not steer.", "Remedy": "Dealers will inspect the column and replace it if needed.",
}
RECALLS = {"Count": 2, "Message": "Results returned successfully", "results": [AIR_BAG, STEERING]}


def nhtsa(monkeypatch, models=MODELS, found=RECALLS) -> list[str]:
    """NHTSA answers with ``models`` and ``found``; returns the addresses asked, to check what was sent."""
    asked: list[str] = []

    def answer(url):
        asked.append(url)
        return models if "/products/" in url else found

    monkeypatch.setattr(recalls, "_get", answer)
    return asked


def down(monkeypatch) -> None:
    def fail(url):
        raise recalls.RecallLookupError(recalls.UNREACHABLE)

    monkeypatch.setattr(recalls, "_get", fail)
