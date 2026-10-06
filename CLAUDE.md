# Project: Automobile Maintenance Genie (AMG) 

## Description
The Automobile Maintenance Genie (AMG) is an automobile maintenance manager.

## Specs
- Full spec and wish-list: `docs/SPEC.md` — read before planning any new feature
- Build plan, phase checklists and decisions: `docs/ROADMAP.md` — tick items off as they ship
- Every approved plan, as approved: `docs/plans/` (index in its README) — a record of what was agreed and how it was built

## Stack
- Python ≥3.12 (server LXC runs Ubuntu 24.04's 3.12; local is 3.14 — don't use 3.13+-only features)
- FastAPI + Jinja2 templates + htmx + Alpine.js (vendored in `static/vendor/`, no JS build step)
- SQLite via stdlib `sqlite3` (WAL), numbered SQL migrations in `src/amg/migrations/`
- PyMuPDF + Tesseract (pytesseract) for local text/OCR; Anthropic SDK for structuring (`AMG_CLAUDE_MODEL`)
- pip + venv (`.venv/`); dependencies live in `pyproject.toml` only

## Commands
- Install: `python -m venv .venv` then `.venv\Scripts\python -m pip install -e ".[dev]"`
- Run dev: `.venv\Scripts\python -m uvicorn amg.app:app --reload` → http://127.0.0.1:8000
- Set the login password: `.venv\Scripts\python -m amg.cli set-password`
- Test: `.venv\Scripts\python -m pytest` (run before declaring any task done)
- Back up / restore: `python -m amg.cli backup` (→ `data/backups/`), `python -m amg.cli restore FILE.zip --replace`
- Deploy (from WSL, in `/mnt/c/projects/amg`): `bash scripts/deploy.sh` — first-time setup and day-to-day ops are in `docs/DEPLOY-proxmox.md`

## Layout
- `src/` app code; `tests/` mirrors `src/`
- `src/amg/repo/` — all SQL lives here; routes never write SQL
- `src/amg/engine/` — pure functions (odometer model, gaps, forecast): no DB, no I/O
- `src/amg/web/` — routes, `templates/`, `static/`
- `data/` — runtime data (database, stored files, backups); gitignored. On the server it's `/var/lib/amg` (`AMG_DATA_DIR`), outside the code
- `deploy/` — the systemd unit and the server's `amg` command; `scripts/deploy.sh` installs both on every deploy
- `samples/` — real receipt/manual scans for extraction trials; gitignored (personal information)

## Conventions
- Prefer stdlib/native over new dependencies; ask before adding one
- Money is integer cents; distance is integer miles; energy is kWh / US gallons as REAL; dates are ISO-8601 text
- Settings and paths are resolved inside functions (never bound as default arguments) so tests can redirect them
- Nothing an AI extracted counts in history or schedules until the user confirms it — and every field stays correctable, before and after confirming, with the source scan alongside. Printed details (VIN, vehicle) are evidence, not truth: shops get them wrong
- UI copy: sentence case, plain verbs, buttons say what happens ("Confirm receipt", not "Submit")

## Workflow
- Propose a plan and wait for approval before multi-file changes
- Once a plan is approved, save it verbatim to `docs/plans/YYYY-MM-DD-short-name.md` with the header the others have, add it to the index, and commit it with the work; when it ships, add its commits and an **As built** note for anything that changed
- Small commits, conventional-commit messages

## Gotchas
- Tesseract on this Windows machine is at `C:\Program Files\Tesseract-OCR\tesseract.exe` and is NOT on PATH — `amg.ingest.ocr` must fall back to that path
- `.env` holds real API keys — never commit it, print it, or copy values into code. `.env.example` lists every setting; add new ones there
- On the server, CLI tasks run as `amg <command>` (as the `amg` user). Run as root against `/var/lib/amg`, they leave files the app can't write, so the CLI refuses
- `deploy/*` and `*.sh` must stay LF (`.gitattributes`): they run on Linux as-is
