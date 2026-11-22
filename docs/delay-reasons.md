# Historical delay reasons

`GET /api/v1/historical/delay-explanation?source_file=...&source_row_number=...`
reloads one source record and returns its flight reference, airline, route,
date, observed arrival and departure delay, reported causes, total reported
cause minutes and provenance. An unknown source row returns 404.

The five reported BTS fields are `CarrierDelay`, `WeatherDelay`, `NASDelay`,
`SecurityDelay`, and `LateAircraftDelay`. Only positive reported minutes
appear in the breakdown. Missing fields remain missing; they are never
converted to zero. Percentages divide each positive category by the sum of
positive reported category minutes, which need not equal the observed arrival
delay. If no category is positive, the response says, “No specific delay
cause was reported in the BTS record.”

The flight detail UI shows category minutes, percentage of reported cause
minutes, a proportional bar, the BTS record date and source row. These are
retrospective carrier reports. They are not inputs to the pre-departure model
and do not establish a cause for a current ADS-B aircraft.
