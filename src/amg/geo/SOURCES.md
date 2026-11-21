# Where the map's data comes from

`places.tsv.gz` and `regions.json` are built by `scripts/build_places.py` from
these files, downloaded 2026-11-21. To refresh them, download the same files
again into one folder and run the script with that folder.

| Built into | Source | File | Licence |
|---|---|---|---|
| `places.tsv.gz` (US) | US Census Bureau, 2024 Gazetteer Files: places | `www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip` | Public domain |
| `places.tsv.gz` (US) | US Census Bureau, 2024 Gazetteer Files: county subdivisions (townships) | `…/2024_Gazetteer/2024_Gaz_cousubs_national.zip` | Public domain |
| `places.tsv.gz` (Canada) | GeoNames, Canada | `download.geonames.org/export/dump/CA.zip` | CC BY 4.0: credit "GeoNames" (the map page does) |
| `regions.json` | Natural Earth 5.1.2, 1:50m admin 1 states and provinces | `raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_1_states_provinces.geojson` | Public domain |

Kept from each: the US places and townships' names (without "city",
"township" and the like) and their internal points; Canada's populated places
with a population or an administrative role, by name and ASCII name; and the
outer outline of each US state and Canadian province, projected
(`amg.engine.geo.project`) and simplified to about a kilometre.
