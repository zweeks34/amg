-- Maintenance schedules: what each car should have done, and how often.
--
-- A schedule starts as a draft — read from the owner's manual, drafted by
-- Claude, taken from a generic template or copied from another car — and
-- counts for nothing until you use it. Using it writes the car's own
-- schedule_items, so editing one car's schedule never touches another's.

-- Severe service (short trips, towing, dust, road salt …): the manual's
-- severe-only intervals apply instead of the normal ones.
ALTER TABLE vehicles ADD COLUMN severe_service INTEGER NOT NULL DEFAULT 0;

-- A proposed schedule for one car.
--   origin: manual   — read by Claude from manual pages (document_id)
--           claude   — drafted by Claude from the car's year, make and model
--           template — a generic schedule for the car's powertrain
--           copy     — another car's schedule
--   extraction_json — what Claude read; never edited. NULL for templates and copies.
--   draft_json      — your copy, edited on review; using it writes schedule_items.
CREATE TABLE schedule_drafts (
    id               INTEGER PRIMARY KEY,
    vehicle_id       INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    origin           TEXT NOT NULL CHECK (origin IN ('manual', 'claude', 'template', 'copy')),
    document_id      INTEGER REFERENCES documents (id) ON DELETE SET NULL,  -- not unique: one manual can serve two cars
    requested_pages  TEXT NOT NULL DEFAULT '',     -- as typed: "30-31"; empty means let AMG find them
    pages_json       TEXT NOT NULL DEFAULT '[]',   -- the pages Claude was shown
    job_id           INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'reading', 'read', 'failed', 'confirmed', 'discarded')),
    extraction_json  TEXT,
    draft_json       TEXT,
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
    confirmed_at     TEXT
);
CREATE INDEX schedule_drafts_vehicle ON schedule_drafts (vehicle_id, status);
CREATE INDEX schedule_drafts_job ON schedule_drafts (job_id, status);

-- One car's schedule. An item is due every interval_miles or interval_months,
-- whichever comes first; first_miles / first_months, when set, is when the
-- first one falls due instead ("first at 137,500 mi or 11 years, then every
-- 75,000 mi or 6 years"). An item with a first and no interval is due once.
--   applies: always — under normal and severe service
--            normal — only under normal service (a severe item replaces it)
--            severe — only under severe service
--   source:  where the item came from — manual (document_id, page), claude,
--            template, or you.
CREATE TABLE schedule_items (
    id               INTEGER PRIMARY KEY,
    vehicle_id       INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    name             TEXT NOT NULL,             -- as the manual words it
    action           TEXT NOT NULL CHECK (action IN ('replace', 'inspect', 'perform')),
    interval_miles   INTEGER CHECK (interval_miles IS NULL OR interval_miles > 0),
    interval_months  INTEGER CHECK (interval_months IS NULL OR interval_months > 0),
    first_miles      INTEGER CHECK (first_miles IS NULL OR first_miles > 0),
    first_months     INTEGER CHECK (first_months IS NULL OR first_months > 0),
    applies          TEXT NOT NULL DEFAULT 'always' CHECK (applies IN ('always', 'normal', 'severe')),
    note             TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL CHECK (source IN ('manual', 'claude', 'template', 'you')),
    document_id      INTEGER REFERENCES documents (id) ON DELETE SET NULL,
    page             INTEGER,
    draft_id         INTEGER REFERENCES schedule_drafts (id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    CHECK (coalesce(interval_miles, interval_months, first_miles, first_months) IS NOT NULL)
);
CREATE INDEX schedule_items_vehicle ON schedule_items (vehicle_id, position);

-- What a schedule item asks for, in service types. One item can name several
-- ("disc brake pads and discs, axle boots and joints"); the item's action
-- applies to them all.
CREATE TABLE schedule_item_services (
    schedule_item_id  INTEGER NOT NULL REFERENCES schedule_items (id) ON DELETE CASCADE,
    service_type_id   INTEGER NOT NULL REFERENCES service_types (id) ON DELETE RESTRICT,
    PRIMARY KEY (schedule_item_id, service_type_id)
);
CREATE INDEX schedule_item_services_type ON schedule_item_services (service_type_id);
