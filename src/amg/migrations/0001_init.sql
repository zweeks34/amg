-- Key/value settings: the login password hash, the session secret, and the
-- preferences later phases add (alert thresholds, inflation rate, ...).
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
