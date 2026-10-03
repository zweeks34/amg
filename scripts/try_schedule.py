"""Phase 4 trial: read a maintenance schedule with Claude and see whether the result is usable.

    python scripts/try_schedule.py samples/2016-Subaru-Outback-Maintenance-Plan.pdf --car "2016 Subaru Outback"
    python scripts/try_schedule.py manual.pdf --pages 412-418 --car "2021 Toyota RAV4" --powertrain hybrid
    python scripts/try_schedule.py --draft --car "2016 Subaru Outback" --engine "2.5L 4-cyl"

Prints the pages read, the schedule as AMG would draft it (intervals worked out
from any table of marks), what a reviewer should check, and what the read
cost. Saves the full JSON to samples/_trial/, which git ignores.

This spends real money: roughly 15–50¢ per read on Opus 5.5 at high effort.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amg import db  # noqa: E402
from amg.ingest import claude, manuals  # noqa: E402
from amg.ingest import schedule_drafts as sd  # noqa: E402
from amg.repo import services  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", type=Path, help="the manual or schedule pages")
    parser.add_argument("--draft", action="store_true", help="no file: ask Claude to draft the schedule")
    parser.add_argument("--pages", default="", help="page numbers to read, e.g. 30-31; default: let AMG find them")
    parser.add_argument("--car", required=True, help='year, make and model, e.g. "2016 Subaru Outback"')
    parser.add_argument("--trim", default="")
    parser.add_argument("--engine", default="")
    parser.add_argument("--powertrain", default="gas", choices=["gas", "hybrid", "ev"])
    parser.add_argument("--out", type=Path, default=ROOT / "samples" / "_trial")
    args = parser.parse_args(argv)

    if bool(args.path) == args.draft:
        parser.error("give a file, or --draft, not both")
    if not claude.configured():
        print("ANTHROPIC_API_KEY isn't set (it's read from .env).", file=sys.stderr)
        return 1

    year, _, rest = args.car.partition(" ")
    if not year.isdigit():
        year, rest = "", args.car
    make, _, model = rest.partition(" ")
    car = {"year": int(year) if year else None, "make": make, "model": model, "trim": args.trim,
           "engine": args.engine, "powertrain": args.powertrain}

    conn = db.connect(":memory:")
    db.migrate(conn)
    types = {row["code"]: dict(row) for row in services.list_types(conn)}

    print(f"Model {claude.model()}, effort {manuals.EFFORT}, car: {manuals.describe_car(car)}\n")
    try:
        if args.draft:
            read = manuals.draft_schedule(car, list(types.values()))
        else:
            print(f"Pages to read: {manuals.find_pages(args.path, args.pages)}")
            read = manuals.read_manual(args.path, car, list(types.values()), pages=args.pages)
    except (claude.ClaudeError, manuals.ManualError) as err:
        print(f"FAILED: {err}", file=sys.stderr)
        return 1

    origin = "claude" if args.draft else "manual"
    draft, warnings = sd.from_extraction(read.extraction, types, origin, document_id=None, pages=read.pages or None)
    _print(read, draft, warnings)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = "draft-" + "-".join(args.car.lower().split()) if args.draft else args.path.stem
    record = {
        "file": None if args.draft else args.path.name,
        "car": car,
        "pages": read.pages,
        "usage": {**read.usage.__dict__, "cost_usd": read.usage.cost_usd},
        "warnings": warnings,
        "extraction": read.extraction.model_dump(),
        "draft": draft.to_dict(),
    }
    target = args.out / f"{stem}.schedule.json"
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nSaved {target.relative_to(ROOT)}")
    return 0


def _print(read: manuals.ScheduleRead, draft: sd.ScheduleDraft, warnings: list[str]) -> None:
    u = read.usage
    e = read.extraction
    cost = f"${u.cost_usd:.3f}" if u.cost_usd is not None else "?"
    print(f"Pages read: {read.pages or 'none (drafted)'}")
    print(f"{u.input_tokens + u.cache_read_tokens + u.cache_write_tokens:,} in / {u.output_tokens:,} out, {cost}, {u.seconds}s")
    print(f"Printed for: {e.printed_for or '-'}")
    if e.table_columns:
        print("Table columns: " + ", ".join(f"{c.miles or '?'} mi/{c.months or '?'} mo" for c in e.table_columns))
    print()
    for label, wanted in (("Normal and severe", "always"), ("Normal only", "normal"), ("Severe only", "severe")):
        rows = [item for item in draft.items if item["applies"] == wanted and item["included"]]
        if rows:
            print(f"== {label}")
            for item in rows:
                _item(item)
    left_out = [item for item in draft.items if not item["included"]]
    if left_out:
        print("== Left out")
        for item in left_out:
            _item(item)
    if draft.severe_conditions:
        print("\nSevere conditions:\n  " + draft.severe_conditions.replace("\n", "\n  "))
    for warning in warnings:
        print(f"! {warning}")


def _item(item: dict) -> None:
    marks = f"  marks {','.join(str(m // 1000) for m in item['marked_miles'])}k" if item["marked_miles"] else ""
    page = f" p{item['page']}" if item["page"] else ""
    print(f"  {item['action']:7} {item['name'][:52]:52} {sd.interval_words(item)}{marks}{page}")
    print(f"          [{','.join(item['codes']) or '-'}]"
          + (f"  note: {item['note']}" if item["note"] else "")
          + (f"  left out: {item['why_not']}" if item["why_not"] else ""))


if __name__ == "__main__":
    sys.exit(main())
