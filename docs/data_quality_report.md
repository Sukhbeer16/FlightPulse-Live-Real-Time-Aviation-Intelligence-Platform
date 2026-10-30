# BTS January 2024 data quality report

- **Input file:** `On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.csv`
- **Validated (UTC):** 2026-10-30T17:11:53.265585+00:00
- **File size:** 246,830,488 bytes
- **Columns:** 110
- **Named columns:** 109
- **Blank-header columns:** Unnamed: 109
- **Missing optional relevant columns:** None
- **Rows scanned:** 547,271
- **Unique rows:** 547,271
- **Duplicate rows after first occurrence:** 0
- **Unparseable non-empty dates:** 0
- **Rows outside January 2024:** 0

## Missing values

| Column | Missing/blank rows |
|---|---:|
| `ActualElapsedTime` | 21,901 |
| `AirTime` | 21,901 |
| `ArrDel15` | 21,901 |
| `ArrDelay` | 21,901 |
| `ArrDelayMinutes` | 21,901 |
| `ArrTime` | 20,633 |
| `ArrivalDelayGroups` | 21,901 |
| `CancellationCode` | 526,882 |
| `CarrierDelay` | 420,861 |
| `DepDel15` | 19,858 |
| `DepDelay` | 19,858 |
| `DepDelayMinutes` | 19,858 |
| `DepTime` | 19,784 |
| `DepartureDelayGroups` | 19,858 |
| `Div1Airport` | 545,627 |
| `Div1AirportID` | 545,627 |
| `Div1AirportSeqID` | 545,627 |
| `Div1LongestGTime` | 545,627 |
| `Div1TailNum` | 545,985 |
| `Div1TotalGTime` | 545,627 |
| `Div1WheelsOff` | 545,985 |
| `Div1WheelsOn` | 545,627 |
| `Div2Airport` | 547,233 |
| `Div2AirportID` | 547,233 |
| `Div2AirportSeqID` | 547,233 |
| `Div2LongestGTime` | 547,233 |
| `Div2TailNum` | 547,250 |
| `Div2TotalGTime` | 547,233 |
| `Div2WheelsOff` | 547,250 |
| `Div2WheelsOn` | 547,233 |
| `Div3Airport` | 547,270 |
| `Div3AirportID` | 547,270 |
| `Div3AirportSeqID` | 547,270 |
| `Div3LongestGTime` | 547,270 |
| `Div3TailNum` | 547,270 |
| `Div3TotalGTime` | 547,270 |
| `Div3WheelsOff` | 547,270 |
| `Div3WheelsOn` | 547,270 |
| `Div4Airport` | 547,271 |
| `Div4AirportID` | 547,271 |
| `Div4AirportSeqID` | 547,271 |
| `Div4LongestGTime` | 547,271 |
| `Div4TailNum` | 547,271 |
| `Div4TotalGTime` | 547,271 |
| `Div4WheelsOff` | 547,271 |
| `Div4WheelsOn` | 547,271 |
| `Div5Airport` | 547,271 |
| `Div5AirportID` | 547,271 |
| `Div5AirportSeqID` | 547,271 |
| `Div5LongestGTime` | 547,271 |
| `Div5TailNum` | 547,271 |
| `Div5TotalGTime` | 547,271 |
| `Div5WheelsOff` | 547,271 |
| `Div5WheelsOn` | 547,271 |
| `DivActualElapsedTime` | 546,003 |
| `DivArrDelay` | 546,003 |
| `DivDistance` | 545,759 |
| `DivReachedDest` | 545,759 |
| `FirstDepTime` | 542,543 |
| `LateAircraftDelay` | 420,861 |
| `LongestAddGTime` | 542,543 |
| `NASDelay` | 420,861 |
| `SecurityDelay` | 420,861 |
| `Tail_Number` | 5,293 |
| `TaxiIn` | 20,634 |
| `TaxiOut` | 20,257 |
| `TotalAddGTime` | 542,543 |
| `Unnamed: 109` | 547,271 |
| `WeatherDelay` | 420,861 |
| `WheelsOff` | 20,257 |
| `WheelsOn` | 20,634 |

## Invalid values

Counts include non-numeric values in numeric fields and values outside
the documented sanity ranges. Counts are per field; one row may be
invalid in more than one field.

| Column | Invalid values |
|---|---:|
| None | 0 |

## Schema and type observations

| Column | Validated semantic type(s) |
|---|---|
| `ActualElapsedTime` | numeric |
| `AirTime` | string/category |
| `ArrDel15` | string/category |
| `ArrDelay` | numeric |
| `ArrDelayMinutes` | numeric |
| `ArrTime` | numeric |
| `ArrTimeBlk` | string/category |
| `ArrivalDelayGroups` | string/category |
| `CRSArrTime` | numeric |
| `CRSDepTime` | numeric |
| `CRSElapsedTime` | numeric |
| `CancellationCode` | string/category |
| `Cancelled` | numeric |
| `CarrierDelay` | numeric |
| `DOT_ID_Reporting_Airline` | string/category |
| `DayOfWeek` | string/category |
| `DayofMonth` | string/category |
| `DepDel15` | string/category |
| `DepDelay` | numeric |
| `DepDelayMinutes` | numeric |
| `DepTime` | numeric |
| `DepTimeBlk` | string/category |
| `DepartureDelayGroups` | string/category |
| `Dest` | string/category |
| `DestAirportID` | string/category |
| `DestAirportSeqID` | string/category |
| `DestCityMarketID` | string/category |
| `DestCityName` | string/category |
| `DestState` | string/category |
| `DestStateFips` | string/category |
| `DestStateName` | string/category |
| `DestWac` | string/category |
| `Distance` | numeric |
| `DistanceGroup` | string/category |
| `Div1Airport` | string/category |
| `Div1AirportID` | string/category |
| `Div1AirportSeqID` | string/category |
| `Div1LongestGTime` | string/category |
| `Div1TailNum` | string/category |
| `Div1TotalGTime` | string/category |
| `Div1WheelsOff` | string/category |
| `Div1WheelsOn` | string/category |
| `Div2Airport` | string/category |
| `Div2AirportID` | string/category |
| `Div2AirportSeqID` | string/category |
| `Div2LongestGTime` | string/category |
| `Div2TailNum` | string/category |
| `Div2TotalGTime` | string/category |
| `Div2WheelsOff` | string/category |
| `Div2WheelsOn` | string/category |
| `Div3Airport` | string/category |
| `Div3AirportID` | string/category |
| `Div3AirportSeqID` | string/category |
| `Div3LongestGTime` | string/category |
| `Div3TailNum` | string/category |
| `Div3TotalGTime` | string/category |
| `Div3WheelsOff` | string/category |
| `Div3WheelsOn` | string/category |
| `Div4Airport` | string/category |
| `Div4AirportID` | string/category |
| `Div4AirportSeqID` | string/category |
| `Div4LongestGTime` | string/category |
| `Div4TailNum` | string/category |
| `Div4TotalGTime` | string/category |
| `Div4WheelsOff` | string/category |
| `Div4WheelsOn` | string/category |
| `Div5Airport` | string/category |
| `Div5AirportID` | string/category |
| `Div5AirportSeqID` | string/category |
| `Div5LongestGTime` | string/category |
| `Div5TailNum` | string/category |
| `Div5TotalGTime` | string/category |
| `Div5WheelsOff` | string/category |
| `Div5WheelsOn` | string/category |
| `DivActualElapsedTime` | string/category |
| `DivAirportLandings` | string/category |
| `DivArrDelay` | string/category |
| `DivDistance` | string/category |
| `DivReachedDest` | string/category |
| `Diverted` | numeric |
| `FirstDepTime` | string/category |
| `FlightDate` | date |
| `Flight_Number_Reporting_Airline` | string/category |
| `Flights` | string/category |
| `IATA_CODE_Reporting_Airline` | string/category |
| `LateAircraftDelay` | numeric |
| `LongestAddGTime` | string/category |
| `Month` | string/category |
| `NASDelay` | numeric |
| `Origin` | string/category |
| `OriginAirportID` | string/category |
| `OriginAirportSeqID` | string/category |
| `OriginCityMarketID` | string/category |
| `OriginCityName` | string/category |
| `OriginState` | string/category |
| `OriginStateFips` | string/category |
| `OriginStateName` | string/category |
| `OriginWac` | string/category |
| `Quarter` | string/category |
| `Reporting_Airline` | string/category |
| `SecurityDelay` | numeric |
| `Tail_Number` | string/category |
| `TaxiIn` | string/category |
| `TaxiOut` | string/category |
| `TotalAddGTime` | string/category |
| `Unnamed: 109` | string/category |
| `WeatherDelay` | numeric |
| `WheelsOff` | string/category |
| `WheelsOn` | string/category |
| `Year` | string/category |

Missing-column notices for non-required BTS fields are informational.
Core columns required for date-, route-, and label-based processing are
validated before cleaning. Invalid dates, out-of-scope dates, incomplete
flight identity fields, and exact duplicate records are excluded from the
processed output; missing measurements are not imputed.

## Processing result

- **Processed rows:** 547,271
- **Excluded rows:** 0
- **Entirely empty unnamed columns omitted from Parquet:** Unnamed: 109
- **Raw CSV SHA-256:** `e92febedf6cd51bd87eca0be2fba3f5c1f383b1da41119db7f1cc1a26c4d3286`
- **Source:** U.S. Department of Transportation, Bureau of Transportation Statistics
- **Source URL:** https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.zip
- **Acquisition method:** official BTS PREZIP archive download
- **Download date (UTC):** 2026-10-30T17:11:21.579736+00:00
- **Imported date (UTC):** Not applicable

EDA CSV tables and PNG charts were written under `reports/eda/2024-01/`.

## Measured ingestion and target results

The following values were rechecked from the preserved raw CSV in 50,000-row
chunks and from the generated Parquet output. Counts below describe the actual
January 2024 BTS source; no values were imputed.

| Measure | Observed value |
|---|---:|
| Downloaded ZIP size | 27,573,265 bytes |
| Extracted raw CSV size | 246,830,488 bytes |
| Source CSV rows | 547,271 |
| Retained rows in Parquet | 547,271 |
| Removed source rows | 0 |
| Exact duplicate rows removed | 0 |
| Unparseable dates | 0 |
| Out-of-scope dates | 0 |
| Rows with missing airline/origin/destination identity | 0 |
| Invalid values in validated numeric/time/flag ranges | 0 |
| Cancelled flights | 20,389 |
| Diverted flights | 1,512 |
| Flights marked both cancelled and diverted | 0 |
| Rows with known operating status but missing `ArrDelay` | 0 |
| Eligible delay targets (`Cancelled=0`, `Diverted=0`, `ArrDelay` present) | 525,370 |
| Delayed eligible flights (`ArrDelay > 15`) | 122,508 |
| Non-delayed eligible flights (`ArrDelay <= 15`) | 402,862 |
| Reporting airlines | 15 |
| Origin airports | 334 |
| Destination airports | 334 |
| Distinct origin-destination routes | 5,666 |

Target reconciliation: 547,271 retained rows = 20,389 cancelled + 1,512
diverted + 525,370 eligible operating flights. The categories are disjoint in
the source. There are no unknown cancellation/diversion flags. Eligible target
rows further reconcile as 122,508 delayed + 402,862 non-delayed = 525,370.

The Parquet output is one Zstandard-compressed file,
`data/processed/bts_ontime_2024_01.parquet`, containing 547,271 rows in 11 row
groups. It was reopened and scanned batchwise; target counts matched the raw
CSV, and the leakage-safe training-frame selector excluded actual outcome
columns.

## EDA outputs

Measured summary tables and plots are under `reports/eda/2024-01/`:

- Tables: `overview.csv`, `arrival_delay_distribution.csv`,
  `airline_delays.csv`, `airport_delays.csv`, `route_delays.csv`, and
  `hour_delays.csv`.
- Plots: `airline_delay_rates.png`, `airport_delay_rates.png`,
  `route_delay_rates.png`, `hourly_delay_rates.png`, and
  `arrival_delay_distribution.png`.

The overview records 547,271 flights, 20,389 cancellations (3.7256% of rows
with known cancellation status), 525,370 eligible flights, and 122,508 delayed
eligible arrivals (23.3184% of eligible flights).
