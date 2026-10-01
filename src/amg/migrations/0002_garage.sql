-- Cars, odometer readings, and the services done to them.
--
-- Distances are integer miles, money is integer cents, dates are ISO-8601 text.

CREATE TABLE vehicles (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,             -- what you call it: "Outback"
    vin              TEXT UNIQUE,               -- 17 characters; NULL when unknown
    year             INTEGER,
    make             TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    trim             TEXT NOT NULL DEFAULT '',
    engine           TEXT NOT NULL DEFAULT '',  -- "2.5L 4-cyl" — from the VIN decode or typed
    powertrain       TEXT NOT NULL DEFAULT 'gas' CHECK (powertrain IN ('gas', 'hybrid', 'ev')),
    in_service_date  TEXT,                      -- first delivered new; schedules count from here
    acquired_date    TEXT,                      -- when you got it; no gaps are judged before this
    acquired_miles   INTEGER CHECK (acquired_miles IS NULL OR acquired_miles >= 0),
    notes            TEXT NOT NULL DEFAULT '',
    archived_at      TEXT,                      -- sold or scrapped: hidden, never deleted
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- Odometer readings typed in directly. Readings that come with a service or a
-- fill-up live on those rows; odometer_points (below) puts them all together.
CREATE TABLE odometer_readings (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    read_on     TEXT NOT NULL,
    miles       INTEGER NOT NULL CHECK (miles >= 0),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX odometer_readings_vehicle ON odometer_readings (vehicle_id, read_on);

CREATE TABLE service_types (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,       -- stable key: "engine_oil"
    name            TEXT NOT NULL,              -- "Engine oil"
    category        TEXT NOT NULL,              -- groups rows on the chart and in pickers
    powertrains     TEXT NOT NULL DEFAULT 'gas,hybrid,ev',
    default_action  TEXT NOT NULL DEFAULT 'replace' CHECK (default_action IN ('replace', 'inspect', 'perform')),
    sort            INTEGER NOT NULL DEFAULT 0,
    is_custom       INTEGER NOT NULL DEFAULT 0
);

-- One visit: a shop invoice, or a job you did yourself.
--   source: diy      — you did the work
--           shop     — a shop did it; typed in by hand
--           receipt  — read from a scanned receipt (phase 2)
--           attested — "it was done, there's no receipt" (phase 5)
-- A receipt lands unconfirmed and counts for nothing until you confirm it.
CREATE TABLE service_events (
    id              INTEGER PRIMARY KEY,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE RESTRICT,
    performed_on    TEXT NOT NULL,
    odometer        INTEGER CHECK (odometer IS NULL OR odometer >= 0),
    source          TEXT NOT NULL CHECK (source IN ('diy', 'shop', 'receipt', 'attested')),
    shop            TEXT NOT NULL DEFAULT '',
    invoice_number  TEXT NOT NULL DEFAULT '',
    tax_cents       INTEGER,
    total_cents     INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    confirmed       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX service_events_vehicle ON service_events (vehicle_id, performed_on);

CREATE TABLE line_items (
    id                INTEGER PRIMARY KEY,
    service_event_id  INTEGER NOT NULL REFERENCES service_events (id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    description       TEXT NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('labor', 'part', 'fee', 'other')),
    part_number       TEXT NOT NULL DEFAULT '',
    quantity          REAL,
    amount_cents      INTEGER                  -- the line's extended amount
);
CREATE INDEX line_items_event ON line_items (service_event_id, position);

-- What a line item did, in schedule terms. One line can cover several service
-- types ("oil and filter change" → engine_oil + oil_filter), and how it covered
-- them matters: a schedule item that says *replace* is not met by an inspection.
CREATE TABLE line_item_services (
    line_item_id     INTEGER NOT NULL REFERENCES line_items (id) ON DELETE CASCADE,
    service_type_id  INTEGER NOT NULL REFERENCES service_types (id) ON DELETE RESTRICT,
    action           TEXT NOT NULL CHECK (action IN ('replace', 'inspect', 'perform')),
    PRIMARY KEY (line_item_id, service_type_id)
);
CREATE INDEX line_item_services_type ON line_item_services (service_type_id);

-- Every known odometer value for a car, wherever it was recorded. The odometer
-- model reads this; nothing else needs to know where a reading came from.
CREATE VIEW odometer_points AS
    SELECT vehicle_id, read_on, miles, 'manual' AS source, id AS source_id
      FROM odometer_readings
    UNION ALL
    SELECT vehicle_id, performed_on, odometer, 'service', id
      FROM service_events
     WHERE odometer IS NOT NULL AND confirmed = 1
    UNION ALL
    SELECT id, acquired_date, acquired_miles, 'acquired', id
      FROM vehicles
     WHERE acquired_date IS NOT NULL AND acquired_miles IS NOT NULL;
