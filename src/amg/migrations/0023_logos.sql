-- Logos for the stations on your fill-ups and the shops on your services.
--
-- places: what you've said about a station or shop, by its name in any
-- capitals. Its website, where its logo comes from; or its letter instead of a
-- logo. A name with no row here gets the logo of the brand AMG recognises in
-- it, if any (web/brands.py).
CREATE TABLE places (
    name         TEXT PRIMARY KEY COLLATE NOCASE,
    website      TEXT NOT NULL DEFAULT '',          -- "joesgarage.com"; blank: as recognised
    letter_only  INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

-- site_icons: each website's icon as AMG fetched it, a 96px square PNG; NULL
-- when none was found, which is tried again 30 days after fetched_at. A copy,
-- not your data: it can always be fetched again.
CREATE TABLE site_icons (
    site        TEXT PRIMARY KEY,                   -- "wawa.com"
    png         BLOB,
    source      TEXT NOT NULL DEFAULT '',           -- the address it came from
    fetched_at  TEXT NOT NULL
);
