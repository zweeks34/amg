-- Where a fill-up or charge was bought: the station as you typed it, "Shell" or
-- "Wawa on Route 9". Blank when not given, as every fill logged before this is.
ALTER TABLE fuel_logs ADD COLUMN station TEXT NOT NULL DEFAULT '';
