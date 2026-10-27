-- Logos you uploaded, stored like a car's photo, shown instead of a fetched icon. One for a station or shop is
-- kept with its name, on places; one for a brand AMG recognises is used for every station or shop that's that
-- brand. added: a station or shop you set up on Stations and shops before visiting it, listed until you do.
ALTER TABLE places ADD COLUMN logo_document_id INTEGER REFERENCES documents (id);
ALTER TABLE places ADD COLUMN added INTEGER NOT NULL DEFAULT 0;

CREATE TABLE brand_logos (
    brand        TEXT PRIMARY KEY,                  -- as web/brands.py names it: "BP"
    document_id  INTEGER NOT NULL REFERENCES documents (id),
    updated_at   TEXT NOT NULL
);
