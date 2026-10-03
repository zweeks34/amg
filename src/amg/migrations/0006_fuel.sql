-- Fill-ups and charges: fuel economy, running cost, and an odometer reading
-- every time the car is filled.
--
--   energy:        gas (quantity in US gallons) or electric (kWh). Set from the
--                  car's powertrain when the row is saved and kept with it, so
--                  correcting the powertrain later never changes old units.
--   full:          filled the tank / charged to the usual limit. Economy is
--                  measured from one full fill to the next.
--   missed_before: a fill since the last one logged wasn't logged; economy is
--                  not measured across it.
--   place:         home or public — charges only.
CREATE TABLE fuel_logs (
    id             INTEGER PRIMARY KEY,
    vehicle_id     INTEGER NOT NULL REFERENCES vehicles (id) ON DELETE CASCADE,
    filled_on      TEXT NOT NULL,
    odometer       INTEGER NOT NULL CHECK (odometer >= 0),
    energy         TEXT NOT NULL CHECK (energy IN ('gas', 'electric')),
    quantity       REAL NOT NULL CHECK (quantity > 0),
    cost_cents     INTEGER CHECK (cost_cents IS NULL OR cost_cents >= 0),  -- NULL: not known
    full           INTEGER NOT NULL DEFAULT 1,
    missed_before  INTEGER NOT NULL DEFAULT 0,
    place          TEXT CHECK (place IS NULL OR place IN ('home', 'public')),
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX fuel_logs_vehicle ON fuel_logs (vehicle_id, filled_on);

-- Fill-ups and charges join the odometer's other sources.
DROP VIEW odometer_points;
CREATE VIEW odometer_points AS
    SELECT vehicle_id, read_on, miles, 'manual' AS source, id AS source_id
      FROM odometer_readings
    UNION ALL
    SELECT vehicle_id, performed_on, odometer, 'service', id
      FROM service_events
     WHERE odometer IS NOT NULL AND confirmed = 1
    UNION ALL
    SELECT id, acquired_date, acquired_miles, 'acquired', id
      FROM vehicles
     WHERE acquired_date IS NOT NULL AND acquired_miles IS NOT NULL
    UNION ALL
    SELECT vehicle_id, filled_on, odometer, CASE energy WHEN 'electric' THEN 'charge' ELSE 'fill' END, id
      FROM fuel_logs;
