-- Issues: what you've noticed wrong with a car ("rattle from the front at 40
-- mph"), to show the shop, until a visit fixes it.
--
-- A later visit closes nothing by itself: a shop can look at a rattle and
-- miss it. AMG asks about the newest visit since you noticed it, and you say.
--   status:            open    — still there, as far as AMG knows
--                      fixed   — closed_on, and the service that fixed it if you said which
--                      dropped — went away, or you'll live with it (closed_on)
--   fixed_by_event_id: SET NULL, so deleting the service keeps the fix and its date
CREATE TABLE issues (
    id                 INTEGER PRIMARY KEY,
    vehicle_id         INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    title              TEXT NOT NULL CHECK (title <> ''),
    details            TEXT NOT NULL DEFAULT '',
    noticed_on         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'fixed', 'dropped')),
    closed_on          TEXT,
    fixed_by_event_id  INTEGER REFERENCES service_events (id) ON DELETE SET NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX issues_by_car ON issues (vehicle_id, status);

-- An issue's photos, in order: each its own document, stored as receipt scans are.
CREATE TABLE issue_photos (
    issue_id     INTEGER NOT NULL REFERENCES issues (id) ON DELETE CASCADE,
    document_id  INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    PRIMARY KEY (issue_id, document_id)
);

-- A visit you said didn't fix an issue: what's been tried, for the shop, and
-- why AMG stops asking about that visit.
CREATE TABLE issue_checks (
    issue_id    INTEGER NOT NULL REFERENCES issues (id) ON DELETE CASCADE,
    event_id    INTEGER NOT NULL REFERENCES service_events (id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (issue_id, event_id)
);
