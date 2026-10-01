"""Phase 1 trial: read real receipts with Claude and see whether the result is usable.

    python scripts/try_receipt.py samples/20160815.pdf
    python scripts/try_receipt.py samples --mode text vision      # every receipt, both ways
    python scripts/try_receipt.py samples --mode vision --effort low

Prints what was read from each receipt, what a reviewer should check, and what
each read cost. Saves the full JSON beside the samples (samples/_trial/), which
git ignores — receipts carry personal details. Files whose name mentions
"manual" or "maintenance" are skipped: they are schedules, not receipts.

This spends real money: roughly 2–8¢ per receipt per mode on Opus 5.5.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amg import db  # noqa: E402
from amg.ingest import claude, pdf, receipts  # noqa: E402
from amg.repo import services  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="receipt files, or folders of them")
    parser.add_argument("--mode", nargs="+", choices=receipts.MODES, default=["vision"])
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--out", type=Path, default=ROOT / "samples" / "_trial")
    args = parser.parse_args(argv)

    if not claude.configured():
        print("ANTHROPIC_API_KEY isn't set (it's read from .env).", file=sys.stderr)
        return 1

    files = _files(args.paths)
    if not files:
        print("No receipts found.", file=sys.stderr)
        return 1

    conn = db.connect(":memory:")
    db.migrate(conn)
    types = [dict(row) for row in services.list_types(conn)]
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Model {claude.model()}, effort {args.effort}, {len(files)} file(s), mode(s) {', '.join(args.mode)}\n")
    totals: dict[str, list] = {mode: [] for mode in args.mode}
    for path in files:
        for mode in args.mode:
            try:
                read = receipts.read_receipt(path, types, mode=mode, effort=args.effort)
            except (claude.ClaudeError, ValueError) as err:
                print(f"== {path.name} [{mode}] FAILED: {err}\n")
                continue
            _print(read)
            _save(read, args.out)
            totals[mode].append(read)

    print("== Summary")
    for mode, reads in totals.items():
        if not reads:
            continue
        cost = sum(r.usage.cost_usd or 0 for r in reads)
        seconds = sum(r.usage.seconds for r in reads)
        flagged = sum(1 for r in reads if r.warnings)
        print(f"   {mode:6} {len(reads)} read, ${cost:.2f} total (${cost / len(reads):.3f} each), "
              f"{seconds / len(reads):.0f}s each, {flagged} with something to check")
    return 0


def _files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
        for candidate in candidates:
            name = candidate.name.lower()
            if candidate.is_file() and pdf.is_supported(candidate) and "manual" not in name and "maintenance" not in name:
                found.append(candidate)
    return found


def _print(read: receipts.ReceiptRead) -> None:
    e = read.extraction
    u = read.usage
    sources = ", ".join(
        f"p{p.number} {p.source}" + (f" ({p.ocr_confidence:.0f}%)" if p.ocr_confidence is not None else "")
        for p in read.pages
    )
    cost = f"${u.cost_usd:.3f}" if u.cost_usd is not None else "?"
    print(f"== {read.path.name} [{read.mode}]  {len(read.pages)} page(s): {sources}")
    print(f"   {u.input_tokens + u.cache_read_tokens + u.cache_write_tokens:,} in / {u.output_tokens:,} out, {cost}, {u.seconds}s")
    print(f"   {e.date or '?'}  {e.odometer if e.odometer is not None else '?':>7} mi  {e.shop_name or '?'}"
          f"  #{e.invoice_number or '-'}  {e.vehicle or ''}  VIN {e.vin or '-'}")
    for line in e.lines:
        amount = f"{line.amount:>9,.2f}" if line.amount is not None else " " * 9
        codes = ",".join(line.service_codes) or "-"
        print(f"     {amount}  {line.kind:5} {line.action:7} {line.description[:60]:60}  [{codes}]")
    for rec in e.recommendations:
        quoted = f"{rec.quoted_amount:,.2f}" if rec.quoted_amount is not None else ""
        print(f"     recommended: {rec.description[:60]} {quoted} [{','.join(rec.service_codes) or '-'}]")
    print(f"     subtotal {e.subtotal}  tax {e.tax}  total {e.total}")
    for warning in read.warnings:
        print(f"   ! {warning}")
    print()


def _save(read: receipts.ReceiptRead, out: Path) -> None:
    record = {
        "file": read.path.name,
        "mode": read.mode,
        "pages": [{"number": p.number, "source": p.source, "ocr_confidence": p.ocr_confidence} for p in read.pages],
        "usage": {**read.usage.__dict__, "cost_usd": read.usage.cost_usd},
        "warnings": read.warnings,
        "extraction": read.extraction.model_dump(),
    }
    (out / f"{read.path.stem}.{read.mode}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
