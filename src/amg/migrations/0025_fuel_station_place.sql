-- The town a station is in: its city as you typed it, and the two-letter code of
-- its US state or Canadian province or territory. Blank when not given, as every
-- fill logged before this is. Not called plain "state": that word is the fuel
-- page's own.
ALTER TABLE fuel_logs ADD COLUMN station_city TEXT NOT NULL DEFAULT '';
ALTER TABLE fuel_logs ADD COLUMN station_state TEXT NOT NULL DEFAULT '';
