-- Recalls NHTSA lists for each car's year, make and model (ingest/recalls.py).
--
-- The check runs weekly from the daily alerts run, or from the car's page.
--   recalls_checked_on: the day NHTSA last answered; NULL means check on the next run
--                       (editing the car's year, make or model clears it)
--   recalls_model:      NHTSA's name for the model it matched ("OUTBACK"); '' for none
--   recalls_listed:     NHTSA's models of that year and make with recalls, comma-separated,
--                       to show when the car's model matched none of them
--   recalls_error:      why the last check failed; '' once one works
ALTER TABLE vehicles ADD COLUMN recalls_checked_on TEXT;
ALTER TABLE vehicles ADD COLUMN recalls_model TEXT NOT NULL DEFAULT '';
ALTER TABLE vehicles ADD COLUMN recalls_listed TEXT NOT NULL DEFAULT '';
ALTER TABLE vehicles ADD COLUMN recalls_error TEXT NOT NULL DEFAULT '';

-- One recall NHTSA listed for a car. NHTSA lists by model year, so one may not
-- fit this car (some cover only certain build dates): you say which.
--   campaign:     NHTSA's campaign number, "19V910000"
--   reported_on:  when NHTSA received the maker's report
--   park_it:      NHTSA says not to drive it until it's fixed
--   park_outside: NHTSA says to park it outside, away from buildings
--   status:       open     — not yet done, as far as AMG knows
--                 done     — done (closed_on, and the service if you said which)
--                 not_mine — doesn't apply to this car
-- A check adds new ones and leaves the status of known ones alone; an open one
-- NHTSA stops listing (after the car's model is corrected, say) is dropped.
CREATE TABLE recalls (
    id                INTEGER PRIMARY KEY,
    vehicle_id        INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    campaign          TEXT NOT NULL,
    reported_on       TEXT,
    component         TEXT NOT NULL DEFAULT '',
    summary           TEXT NOT NULL DEFAULT '',
    consequence       TEXT NOT NULL DEFAULT '',
    remedy            TEXT NOT NULL DEFAULT '',
    park_it           INTEGER NOT NULL DEFAULT 0 CHECK (park_it IN (0, 1)),
    park_outside      INTEGER NOT NULL DEFAULT 0 CHECK (park_outside IN (0, 1)),
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'not_mine')),
    closed_on         TEXT,
    service_event_id  INTEGER REFERENCES service_events (id) ON DELETE SET NULL,
    note              TEXT NOT NULL DEFAULT '',
    found_at          TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (vehicle_id, campaign)
);
CREATE INDEX recalls_open ON recalls (status, vehicle_id);
