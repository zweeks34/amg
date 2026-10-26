-- How a car's photo sits in its avatar. At zoom 1 the circle shows the whole
-- photo, whatever its shape; up to 4 zooms in about its centre. x and y move
-- it, as a share of the circle's width (-100 to 100 percent). The defaults
-- show the whole photo, centred.
ALTER TABLE vehicles ADD COLUMN photo_zoom REAL NOT NULL DEFAULT 1 CHECK (photo_zoom BETWEEN 1 AND 4);
ALTER TABLE vehicles ADD COLUMN photo_x REAL NOT NULL DEFAULT 0 CHECK (photo_x BETWEEN -100 AND 100);
ALTER TABLE vehicles ADD COLUMN photo_y REAL NOT NULL DEFAULT 0 CHECK (photo_y BETWEEN -100 AND 100);
