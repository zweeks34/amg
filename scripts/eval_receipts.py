"""How well AMG reads receipts, scored against the ones you confirmed.

    python scripts/eval_receipts.py                    # free: the original readings vs your corrections
    python scripts/eval_receipts.py --reread --yes     # re-read every confirmed receipt now and score that
    python scripts/eval_receipts.py --reread --yes --limit 5

Each confirmed receipt's draft is what you checked; its reading is what Claude
said at the time. The free mode shows where you've had to correct things. The
re-read mode runs the *current* model and prompt (AMG_CLAUDE_MODEL) over the
same files — run it before and after changing either, to see if it helped.
Re-reading costs about 6¢ a receipt on Opus 5.5, so it asks for --yes.

Point --data at another data directory (e.g. a copy of the server's) to score that.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reread", action="store_true", help="read the files again with the current model")
    parser.add_argument("--yes", action="store_true", help="agree to the cost of re-reading")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--data", type=Path, default=None, help="data directory (default: AMG_DATA_DIR or data/)")
    args = parser.parse_args(argv)
    if args.data:
        os.environ["AMG_DATA_DIR"] = str(args.data)

    from amg import db
    from amg.ingest import claude, drafts, evaluate
    from amg.ingest import receipts as reader
    from amg.ingest.receipts import ReceiptExtraction
    from amg.repo import documents, receipts, services

    conn = db.connect()
    db.migrate(conn)
    types = {row["code"]: dict(row) for row in services.list_types(conn)}
    ids = [row[0] for row in conn.execute("SELECT id FROM receipts WHERE status = 'confirmed' ORDER BY id")]
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        print("No confirmed receipts yet. Confirm some on the receipts page, then run this again.")
        return 0

    if args.reread:
        if not claude.configured():
            print("ANTHROPIC_API_KEY isn't set (it's read from .env).", file=sys.stderr)
            return 1
        if not args.yes:
            print(f"Re-reading {len(ids)} receipt(s) with {claude.model()} costs roughly ${0.06 * len(ids):.2f}. "
                  "Run again with --yes to go ahead.")
            return 1

    results: list[tuple[str, dict[str, bool]]] = []
    spent = 0.0
    for receipt_id in ids:
        receipt = receipts.get(conn, receipt_id)
        truth = receipt["draft"]
        name = receipt["document"]["filename"]
        if args.reread:
            try:
                read = reader.read_receipt(documents.path(documents.get(conn, receipt["document_id"])), list(types.values()))
            except (claude.ClaudeError, ValueError) as err:
                print(f"  {name}: couldn't read ({err})")
                continue
            spent += read.usage.cost_usd or 0
            reading = drafts.from_extraction(read.extraction, types)
        else:
            reading = drafts.from_extraction(ReceiptExtraction.model_validate(receipt["extraction"]), types)
        result = evaluate.compare(reading, truth)
        results.append((name, result))
        wrong = [field for field, right in result.items() if not right]
        print(f"  {name:40.40}  {'all right' if not wrong else 'wrong: ' + ', '.join(wrong)}")

    scores = evaluate.summarize([result for _, result in results])
    label = f"re-read with {claude.model()}" if args.reread else "as originally read"
    print(f"\n{len(results)} confirmed receipt(s), {label}:\n")
    for field, score in sorted(scores.items(), key=lambda item: item[1].percent):
        bar = "█" * round(score.percent / 5)
        print(f"  {field:16} {score.right:3}/{score.total:<3} {score.percent:5.1f}%  {bar}")
    if args.reread:
        print(f"\nSpent about ${spent:.2f}.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
