-- A photo for each car, shown as its avatar beside its name: one of the
-- stored files (documents). NULL when it has none; the car's initial stands in.
-- Replacing or removing it leaves the file, as a discarded receipt's is left.
ALTER TABLE vehicles ADD COLUMN photo_document_id INTEGER REFERENCES documents (id);
