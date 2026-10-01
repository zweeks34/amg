-- Scanned receipts: the files, reading them in the background, and the review
-- that turns a reading into a service event.

-- Handwritten receipts often carry a plate and no VIN.
ALTER TABLE vehicles ADD COLUMN plate TEXT NOT NULL DEFAULT '';

-- Uploaded files, stored once by content. Re-uploading the same file finds
-- this row instead of making a second one.
CREATE TABLE documents (
    id           INTEGER PRIMARY KEY,
    sha256       TEXT NOT NULL UNIQUE,      -- of the bytes as uploaded
    filename     TEXT NOT NULL,             -- as uploaded; shown, never used as a path
    media_type   TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    page_count   INTEGER NOT NULL,
    stored_as    TEXT NOT NULL,             -- path under the data directory
    uploaded_at  TEXT NOT NULL
);

-- A batch of reading done by a background thread. A job whose heartbeat has
-- gone quiet lost its thread (a restart, a deploy) and is shown as stalled.
CREATE TABLE jobs (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('running', 'done')),
    started_at    TEXT NOT NULL,
    heartbeat_at  TEXT NOT NULL,
    finished_at   TEXT
);

-- One receipt per document.
--   extraction_json — what Claude read. Never edited: it's the baseline every
--                     correction is measured against.
--   draft_json      — your copy. Starts as the reading, is edited on review,
--                     and stays the editable record after confirming; the
--                     service event is written from it.
CREATE TABLE receipts (
    id                INTEGER PRIMARY KEY,
    document_id       INTEGER NOT NULL UNIQUE REFERENCES documents (id) ON DELETE CASCADE,
    job_id            INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
    status            TEXT NOT NULL CHECK (status IN ('queued', 'reading', 'read', 'failed', 'confirmed', 'discarded')),
    vehicle_id        INTEGER REFERENCES vehicles (id) ON DELETE SET NULL,
    vehicle_reason    TEXT NOT NULL DEFAULT '',   -- why this car was suggested
    extraction_json   TEXT,
    draft_json        TEXT,
    warnings_json     TEXT NOT NULL DEFAULT '[]',
    error             TEXT NOT NULL DEFAULT '',
    model             TEXT,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          REAL,
    read_seconds      REAL,
    request_id        TEXT,
    service_event_id  INTEGER UNIQUE REFERENCES service_events (id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    read_at           TEXT,
    confirmed_at      TEXT
);
CREATE INDEX receipts_status ON receipts (status, id);
CREATE INDEX receipts_job ON receipts (job_id, status);

-- What you tagged a line's text with, so the next receipt that prints the
-- same words gets the same service types without second-guessing.
CREATE TABLE service_aliases (
    phrase       TEXT PRIMARY KEY,          -- normalised line description
    covers_json  TEXT NOT NULL,             -- [{"code": ..., "action": ...}, ...]
    updated_at   TEXT NOT NULL
);
