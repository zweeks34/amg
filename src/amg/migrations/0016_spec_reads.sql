-- Claude's readings of a car's specs from its owner's manual or photos.
--
-- A reading runs queued → reading → read → used, with failed and discarded to
-- the side, as a schedule draft does. values_json is what goes in the boxes
-- to check: {key: {"value", "page"}}, from extraction_json, which is never
-- edited. Using a reading writes vehicle_specs; it isn't kept as a draft.
CREATE TABLE spec_reads (
    id               INTEGER PRIMARY KEY,
    vehicle_id       INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    document_id      INTEGER REFERENCES documents (id) ON DELETE SET NULL,
    requested_pages  TEXT NOT NULL DEFAULT '',     -- as typed: "410-414"; empty means let AMG find them
    pages_json       TEXT NOT NULL DEFAULT '[]',   -- the pages Claude was shown
    job_id           INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'reading', 'read', 'failed', 'used', 'discarded')),
    extraction_json  TEXT,
    values_json      TEXT,
    warnings_json    TEXT NOT NULL DEFAULT '[]',
    error            TEXT NOT NULL DEFAULT '',
    model            TEXT,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    cost_usd         REAL,
    read_seconds     REAL,
    request_id       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    read_at          TEXT,
    used_at          TEXT
);
CREATE INDEX spec_reads_vehicle ON spec_reads (vehicle_id, status);
CREATE INDEX spec_reads_job ON spec_reads (job_id, status);
