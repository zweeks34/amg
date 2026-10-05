-- Inspections and registration: dates the state sets, not the owner's manual.
--
-- A row is one safety inspection, emissions inspection or registration
-- renewal, good through expires_on: the date on the sticker or the
-- registration card, which you type (AMG only suggests one). A kind's current
-- one is the latest expiry; the rows before it are its history.
--
--   done_on:          when it was inspected or renewed; NULL when only the
--                     expiry is known (typed in from the sticker)
--   service_event_id: the service whose receipt shows the inspection, when it
--                     was logged from one
CREATE TABLE renewals (
    id                INTEGER PRIMARY KEY,
    vehicle_id        INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    kind              TEXT NOT NULL CHECK (kind IN ('safety', 'emissions', 'registration')),
    done_on           TEXT,
    expires_on        TEXT NOT NULL,
    cost_cents        INTEGER CHECK (cost_cents IS NULL OR cost_cents >= 0),
    note              TEXT NOT NULL DEFAULT '',
    service_event_id  INTEGER REFERENCES service_events (id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    CHECK (done_on IS NULL OR done_on <= expires_on)
);
CREATE INDEX renewals_vehicle ON renewals (vehicle_id, kind, expires_on);
