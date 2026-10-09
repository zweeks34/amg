-- The look through receipts read before AMG kept warranties: a row per
-- confirmed receipt asked about, once.
--   status: queued → looking → done; or failed, with the error, to be tried
--           again.
--   found:  how many warranties it added to the receipt's draft. They wait
--           there, marked, until you check them and save the receipt.
CREATE TABLE warranty_looks (
    receipt_id     INTEGER PRIMARY KEY REFERENCES receipts (id) ON DELETE CASCADE,
    job_id         INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
    status         TEXT NOT NULL CHECK (status IN ('queued', 'looking', 'done', 'failed')),
    found          INTEGER NOT NULL DEFAULT 0,
    error          TEXT NOT NULL DEFAULT '',
    model          TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost_usd       REAL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    looked_at      TEXT
);
CREATE INDEX warranty_looks_job ON warranty_looks (job_id, status);
