# RIGGS scientific-context milestone — 2026-10-16

## Completed

- Added an authenticated `GET /frozen-legacies/api/context/riggs` endpoint.
- Added a separately switchable RIGGS map layer, disabled by default.
- Used equally bounded point symbols: square for seismic and triangle for
  radar, with the same 4.5-pixel radius as radar-observation points.
- Added station inspection with method, selected thickness, original seismic
  and radar values, citation, source record, and an explicit warning that the
  station is not a Frozen Legacies pick.
- Required the source CSV and provenance manifest to live under an approved
  storage root.
- Added fail-closed validation for the exact source checksum, manifest schema,
  HTTPS source record, citation, required columns, station IDs, coordinate
  ranges, measurement values, and station-count/byte limits.
- Documented the intake contract and API.

## Evidence

- Focused backend/frontend tests: 59 passed.
- Protected route/frontend integration tests: 76 passed.
- Complete Frozen Legacies suite: 633 passed, 2 skipped.
- JavaScript syntax checks passed.
- Changed-file whitespace validation passed.

## Data finding and release state

The imported LYRA code expects `Data/RIGGS/riggs_stations.csv`, but that file
is not present in the LYRA tree, its ZIP, the CryoStack repository, or the
operator's home tree. No points were copied from publications or generated.
The UI therefore remains hidden and the endpoint returns an empty optional
collection until the actual table and authoritative citation are supplied.

Promotion to the isolated staging service was attempted after tests, but the
reviewed installer requires interactive sudo and no cached authorization was
available. The safeguard was preserved. No production restart or data change
was made for this milestone.
