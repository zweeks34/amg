-- What a job costs, for the budget, when your receipts don't say: a price you
-- set, or Claude's estimate.
--
-- A job is what a schedule item asks for — its service types and its action —
-- so a price is kept per car and per job, not per schedule item: it survives
-- using a new schedule, and a severe-service oil change shares the normal
-- one's price.
--
--   codes:   the job's service type codes, sorted, comma-separated
--   source:  you    — typed by you; beats every other price
--            claude — Claude's estimate, a range; flagged wherever it's shown
--   status:  Claude's asking, as with receipts: queued → asking → done or
--            failed. A price you set is always done.
CREATE TABLE price_book (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    codes       TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('replace', 'inspect', 'perform')),
    name        TEXT NOT NULL,              -- the schedule item's name when it was priced
    source      TEXT NOT NULL CHECK (source IN ('you', 'claude')),
    low_cents   INTEGER CHECK (low_cents IS NULL OR low_cents >= 0),
    high_cents  INTEGER CHECK (high_cents IS NULL OR high_cents >= low_cents),
    note        TEXT NOT NULL DEFAULT '',   -- Claude's line on what the range covers
    status      TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('queued', 'asking', 'done', 'failed')),
    job_id      INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
    error       TEXT NOT NULL DEFAULT '',
    model       TEXT,
    cost_usd    REAL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (vehicle_id, codes, action, source)
);
CREATE INDEX price_book_job ON price_book (job_id, status);
