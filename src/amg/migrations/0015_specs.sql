-- A car's specs card: what to buy for it at the parts counter.
--
-- One row per spec that has a value. key is a field of the catalogue in
-- engine/specs.py ("oil_grade", "tire_size" …), or 'custom' for a line you
-- named yourself (label), kept in your order (position).
--   source: you  — typed, or changed after it was read
--           read — read by Claude from a file (document_id, page) and left as read
CREATE TABLE vehicle_specs (
    id           INTEGER PRIMARY KEY,
    vehicle_id   INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    key          TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    value        TEXT NOT NULL CHECK (value <> ''),
    source       TEXT NOT NULL DEFAULT 'you' CHECK (source IN ('you', 'read')),
    document_id  INTEGER REFERENCES documents (id) ON DELETE SET NULL,
    page         INTEGER,
    position     INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    CHECK (key <> 'custom' OR label <> '')
);
CREATE UNIQUE INDEX vehicle_specs_key ON vehicle_specs (vehicle_id, key) WHERE key <> 'custom';
CREATE INDEX vehicle_specs_vehicle ON vehicle_specs (vehicle_id, position);
