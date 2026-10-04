-- Alerts: which cars send them, and every alert sent (or held back), once.
--
-- A car's alerts are off until you turn them on. Turning them on takes stock:
-- what's already due or overdue is logged as known, not sent.
ALTER TABLE vehicles ADD COLUMN alerts INTEGER NOT NULL DEFAULT 0 CHECK (alerts IN (0, 1));

-- Each alert is logged before it goes out, and UNIQUE (channel, subject, level)
-- means it goes out once: a second run, or two at once, finds the row taken.
-- Only a failed send is tried again.
--
--   subject: what it's about.
--            A job's round:  "{vehicle_id}:{codes}:{action}:{since}", where
--                            since is the last service that did the job
--                            ("s123"), or "new" if none has. Doing the job
--                            starts the next round; a new schedule with the
--                            same jobs keeps the same subjects.
--            A digest:       "digest:2026-W40", the ISO week it's for.
--   level:   due (due soon), overdue, or digest
--   outcome: sending — claimed by a run, going out now
--            sent    — gone
--            known   — held back: already due when the car's alerts were
--                      turned on
--            failed  — didn't go; error says why, and the next run retries
CREATE TABLE alert_log (
    id          INTEGER PRIMARY KEY,
    channel     TEXT NOT NULL CHECK (channel IN ('ntfy', 'email')),
    subject     TEXT NOT NULL,
    level       TEXT NOT NULL CHECK (level IN ('due', 'overdue', 'digest')),
    vehicle_id  INTEGER REFERENCES vehicles (id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    outcome     TEXT NOT NULL CHECK (outcome IN ('sending', 'sent', 'known', 'failed')),
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (channel, subject, level)
);
CREATE INDEX alert_log_recent ON alert_log (updated_at);
