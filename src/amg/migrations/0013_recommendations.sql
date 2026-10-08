-- Shop recommendations: work a receipt marks as recommended, declined or due
-- next time. They live in the receipt's draft_json, which stays the editable
-- record; this keeps what you decided about each one.
--
-- A recommendation closes by itself when a later service does the work, so
-- that isn't stored. What is: you logged it from the recommendation (done,
-- with the service), or you're not doing it (skipped). A recommendation is
-- found by its receipt and its wording, normalised as a line's is for learned
-- wording (drafts.phrase): reword it on the receipt and it reopens.
CREATE TABLE recommendation_outcomes (
    id                INTEGER PRIMARY KEY,
    receipt_id        INTEGER NOT NULL REFERENCES receipts (id) ON DELETE CASCADE,
    phrase            TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('done', 'skipped')),
    service_event_id  INTEGER REFERENCES service_events (id) ON DELETE CASCADE,
    created_at        TEXT NOT NULL,
    UNIQUE (receipt_id, phrase)
);
