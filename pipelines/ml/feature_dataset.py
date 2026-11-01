"""Build a leakage-safe, reproducible BTS flight-delay feature dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipelines.spark.bts_validation import EXPECTED_METRICS


DEFAULT_INPUT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "bts_ontime_2024_01.parquet"
)
DEFAULT_OUTPUT_DIRECTORY = DEFAULT_INPUT_PATH.parent / "ml"
DEFAULT_DATASET_NAME = "flight_delay_features.parquet"
DEFAULT_MANIFEST_NAME = "feature_manifest.json"
TARGET_COLUMN = "target_arr_delay_gt_15"
FLIGHT_DATE_COLUMN = "flight_date"
SPLIT_COLUMN = "split"
MISSING_CATEGORY = "__MISSING__"
TRAIN_END = date(2024, 1, 21)
VALIDATION_END = date(2024, 1, 26)
ROW_GROUP_SIZE = 50_000

SOURCE_COLUMNS = (
    "FlightDate",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSArrTime",
    "CRSElapsedTime",
    "Distance",
    "ArrDelay",
    "Cancelled",
    "Diverted",
)

CATEGORICAL_FEATURES = ("Reporting_Airline", "Origin", "Dest")
NUMERIC_FEATURES = (
    "month",
    "day_of_month",
    "day_of_week",
    "scheduled_departure_sin",
    "scheduled_departure_cos",
    "scheduled_arrival_sin",
    "scheduled_arrival_cos",
    "scheduled_elapsed_time_minutes",
    "distance_miles",
)
MISSING_INDICATOR_FEATURES = tuple(
    f"is_missing_{name}" for name in NUMERIC_FEATURES
)
FEATURE_ALLOWLIST = (
    *CATEGORICAL_FEATURES,
    *NUMERIC_FEATURES,
    *MISSING_INDICATOR_FEATURES,
)

_DIVERSION_DETAILS = {
    f"Div{index}{field}"
    for index in range(1, 6)
    for field in (
        "Airport",
        "AirportID",
        "AirportSeqID",
        "WheelsOn",
        "TotalGTime",
        "LongestGTime",
        "WheelsOff",
        "TailNum",
    )
}
LEAKAGE_DENYLIST = frozenset(
    {
        TARGET_COLUMN,
        "is_delayed",
        "ArrDelay",
        "ArrDelayMinutes",
        "ArrDel15",
        "ArrivalDelayGroups",
        "DepDelay",
        "DepDelayMinutes",
        "DepDel15",
        "DepartureDelayGroups",
        "DepTime",
        "ArrTime",
        "ActualElapsedTime",
        "AirTime",
        "TaxiIn",
        "TaxiOut",
        "WheelsOff",
        "WheelsOn",
        "FirstDepTime",
        "Cancelled",
        "CancellationCode",
        "Diverted",
        "DivAirportLandings",
        "DivReachedDest",
        "DivActualElapsedTime",
        "DivArrDelay",
        "DivDistance",
        "CarrierDelay",
        "WeatherDelay",
        "NASDelay",
        "SecurityDelay",
        "LateAircraftDelay",
        "is_trainable",
        "arrival_delay_category",
    }
) | frozenset(_DIVERSION_DETAILS)

if set(FEATURE_ALLOWLIST) & LEAKAGE_DENYLIST:
    raise RuntimeError("The ML feature allowlist overlaps the leakage denylist.")


def parse_scheduled_hhmm(
    values: Sequence[object] | pa.Array | pa.ChunkedArray,
) -> pa.Array:
    """Convert valid numeric HHMM values to minutes after midnight.

    Single- and double-digit values represent minutes after midnight (5 is
    00:05); 2400 maps to 00:00. Null, non-finite, fractional, and malformed
    clock values become null rather than being coerced.
    """
    source = (
        values.to_pylist()
        if isinstance(values, (pa.Array, pa.ChunkedArray))
        else values
    )
    parsed: list[int | None] = []
    for value in source:
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not float(value).is_integer()
        ):
            parsed.append(None)
            continue
        hhmm = int(value)
        hour, minute = divmod(hhmm, 100)
        if hhmm == 2_400:
            parsed.append(0)
        elif 0 <= hhmm < 2_400 and hour < 24 and minute < 60:
            parsed.append(hour * 60 + minute)
        else:
            parsed.append(None)
    return pa.array(parsed, type=pa.int16())


def _cyclic_time_features(minutes: pa.Array) -> tuple[pa.Array, pa.Array]:
    sine: list[float | None] = []
    cosine: list[float | None] = []
    for value in minutes.to_pylist():
        if value is None:
            sine.append(None)
            cosine.append(None)
        else:
            angle = 2 * math.pi * value / 1_440
            sine.append(math.sin(angle))
            cosine.append(math.cos(angle))
    return pa.array(sine, type=pa.float64()), pa.array(cosine, type=pa.float64())


def _count(mask: pa.Array) -> int:
    count = pc.sum(pc.cast(pc.fill_null(mask, False), pa.int64())).as_py()
    return int(count or 0)


def _validate_source_schema(schema: pa.Schema) -> None:
    missing = sorted(set(SOURCE_COLUMNS).difference(schema.names))
    if missing:
        raise ValueError(f"BTS Parquet is missing required columns: {missing}")

    expected_types = {
        "FlightDate": pa.types.is_timestamp,
        "Reporting_Airline": pa.types.is_string,
        "Origin": pa.types.is_string,
        "Dest": pa.types.is_string,
    }
    invalid = [
        name
        for name, predicate in expected_types.items()
        if not predicate(schema.field(name).type)
    ]
    numeric = (
        "CRSDepTime",
        "CRSArrTime",
        "CRSElapsedTime",
        "Distance",
        "ArrDelay",
        "Cancelled",
        "Diverted",
    )
    invalid.extend(
        name
        for name in numeric
        if not (
            pa.types.is_integer(schema.field(name).type)
            or pa.types.is_floating(schema.field(name).type)
        )
    )
    if invalid:
        raise ValueError(f"Unexpected types for BTS columns: {sorted(invalid)}")


def _source_metrics(source: pa.Table) -> dict[str, int]:
    cancelled = pc.equal(source["Cancelled"], 1)
    diverted = pc.equal(source["Diverted"], 1)
    operating = pc.and_kleene(
        pc.equal(source["Cancelled"], 0),
        pc.equal(source["Diverted"], 0),
    )
    eligible = pc.and_kleene(operating, pc.is_valid(source["ArrDelay"]))
    delayed = pc.and_kleene(eligible, pc.greater(source["ArrDelay"], 15))
    non_delayed = pc.and_kleene(eligible, pc.less_equal(source["ArrDelay"], 15))
    overlap = pc.and_kleene(cancelled, diverted)
    unknown_cancelled = pc.invert(
        pc.fill_null(
            pc.or_kleene(
                pc.equal(source["Cancelled"], 0),
                pc.equal(source["Cancelled"], 1),
            ),
            False,
        )
    )
    unknown_diverted = pc.invert(
        pc.fill_null(
            pc.or_kleene(
                pc.equal(source["Diverted"], 0),
                pc.equal(source["Diverted"], 1),
            ),
            False,
        )
    )
    unknown_status = pc.or_kleene(unknown_cancelled, unknown_diverted)
    metrics = {
        "total_flights": source.num_rows,
        "cancelled_flights": _count(cancelled),
        "diverted_flights": _count(diverted),
        "eligible_delay_records": _count(eligible),
        "delayed_flights": _count(delayed),
        "non_delayed_eligible_flights": _count(non_delayed),
        "cancelled_and_diverted_overlap": _count(overlap),
        "unknown_status": _count(unknown_status),
    }
    if metrics["cancelled_and_diverted_overlap"] or metrics["unknown_status"]:
        raise ValueError("Cancellation/diversion flags overlap or contain unknown values.")
    if metrics["eligible_delay_records"] != (
        metrics["delayed_flights"] + metrics["non_delayed_eligible_flights"]
    ):
        raise ValueError(
            "Eligible arrival delays do not reconcile; check for non-finite ArrDelay."
        )
    return metrics


def _as_numeric(
    values: pa.Array, *, lower: float, upper: float
) -> pa.Array:
    cleaned: list[float | None] = []
    for value in values.to_pylist():
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            cleaned.append(None)
        else:
            cleaned.append(float(value))
    return pa.array(cleaned, type=pa.float64())


def _category_values(values: pa.Array) -> pa.Array:
    categories = []
    for value in values.to_pylist():
        normalized = value.strip() if isinstance(value, str) else ""
        categories.append(normalized or MISSING_CATEGORY)
    return pa.array(categories, type=pa.string())


def _training_median(values: pa.Array, training_mask: pa.Array, name: str) -> float:
    training_values = pc.filter(values, training_mask)
    quantile = pc.quantile(training_values, q=0.5, interpolation="linear")
    median = quantile[0].as_py() if len(quantile) else None
    if median is None or not math.isfinite(median):
        raise ValueError(
            f"Cannot impute {name}: training partition has no valid values."
        )
    return float(median)


def _split_name(day: date) -> str:
    if day <= TRAIN_END:
        return "train"
    if day <= VALIDATION_END:
        return "validation"
    return "test"


def build_feature_table(
    source: pa.Table,
) -> tuple[pa.Table, dict[str, Any]]:
    """Create eligible, split, imputed features and a leakage-free target."""
    _validate_source_schema(source.schema)
    metrics = _source_metrics(source)
    dates = pc.cast(source["FlightDate"], pa.date32())
    date_values = dates.to_pylist()
    if any(value is None for value in date_values):
        raise ValueError("FlightDate contains null values; refusing to split rows.")
    if any(value.year != 2024 or value.month != 1 for value in date_values):
        raise ValueError("Input must contain only dates from January 2024.")
    if set(date_values) != {
        date(2024, 1, day)
        for day in range(1, 32)
    }:
        raise ValueError("Expected complete daily coverage for January 2024.")

    cancelled = pc.equal(source["Cancelled"], 0)
    not_diverted = pc.equal(source["Diverted"], 0)
    eligible = pc.and_kleene(
        pc.and_kleene(cancelled, not_diverted),
        pc.is_valid(source["ArrDelay"]),
    )
    eligible_source = pc.filter(source, eligible)
    eligible_dates = pc.filter(dates, eligible)
    eligible_date_values = eligible_dates.to_pylist()
    split_values = [_split_name(value) for value in eligible_date_values]
    training_mask = pa.array(
        [name == "train" for name in split_values], type=pa.bool_()
    )

    month = pc.cast(pc.month(eligible_dates), pa.int8())
    day_of_month = pc.cast(pc.day(eligible_dates), pa.int8())
    day_of_week = pc.cast(
        pc.day_of_week(
            eligible_dates, week_start=1, count_from_zero=True
        ),
        pa.int8(),
    )
    departure_minutes = parse_scheduled_hhmm(
        pc.filter(source["CRSDepTime"], eligible)
    )
    arrival_minutes = parse_scheduled_hhmm(
        pc.filter(source["CRSArrTime"], eligible)
    )
    dep_sin, dep_cos = _cyclic_time_features(departure_minutes)
    arr_sin, arr_cos = _cyclic_time_features(arrival_minutes)

    numeric_values: dict[str, pa.Array] = {
        "month": pa.array(month),
        "day_of_month": pa.array(day_of_month),
        "day_of_week": pa.array(day_of_week),
        "scheduled_departure_sin": dep_sin,
        "scheduled_departure_cos": dep_cos,
        "scheduled_arrival_sin": arr_sin,
        "scheduled_arrival_cos": arr_cos,
        "scheduled_elapsed_time_minutes": _as_numeric(
            eligible_source["CRSElapsedTime"],
            lower=0,
            upper=2_000,
        ),
        "distance_miles": _as_numeric(
            eligible_source["Distance"], lower=0, upper=20_000
        ),
    }
    # Date components and categorical dimensions are all available before departure.
    categories = {
        name: _category_values(eligible_source[name])
        for name in CATEGORICAL_FEATURES
    }

    imputation_medians = {
        name: _training_median(values, training_mask, name)
        for name, values in numeric_values.items()
    }
    feature_arrays: dict[str, pa.Array] = dict(categories)
    for name in NUMERIC_FEATURES:
        values = numeric_values[name]
        feature_arrays[name] = pc.fill_null(values, imputation_medians[name])
        feature_arrays[f"is_missing_{name}"] = pc.cast(
            pc.is_null(values), pa.int8()
        )

    target = pc.cast(pc.greater(eligible_source["ArrDelay"], 15), pa.int8())
    output_arrays = [
        eligible_dates,
        pa.array(split_values, type=pa.string()),
        target,
        *(feature_arrays[name] for name in FEATURE_ALLOWLIST),
    ]
    output_names = [
        FLIGHT_DATE_COLUMN,
        SPLIT_COLUMN,
        TARGET_COLUMN,
        *FEATURE_ALLOWLIST,
    ]
    result = pa.Table.from_arrays(output_arrays, names=output_names)
    if result.num_rows != metrics["eligible_delay_records"]:
        raise ValueError(
            "Feature generation dropped eligible records: "
            f"{result.num_rows} != {metrics['eligible_delay_records']}."
        )
    if result.column_names[3:] != list(FEATURE_ALLOWLIST):
        raise ValueError("Output feature columns do not match the feature allowlist.")
    if set(result.column_names) & (LEAKAGE_DENYLIST - {TARGET_COLUMN}):
        raise ValueError("A prohibited leakage field appears in the output.")

    split_counts: dict[str, dict[str, int]] = {}
    for name in ("train", "validation", "test"):
        mask = pc.equal(result[SPLIT_COLUMN], name)
        subset = pc.filter(result, mask)
        split_counts[name] = {
            "rows": subset.num_rows,
            "delayed": _count(pc.equal(subset[TARGET_COLUMN], 1)),
            "non_delayed": _count(pc.equal(subset[TARGET_COLUMN], 0)),
            "start_date": min(subset[FLIGHT_DATE_COLUMN].to_pylist()).isoformat(),
            "end_date": max(subset[FLIGHT_DATE_COLUMN].to_pylist()).isoformat(),
        }
    if not (
        split_counts["train"]["end_date"]
        < split_counts["validation"]["start_date"]
        < split_counts["test"]["start_date"]
    ):
        raise ValueError("Chronological train/validation/test partitions overlap.")

    summary = {
        "source_metrics": metrics,
        "eligible_rows": result.num_rows,
        "delayed_rows": _count(pc.equal(result[TARGET_COLUMN], 1)),
        "non_delayed_rows": _count(pc.equal(result[TARGET_COLUMN], 0)),
        "split_counts": split_counts,
        "imputation_medians_fit_on_train_only": imputation_medians,
        "feature_allowlist": list(FEATURE_ALLOWLIST),
    }
    return result, summary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_parquet(table: pa.Table, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=["Reporting_Airline", "Origin", "Dest", "split"],
            row_group_size=ROW_GROUP_SIZE,
            write_statistics=True,
        )
        temporary.replace(path)
    except (OSError, pa.ArrowException):
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def run_feature_preparation(
    input_path: Path = DEFAULT_INPUT_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
) -> dict[str, Any]:
    """Validate the BTS population and write the feature table and manifest."""
    if not input_path.is_file():
        raise FileNotFoundError(f"BTS Parquet dataset not found: {input_path}")
    source = pq.read_table(input_path, columns=list(SOURCE_COLUMNS))
    features, summary = build_feature_table(source)
    for name, expected in EXPECTED_METRICS.items():
        actual = summary["source_metrics"][name]
        if actual != expected:
            raise ValueError(
                f"Source {name} mismatch: expected {expected:,}, found {actual:,}."
            )

    output_directory.mkdir(parents=True, exist_ok=True)
    dataset_path = output_directory / DEFAULT_DATASET_NAME
    manifest_path = output_directory / DEFAULT_MANIFEST_NAME
    manifest = {
        "input_dataset": input_path.name,
        "input_sha256": _sha256_file(input_path),
        "target": {
            "column": TARGET_COLUMN,
            "definition": "1 when ArrDelay > 15 minutes; otherwise 0.",
            "eligible_rows": summary["eligible_rows"],
            "delayed_rows": summary["delayed_rows"],
            "non_delayed_rows": summary["non_delayed_rows"],
        },
        "feature_allowlist": summary["feature_allowlist"],
        "leakage_denylist": sorted(LEAKAGE_DENYLIST),
        "categorical_missing_value": MISSING_CATEGORY,
        "numeric_imputation": {
            "strategy": "training-partition median",
            "fit_partition": "train",
            "medians": summary["imputation_medians_fit_on_train_only"],
            "numeric_missing_indicators": list(MISSING_INDICATOR_FEATURES),
        },
        "split_strategy": {
            "type": "chronological calendar-date holdout",
            "train_end_inclusive": TRAIN_END.isoformat(),
            "validation_start": date(2024, 1, 22).isoformat(),
            "validation_end_inclusive": VALIDATION_END.isoformat(),
            "test_start": date(2024, 1, 27).isoformat(),
            "limitations": (
                "All partitions are from January 2024. This within-month "
                "holdout does not establish generalization across seasons or years."
            ),
            "counts": summary["split_counts"],
        },
        "source_metrics": summary["source_metrics"],
        "rows_written": features.num_rows,
    }
    _atomic_write_parquet(features, dataset_path)
    _atomic_write_json(manifest, manifest_path)
    return {
        **summary,
        "dataset_path": str(dataset_path),
        "manifest_path": str(manifest_path),
    }


def main(argv: list[str] | None = None) -> int:
    """Run the standalone, non-training ML feature-preparation pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        result = run_feature_preparation(
            args.input.expanduser(), args.output_dir.expanduser()
        )
        print(f"Feature dataset: {result['dataset_path']}")
        print(f"Manifest: {result['manifest_path']}")
        print(
            "Eligible rows: "
            f"{result['eligible_rows']:,} "
            f"(delayed {result['delayed_rows']:,}; "
            f"non-delayed {result['non_delayed_rows']:,})"
        )
        for name, counts in result["split_counts"].items():
            print(
                f"{name}: {counts['rows']:,} rows, "
                f"{counts['delayed']:,} delayed, "
                f"{counts['non_delayed']:,} non-delayed "
                f"({counts['start_date']} to {counts['end_date']})"
            )
        return 0
    except (OSError, ValueError, pa.ArrowException) as exc:
        print(f"ML feature preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
