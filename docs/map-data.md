# Dataset map data

The map aggregates the January and February 2024 BTS Parquet files. Across
1,066,492 source rows it resolves **334 airport sequence IDs**, **328 source
named airport cities**, and **5,757 directed origin-destination routes**.
All 1,066,492 rows in this local dataset have coordinates for both endpoints.
The source archives are ignored local data and are not bundled in Git.

`GET /api/v1/historical/map-coverage` groups actual records by origin and
destination airport sequence IDs. It returns route flight counts, known-delay
counts, delayed percentages and mean arrival delay. Airport counts count
touches at either endpoint, so their sum is twice the flight count. Delay
percentage uses records with a reported arrival delay as its denominator.
Routes are sorted by flight volume and paginated; the UI shows 15 aggregated
routes per map page. The API supports `page`, `page_size`, `city`, `airport`,
`origin`, `destination`, `airline`, `flight_number`, `date_from`, `date_to`, and
`delayed` filters. The city selector lists cities found in the source data.
Selecting a route filters the underlying flight roster to that pair.

Airport names, city names and coordinates come from the exact
`AIRPORT_SEQ_ID` join into `Master_Coordinate.zip`. Carrier names use the
exact DOT airline ID in `Carrier_Decode.zip`. A BTS `Origin` or `Dest` code
is displayed as its source code, without claiming it is an IATA identifier.
Records missing reference coordinates remain in the flight list and are
excluded from the map geometry. No coordinates or city names are guessed.

Map lines show historical airport-to-airport routes, and the plane symbols
mark route midpoints for selection. Neither is a reconstructed trajectory or
a current aircraft position. **Live radar** uses direct provider positions;
**Kafka stream** uses fresh, consumed provider positions. The three sources
remain separate.
