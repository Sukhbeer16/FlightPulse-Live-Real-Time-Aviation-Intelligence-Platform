"""Build a leakage-safe January-February 2024 BTS feature dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    FLIGHT_DATE_COLUMN,
    LEAKAGE_DENYLIST,
    MISSING_CATEGORY,
    MISSING_INDICATOR_FEATURES,
    NUMERIC_FEATURES,
    SOURCE_COLUMNS,
    SPLIT_COLUMN,
    TARGET_COLUMN,
    _as_numeric,
    _category_values,
    _count,
    _cyclic_time_features,
    _source_metrics,
    _validate_source_schema,
    parse_scheduled_hhmm,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUTS = (
    (1, ROOT / "data" / "processed" / "bts_ontime_2024_01.parquet"),
    (2, ROOT / "data" / "processed" / "monthly" / "bts_ontime_2024_02.parquet"),
)
OUTPUT_PATH = ROOT / "data" / "processed" / "ml" / "flight_delay_features_2024_01_02.parquet"
OUTPUT_MANIFEST = (
    ROOT / "data" / "processed" / "ml" / "feature_manifest_2024_01_02.json"
)
BATCH_SIZE = 50_000
ROW_GROUP_SIZE = 50_000
TRAIN_END = date(2024, 2, 11)
VALIDATION_END = date(2024, 2, 20)
SPLIT_BOUNDARIES = {
    1: (date(2024, 1, 1), date(2024, 1, 31)),
    2: (date(2024, 2, 1), date(2024, 2, 29)),
}

EXPECTED_SOURCE_METRICS = {
    "total_flights": 1_066_492,
    "cancelled_flights": 23_391,
    "diverted_flights": 2_462,
    "eligible_delay_records": 1_040_639,
    "delayed_flights": 201_297,
    "non_delayed_eligible_flights": 839_342,
}
EXPECTED_PARTITION_METRICS = {
    "train": {"rows": 716_676, "delayed": 150_800, "non_delayed": 565_876},
    "validation": {"rows": 159_176, "delayed": 26_526, "non_delayed": 132_650},
    "test": {"rows": 164_787, "delayed": 23_971, "non_delayed": 140_816},
}
PRESERVED_ARTIFACTS = (
    ROOT / "data" / "processed" / "ml" / "flight_delay_features.parquet",
    ROOT / "data" / "processed" / "ml" / "feature_manifest.json",
    *(ROOT / "data" / "processed" / "analytics").glob("*.parquet"),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_for_date(flight_date: date) -> str:
    if flight_date <= TRAIN_END:
        return "train"
    if flight_date <= VALIDATION_END:
        return "validation"
    return "test"


def _eligible_mask(source: pa.Table) -> pa.Array:
    operating = pc.and_kleene(
        pc.equal(source["Cancelled"], 0),
        pc.equal(source["Diverted"], 0),
    )
    return pc.and_kleene(operating, pc.is_valid(source["ArrDelay"]))


def _feature_components(
    source: pa.Table,
) -> tuple[pa.Table, pa.Array, list[str], dict[str, pa.Array]]:
    eligible_mask = _eligible_mask(source)
    eligible = pc.filter(source, eligible_mask)
    dates = pc.cast(pc.filter(source["FlightDate"], eligible_mask), pa.date32())
    date_values = dates.to_pylist()
    if any(value is None for value in date_values):
        raise ValueError("Eligible flight has a null FlightDate.")
    split_names = [_split_for_date(value) for value in date_values]

    month = pc.cast(pc.month(dates), pa.int8())
    day_of_month = pc.cast(pc.day(dates), pa.int8())
    day_of_week = pc.cast(
        pc.day_of_week(dates, week_start=1, count_from_zero=True),
        pa.int8(),
    )
    departure_minutes = parse_scheduled_hhmm(eligible["CRSDepTime"])
    arrival_minutes = parse_scheduled_hhmm(eligible["CRSArrTime"])
    departure_sin, departure_cos = _cyclic_time_features(departure_minutes)
    arrival_sin, arrival_cos = _cyclic_time_features(arrival_minutes)
    numeric = {
        "month": pa.array(month),
        "day_of_month": pa.array(day_of_month),
        "day_of_week": pa.array(day_of_week),
        "scheduled_departure_sin": departure_sin,
        "scheduled_departure_cos": departure_cos,
        "scheduled_arrival_sin": arrival_sin,
        "scheduled_arrival_cos": arrival_cos,
        "scheduled_elapsed_time_minutes": _as_numeric(
            eligible["CRSElapsedTime"], lower=0, upper=2_000
        ),
        "distance_miles": _as_numeric(
            eligible["Distance"], lower=0, upper=20_000
        ),
    }
    return eligible, dates, split_names, numeric


def _make_feature_table(source: pa.Table, medians: Mapping[str, float]) -> pa.Table:
    eligible, dates, split_names, numeric = _feature_components(source)
    categories = {
        name: _category_values(eligible[name]) for name in CATEGORICAL_FEATURES
    }
    features: dict[str, pa.Array] = dict(categories)
    for name in NUMERIC_FEATURES:
        values = numeric[name]
        features[name] = pc.fill_null(values, medians[name])
        features[f"is_missing_{name}"] = pc.cast(pc.is_null(values), pa.int8())

    target = pc.cast(pc.greater(eligible["ArrDelay"], 15), pa.int8())
    result = pa.Table.from_arrays(
        [
            dates,
            pa.array(split_names, type=pa.string()),
            target,
            *(features[name] for name in FEATURE_ALLOWLIST),
        ],
        names=[
            FLIGHT_DATE_COLUMN,
            SPLIT_COLUMN,
            TARGET_COLUMN,
            *FEATURE_ALLOWLIST,
        ],
    )
    if result.column_names[3:] != list(FEATURE_ALLOWLIST):
        raise ValueError("Combined feature columns do not match the allowlist.")
    if set(result.column_names) & (LEAKAGE_DENYLIST - {TARGET_COLUMN}):
        raise ValueError("A prohibited outcome/leakage field entered the output.")
    if result[TARGET_COLUMN].null_count:
        raise ValueError("Generated target contains null values.")
    return result


def _date_set(ranges: Mapping[int, tuple[date, date]]) -> dict[int, set[date]]:
    return {
        month: {
            date.fromordinal(day)
            for day in range(start.toordinal(), end.toordinal() + 1)
        }
        for month, (start, end) in ranges.items()
    }


def _preserved_hashes() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): _sha256_file(path)
        for path in PRESERVED_ARTIFACTS
        if path.is_file()
    }


def _increment(metrics: Counter[str], values: Mapping[str, int]) -> None:
    metrics.update(values)


def _scan_and_fit(
    inputs: Sequence[tuple[int, Path]],
    expected_dates: Mapping[int, tuple[date, date]],
) -> tuple[
    dict[str, float],
    dict[str, dict[str, int]],
    dict[str, dict[str, int]],
    dict[str, Any],
    dict[str, str],
]:
    expected_days = _date_set(expected_dates)
    daily: dict[date, Counter[str]] = {}
    source_metrics: Counter[str] = Counter()
    monthly_metrics: dict[str, Counter[str]] = {}
    training_values: dict[str, list[pa.Array]] = {
        name: [] for name in NUMERIC_FEATURES
    }
    common_schema: pa.Schema | None = None
    source_provenance: dict[str, Any] = {}

    for month, path in inputs:
        if month not in expected_days or not path.is_file():
            raise FileNotFoundError(f"Missing BTS source for month {month}: {path}")
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        _validate_source_schema(schema)
        if common_schema is None:
            common_schema = schema
        elif not schema.equals(common_schema, check_metadata=True):
            raise ValueError(f"Parquet schema differs for source month {month}.")

        month_key = f"2024-{month:02d}"
        monthly = monthly_metrics.setdefault(month_key, Counter())
        month_dates: set[date] = set()
        source_provenance[month_key] = {
            "path": path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else str(path.resolve()),
            "sha256": _sha256_file(path),
            "source_rows": parquet.metadata.num_rows,
            "schema_column_count": len(schema),
        }

        for record_batch in parquet.iter_batches(
            batch_size=BATCH_SIZE, columns=list(SOURCE_COLUMNS)
        ):
            source = pa.Table.from_batches([record_batch])
            counts = _source_metrics(source)
            _increment(source_metrics, counts)
            _increment(monthly, counts)

            dates = pc.cast(source["FlightDate"], pa.date32()).to_pylist()
            if any(value is None for value in dates):
                raise ValueError(f"Null FlightDate in source month {month}.")
            for flight_date in dates:
                if flight_date.year != 2024 or flight_date.month != month:
                    raise ValueError(
                        f"Unexpected date {flight_date} in source month {month}."
                    )
                month_dates.add(flight_date)
                day = daily.setdefault(flight_date, Counter())
                day["source_rows"] += 1

            eligible, eligible_dates, split_names, numeric = _feature_components(source)
            targets = pc.greater(eligible["ArrDelay"], 15).to_pylist()
            training_mask = pa.array(
                [name == "train" for name in split_names], type=pa.bool_()
            )
            for flight_date, split, delayed in zip(
                eligible_dates.to_pylist(), split_names, targets
            ):
                day = daily[flight_date]
                day["eligible"] += 1
                day[f"{split}_rows"] += 1
                day[f"{split}_delayed"] += int(bool(delayed))
                day[f"{split}_non_delayed"] += int(not bool(delayed))
                day["delayed"] += int(bool(delayed))
                day["non_delayed"] += int(not bool(delayed))

            for name, values in numeric.items():
                selected = pc.drop_null(pc.filter(values, training_mask))
                if len(selected):
                    training_values[name].append(selected)

        if month_dates != expected_days[month]:
            raise ValueError(
                f"Source month {month} date coverage mismatch: "
                f"expected {min(expected_days[month])}–{max(expected_days[month])} "
                f"({len(expected_days[month])} dates), found "
                f"{len(month_dates)} dates."
            )

    medians: dict[str, float] = {}
    training_rows = sum(
        day["train_rows"] for day in daily.values()
    )
    if not training_rows:
        raise ValueError("No eligible training rows are available for imputation.")
    for name, arrays in training_values.items():
        if not arrays:
            raise ValueError(f"Cannot impute {name}: training data has no values.")
        values = arrays[0] if len(arrays) == 1 else pa.concat_arrays(arrays)
        quantile = pc.quantile(values, q=0.5, interpolation="linear")
        median = quantile[0].as_py() if len(quantile) else None
        if median is None or not math.isfinite(median):
            raise ValueError(f"Cannot calculate a finite training median for {name}.")
        medians[name] = float(median)

    partitions: dict[str, dict[str, int]] = {}
    for split in ("train", "validation", "test"):
        partitions[split] = {
            "rows": sum(day[f"{split}_rows"] for day in daily.values()),
            "delayed": sum(day[f"{split}_delayed"] for day in daily.values()),
            "non_delayed": sum(
                day[f"{split}_non_delayed"] for day in daily.values()
            ),
        }
        dated = sorted(
            flight_date
            for flight_date, day in daily.items()
            if day[f"{split}_rows"]
        )
        partitions[split]["start_date"] = dated[0].isoformat() if dated else None
        partitions[split]["end_date"] = dated[-1].isoformat() if dated else None

    daily_summary = {
        flight_date.isoformat(): {
            "source_rows": day["source_rows"],
            "eligible_rows": day["eligible"],
            "split": _split_for_date(flight_date),
        }
        for flight_date, day in sorted(daily.items())
    }
    monthly_summary = {
        month: dict(counts) for month, counts in sorted(monthly_metrics.items())
    }
    return (
        medians,
        partitions,
        monthly_summary,
        {
            "source": dict(source_metrics),
            "daily": daily_summary,
            "training_rows": training_rows,
            "source_provenance": source_provenance,
        },
        source_provenance,
    )


def _validate_expected(
    source_metrics: Mapping[str, int],
    partitions: Mapping[str, Mapping[str, int]],
    expected_source_metrics: Mapping[str, int] | None,
    expected_partitions: Mapping[str, Mapping[str, int]] | None,
) -> None:
    if expected_source_metrics is not None:
        for name, expected in expected_source_metrics.items():
            actual = source_metrics.get(name, 0)
            if actual != expected:
                raise ValueError(
                    f"Combined source {name} mismatch: expected {expected:,}, "
                    f"found {actual:,}."
                )
    if expected_partitions is not None:
        for split, expected_counts in expected_partitions.items():
            for name, expected in expected_counts.items():
                actual = partitions[split].get(name, 0)
                if actual != expected:
                    raise ValueError(
                        f"{split} {name} mismatch: expected {expected:,}, "
                        f"found {actual:,}."
                    )


def build_combined_feature_dataset(
    inputs: Sequence[tuple[int, Path]] = DEFAULT_INPUTS,
    output_path: Path = OUTPUT_PATH,
    manifest_path: Path = OUTPUT_MANIFEST,
    *,
    expected_dates: Mapping[int, tuple[date, date]] = SPLIT_BOUNDARIES,
    expected_source_metrics: Mapping[str, int] | None = EXPECTED_SOURCE_METRICS,
    expected_partitions: Mapping[str, Mapping[str, int]] | None = EXPECTED_PARTITION_METRICS,
) -> dict[str, Any]:
    """Create the combined feature Parquet and its provenance manifest."""
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(
            "Combined dataset or manifest already exists; refusing to overwrite."
        )
    input_paths = {path.resolve() for _, path in inputs}
    if output_path.resolve() in input_paths or manifest_path.resolve() in input_paths:
        raise ValueError("Output paths must not overwrite BTS source files.")
    if output_path.resolve() == manifest_path.resolve():
        raise ValueError("Dataset and manifest paths must be different.")

    protected_before = _preserved_hashes()
    input_hashes_before = {
        path.resolve(): _sha256_file(path) for _, path in inputs if path.is_file()
    }
    (
        medians,
        partitions,
        monthly_metrics,
        scan_summary,
        source_provenance,
    ) = _scan_and_fit(inputs, expected_dates)
    _validate_expected(
        scan_summary["source"],
        partitions,
        expected_source_metrics,
        expected_partitions,
    )
    total = scan_summary["source"]["total_flights"]
    eligible_total = scan_summary["source"]["eligible_delay_records"]
    delayed_total = scan_summary["source"]["delayed_flights"]
    non_delayed_total = scan_summary["source"]["non_delayed_eligible_flights"]
    if eligible_total != delayed_total + non_delayed_total:
        raise ValueError("Combined eligible target counts do not reconcile.")
    if sum(part["rows"] for part in partitions.values()) != eligible_total:
        raise ValueError("Chronological partition row counts do not reconcile.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_temp = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    manifest_temp = manifest_path.with_name(
        f".{manifest_path.name}.{uuid.uuid4().hex}.tmp"
    )
    writer: pq.ParquetWriter | None = None
    written_partitions: dict[str, Counter[str]] = {
        split: Counter() for split in ("train", "validation", "test")
    }
    written_rows = 0
    try:
        for _, path in inputs:
            parquet = pq.ParquetFile(path)
            for record_batch in parquet.iter_batches(
                batch_size=BATCH_SIZE, columns=list(SOURCE_COLUMNS)
            ):
                table = _make_feature_table(
                    pa.Table.from_batches([record_batch]), medians
                )
                if writer is None:
                    writer = pq.ParquetWriter(
                        output_temp,
                        table.schema,
                        compression="zstd",
                        use_dictionary=[
                            "Reporting_Airline",
                            "Origin",
                            "Dest",
                            SPLIT_COLUMN,
                        ],
                        write_statistics=True,
                    )
                writer.write_table(table, row_group_size=ROW_GROUP_SIZE)
                written_rows += table.num_rows
                for split, target in zip(
                    table[SPLIT_COLUMN].to_pylist(),
                    table[TARGET_COLUMN].to_pylist(),
                ):
                    split_counts = written_partitions[split]
                    split_counts["rows"] += 1
                    split_counts["delayed"] += int(target == 1)
                    split_counts["non_delayed"] += int(target == 0)
        if writer is None:
            raise ValueError("No source records were processed.")
        writer.close()
        writer = None

        if written_rows != eligible_total:
            raise ValueError(
                f"Feature row count mismatch: expected {eligible_total:,}, "
                f"wrote {written_rows:,}."
            )
        for split, expected in partitions.items():
            actual = written_partitions[split]
            for name in ("rows", "delayed", "non_delayed"):
                if actual[name] != expected[name]:
                    raise ValueError(
                        f"Written {split} {name} mismatch: expected "
                        f"{expected[name]:,}, found {actual[name]:,}."
                    )
        if sum(part["delayed"] for part in written_partitions.values()) != delayed_total:
            raise ValueError("Written delayed target count does not match source metrics.")
        if (
            sum(part["non_delayed"] for part in written_partitions.values())
            != non_delayed_total
        ):
            raise ValueError(
                "Written non-delayed target count does not match source metrics."
            )

        source_hashes_after = {
            path.resolve(): _sha256_file(path) for _, path in inputs
        }
        if source_hashes_after != input_hashes_before:
            raise ValueError("An input BTS source changed during feature generation.")
        protected_after = _preserved_hashes()
        if protected_after != protected_before:
            raise ValueError("A January-only or Phase 3.2 protected artifact changed.")

        manifest = {
            "validation_status": "passed",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_dataset": output_path.name,
            "output_sha256": _sha256_file(output_temp),
            "rows_written": written_rows,
            "source_datasets": source_provenance,
            "source_metrics": scan_summary["source"],
            "monthly_metrics": monthly_metrics,
            "target": {
                "column": TARGET_COLUMN,
                "definition": "1 when ArrDelay > 15 minutes; otherwise 0.",
                "eligible_rows": eligible_total,
                "delayed_rows": delayed_total,
                "non_delayed_rows": non_delayed_total,
            },
            "features": {
                "allowlist": list(FEATURE_ALLOWLIST),
                "count": len(FEATURE_ALLOWLIST),
                "categorical": list(CATEGORICAL_FEATURES),
                "numeric": list(NUMERIC_FEATURES),
                "numeric_missing_indicators": list(MISSING_INDICATOR_FEATURES),
                "metadata_columns": [
                    FLIGHT_DATE_COLUMN,
                    SPLIT_COLUMN,
                    TARGET_COLUMN,
                ],
                "leakage_denylist": sorted(LEAKAGE_DENYLIST),
                "categorical_missing_value": MISSING_CATEGORY,
            },
            "numeric_imputation": {
                "strategy": "training-partition median",
                "fit_partition": "train",
                "fit_rows": scan_summary["training_rows"],
                "medians": medians,
            },
            "split_strategy": {
                "type": "chronological calendar-date holdout",
                "boundaries_inclusive": {
                    "train": {
                        "start": min(expected_dates[1][0].isoformat(), expected_dates[2][0].isoformat()),
                        "end": TRAIN_END.isoformat(),
                    },
                    "validation": {
                        "start": (TRAIN_END.fromordinal(TRAIN_END.toordinal() + 1)).isoformat(),
                        "end": VALIDATION_END.isoformat(),
                    },
                    "test": {
                        "start": (VALIDATION_END.fromordinal(VALIDATION_END.toordinal() + 1)).isoformat(),
                        "end": max(expected_dates[1][1].isoformat(), expected_dates[2][1].isoformat()),
                    },
                },
                "counts": partitions,
                "daily_rows_and_partition": scan_summary["daily"],
                "same_calendar_date_stays_in_one_partition": True,
            },
            "preservation_checks": {
                "protected_artifacts_sha256": protected_after,
                "source_checksums_unchanged_during_run": True,
            },
        }
        manifest_temp.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_temp.replace(output_path)
        manifest_temp.replace(manifest_path)
    except (OSError, pa.ArrowException, ValueError):
        if writer is not None:
            writer.close()
        output_temp.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
        raise

    return {
        "dataset_path": str(output_path),
        "manifest_path": str(manifest_path),
        "rows_written": written_rows,
        "delayed_rows": delayed_total,
        "non_delayed_rows": non_delayed_total,
        "source_rows": total,
        "partitions": partitions,
        "feature_allowlist": list(FEATURE_ALLOWLIST),
        "imputation_medians": medians,
        "output_bytes": output_path.stat().st_size,
        "manifest_bytes": manifest_path.stat().st_size,
    }


def main() -> int:
    """Run the combined feature preparation pipeline without model training."""
    try:
        result = build_combined_feature_dataset()
        print(f"Feature dataset: {result['dataset_path']}")
        print(f"Manifest: {result['manifest_path']}")
        print(
            f"Eligible rows: {result['rows_written']:,}; "
            f"delayed {result['delayed_rows']:,}; "
            f"non-delayed {result['non_delayed_rows']:,}"
        )
        for split, counts in result["partitions"].items():
            print(
                f"{split}: {counts['rows']:,} rows, {counts['delayed']:,} delayed, "
                f"{counts['non_delayed']:,} non-delayed "
                f"({counts['start_date']} to {counts['end_date']})"
            )
        return 0
    except (OSError, ValueError, pa.ArrowException) as exc:
        print(f"Combined ML feature preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
