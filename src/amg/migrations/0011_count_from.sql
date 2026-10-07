-- A date a schedule item's count starts on, for a job you never kept records
-- of (topping up washer fluid): the gap engine treats it as done that day, so
-- nothing before it counts as missed. NULL counts from new, or from when you
-- got the car, as before.
ALTER TABLE schedule_items ADD COLUMN counts_from TEXT;
