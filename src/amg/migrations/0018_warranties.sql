-- Warranties: a part's or a repair's, read from a receipt or typed in, and
-- the car's own (factory or extended), each running from a day and the miles
-- then for some months, some miles, whichever comes first, or for life.
--
--   receipt_id, phrase: read from that receipt. Its draft is the record, as
--                       for everything on a receipt: saving the receipt
--                       rewrites these rows, found again by the wording
--                       (normalised as drafts.phrase), so answers survive.
--   service_event_id:   the visit it came with, if any. SET NULL: the
--                       warranty keeps its own start day and miles.
--   months, miles:      how long it lasts, whichever comes first; both NULL
--                       is lifetime.
--   start_miles:        NULL is "estimate from the readings".
--   whole_car:          covers the car, not listed parts (warranty_covers is
--                       empty).
CREATE TABLE warranties (
    id                INTEGER PRIMARY KEY,
    vehicle_id        INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    receipt_id        INTEGER REFERENCES receipts (id) ON DELETE CASCADE,
    phrase            TEXT NOT NULL DEFAULT '',
    service_event_id  INTEGER REFERENCES service_events (id) ON DELETE SET NULL,
    title             TEXT NOT NULL CHECK (title <> ''),
    provider          TEXT NOT NULL DEFAULT '',
    details           TEXT NOT NULL DEFAULT '',
    starts_on         TEXT NOT NULL,
    start_miles       INTEGER CHECK (start_miles IS NULL OR start_miles >= 0),
    months            INTEGER CHECK (months IS NULL OR months > 0),
    miles             INTEGER CHECK (miles IS NULL OR miles > 0),
    whole_car         INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (receipt_id, phrase)
);
CREATE INDEX warranties_by_car ON warranties (vehicle_id);
CREATE INDEX warranties_by_event ON warranties (service_event_id);

-- The services a warranty covers.
CREATE TABLE warranty_covers (
    warranty_id      INTEGER NOT NULL REFERENCES warranties (id) ON DELETE CASCADE,
    service_type_id  INTEGER NOT NULL REFERENCES service_types (id) ON DELETE RESTRICT,
    PRIMARY KEY (warranty_id, service_type_id)
);

-- What you said about a later visit that replaced a covered part:
--   claimed — done under the warranty, which carries on
--   paid    — you paid for it, and the warranty ended that day: the part it
--             covered is gone
CREATE TABLE warranty_answers (
    warranty_id  INTEGER NOT NULL REFERENCES warranties (id) ON DELETE CASCADE,
    event_id     INTEGER NOT NULL REFERENCES service_events (id) ON DELETE CASCADE,
    answer       TEXT NOT NULL CHECK (answer IN ('claimed', 'paid')),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (warranty_id, event_id)
);
