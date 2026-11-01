"""Build annual leakage-safe features using bounded-memory Parquet batches."""

from __future__ import annotations

import json
import hashlib
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipelines.ml.feature_dataset import (
    CATEGORICAL_FEATURES,
    FEATURE_ALLOWLIST,
    FLIGHT_DATE_COLUMN,
    LEAKAGE_DENYLIST,
    MISSING_CATEGORY,
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
INPUT_PATH = ROOT / "data" / "processed" / "bts_ontime_2024.parquet"
INPUT_MANIFEST = ROOT / "data" / "processed" / "bts_ontime_2024_manifest.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "ml" / "flight_delay_features_2024.parquet"
OUTPUT_MANIFEST = (
    ROOT / "data" / "processed" / "ml" / "feature_manifest_2024.json"
)
BATCH_SIZE = 50_000


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _month_split(months: list[int]) -> dict[int, str]:
    if len(months) < 3:
        raise ValueError(
            "At least three validated months are required for chronological "
            "train/validation/test partitions."
        )
    train_count = max(1, round(len(months) * 2 / 3))
    validation_count = max(1, round(len(months) / 6))
    if train_count + validation_count >= len(months):
        train_count = len(months) - 2
        validation_count = 1
    assignments = {}
    for index, month in enumerate(months):
        if index < train_count:
            assignments[month] = "train"
        elif index < train_count + validation_count:
            assignments[month] = "validation"
        else:
            assignments[month] = "test"
    return assignments


def _is_eligible(source: pa.Table) -> pa.Array:
    operating = pc.and_kleene(
        pc.equal(source["Cancelled"], 0),
        pc.equal(source["Diverted"], 0),
    )
    return pc.and_kleene(operating, pc.is_valid(source["ArrDelay"]))


def _feature_components(
    source: pa.Table, split_by_month: dict[int, str]
) -> tuple[pa.Table, pa.Array, list[str], dict[str, pa.Array]]:
    eligible_mask = _is_eligible(source)
    eligible = pc.filter(source, eligible_mask)
    dates = pc.cast(pc.filter(source["FlightDate"], eligible_mask), pa.date32())
    date_values = dates.to_pylist()
    months = [value.month for value in date_values]
    split_names = [split_by_month[value] for value in months]

    month = pc.cast(pc.month(dates), pa.int8())
    day_of_month = pc.cast(pc.day(dates), pa.int8())
    day_of_week = pc.cast(
        pc.day_of_week(dates, week_start=1, count_from_zero=True),
        pa.int8(),
    )
    dep_minutes = parse_scheduled_hhmm(eligible["CRSDepTime"])
    arr_minutes = parse_scheduled_hhmm(eligible["CRSArrTime"])
    dep_sin, dep_cos = _cyclic_time_features(dep_minutes)
    arr_sin, arr_cos = _cyclic_time_features(arr_minutes)
    numeric = {
        "month": pa.array(month),
        "day_of_month": pa.array(day_of_month),
        "day_of_week": pa.array(day_of_week),
        "scheduled_departure_sin": dep_sin,
        "scheduled_departure_cos": dep_cos,
        "scheduled_arrival_sin": arr_sin,
        "scheduled_arrival_cos": arr_cos,
        "scheduled_elapsed_time_minutes": _as_numeric(
            eligible["CRSElapsedTime"], lower=0, upper=2_000
        ),
        "distance_miles": _as_numeric(eligible["Distance"], lower=0, upper=20_000),
    }
    return eligible, dates, split_names, numeric


def _collect_training_values(
    input_file: pq.ParquetFile,
    split_by_month: dict[int, str],
) -> tuple[dict[str, list[np.ndarray]], dict[str, dict[str, int]], dict[str, int]]:
    training_values: dict[str, list[np.ndarray]] = {
        name: [] for name in NUMERIC_FEATURES
    }
    month_counts: dict[str, dict[str, int]] = {
        f"2024-{month:02d}": {"rows": 0, "delayed": 0, "non_delayed": 0}
        for month in split_by_month
    }
    source_totals: dict[str, int] = {}

    for batch in input_file.iter_batches(
        batch_size=BATCH_SIZE, columns=list(SOURCE_COLUMNS)
    ):
        source = pa.Table.from_batches([batch])
        metrics = _source_metrics(source)
        for name, value in metrics.items():
            source_totals[name] = source_totals.get(name, 0) + value
        _, dates, split_names, numeric = _feature_components(source, split_by_month)
        eligible_source = pc.filter(source, _is_eligible(source))
        target = pc.greater(eligible_source["ArrDelay"], 15)
        date_months = [value.month for value in dates.to_pylist()]
        for index, month in enumerate(date_months):
            entry = month_counts[f"2024-{month:02d}"]
            entry["rows"] += 1
            entry["delayed"] += int(target[index].as_py())
            entry["non_delayed"] += int(not target[index].as_py())

        training_mask = pa.array(
            [split == "train" for split in split_names], type=pa.bool_()
        )
        for name, values in numeric.items():
            selected = pc.drop_null(pc.filter(values, training_mask))
            if len(selected):
                training_values[name].append(
                    np.asarray(selected.to_numpy(zero_copy_only=False), dtype=np.float64)
                )
    return training_values, month_counts, source_totals


def _make_feature_table(
    source: pa.Table,
    split_by_month: dict[int, str],
    medians: dict[str, float],
) -> pa.Table:
    eligible, dates, split_names, numeric = _feature_components(source, split_by_month)
    categories = {
        name: _category_values(eligible[name]) for name in CATEGORICAL_FEATURES
    }
    features: dict[str, pa.Array] = dict(categories)
    for name in NUMERIC_FEATURES:
        values = numeric[name]
        features[name] = pc.fill_null(values, medians[name])
        features[f"is_missing_{name}"] = pc.cast(pc.is_null(values), pa.int8())

    target = pc.cast(pc.greater(eligible["ArrDelay"], 15), pa.int8())
    table = pa.Table.from_arrays(
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
    if table.column_names[3:] != list(FEATURE_ALLOWLIST):
        raise ValueError("Annual feature output does not match the feature allowlist.")
    if set(table.column_names) & (LEAKAGE_DENYLIST - {TARGET_COLUMN}):
        raise ValueError("A prohibited outcome/leakage column entered the feature set.")
    return table


def build_annual_feature_dataset() -> dict[str, Any]:
    """Create an annual feature Parquet and its reproducibility manifest."""
    if not INPUT_PATH.is_file() or not INPUT_MANIFEST.is_file():
        raise FileNotFoundError(
            "The validated annual BTS Parquet and manifest must exist before "
            "annual ML feature preparation."
        )
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    if OUTPUT_PATH.exists() or OUTPUT_MANIFEST.exists():
        if not (OUTPUT_PATH.is_file() and OUTPUT_MANIFEST.is_file()):
            raise FileExistsError(
                "Annual ML dataset and manifest must both exist to reuse prior outputs."
            )
        existing = json.loads(OUTPUT_MANIFEST.read_text(encoding="utf-8"))
        parquet = pq.ParquetFile(OUTPUT_PATH)
        if (
            existing.get("validation_status") != "passed"
            or existing.get("source_dataset_sha256") != _sha256_file(INPUT_PATH)
            or existing.get("output_sha256") != _sha256_file(OUTPUT_PATH)
            or existing.get("output_rows") != parquet.metadata.num_rows
            or existing.get("feature_allowlist") != list(FEATURE_ALLOWLIST)
        ):
            raise ValueError("Existing annual ML outputs failed integrity checks.")
        return existing
    months = sorted(manifest.get("included_months", []))
    split_by_month = _month_split(months)
    input_file = pq.ParquetFile(INPUT_PATH)
    _validate_source_schema(input_file.schema_arrow)

    training_values, month_counts, source_totals = _collect_training_values(
        input_file, split_by_month
    )
    medians = {}
    for name, batches in training_values.items():
        if not batches:
            raise ValueError(f"No training values available to impute {name}.")
        medians[name] = float(np.median(np.concatenate(batches)))
        if not math.isfinite(medians[name]):
            raise ValueError(f"Training median for {name} is not finite.")
    del training_values

    expected_eligible = source_totals["eligible_delay_records"]
    if expected_eligible != (
        source_totals["delayed_flights"]
        + source_totals["non_delayed_eligible_flights"]
    ):
        raise ValueError("Annual eligible target classes do not reconcile.")
    if source_totals["total_flights"] != (
        source_totals["cancelled_flights"]
        + source_totals["diverted_flights"]
        + expected_eligible
    ):
        raise ValueError("Annual cancellation/diversion/eligibility counts do not reconcile.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".part")
    if temporary_path.exists():
        raise FileExistsError(f"Refusing to overwrite incomplete output: {temporary_path}")
    writer: pq.ParquetWriter | None = None
    split_counts: dict[str, dict[str, Any]] = {
        name: {
            "rows": 0,
            "delayed": 0,
            "non_delayed": 0,
            "start_date": None,
            "end_date": None,
        }
        for name in ("train", "validation", "test")
    }
    output_rows = 0
    try:
        for batch in input_file.iter_batches(
            batch_size=BATCH_SIZE, columns=list(SOURCE_COLUMNS)
        ):
            table = _make_feature_table(
                pa.Table.from_batches([batch]), split_by_month, medians
            )
            if table.num_rows == 0:
                continue
            if writer is None:
                writer = pq.ParquetWriter(
                    temporary_path, table.schema, compression="zstd"
                )
            writer.write_table(table, row_group_size=BATCH_SIZE)
            output_rows += table.num_rows
            for name in split_counts:
                mask = pc.equal(table[SPLIT_COLUMN], name)
                count = _count(mask)
                if not count:
                    continue
                subset = pc.filter(table, mask)
                dates = subset[FLIGHT_DATE_COLUMN].to_pylist()
                entry = split_counts[name]
                entry["rows"] += count
                entry["delayed"] += _count(pc.equal(subset[TARGET_COLUMN], 1))
                entry["non_delayed"] += _count(pc.equal(subset[TARGET_COLUMN], 0))
                first, last = min(dates).isoformat(), max(dates).isoformat()
                entry["start_date"] = min(entry["start_date"] or first, first)
                entry["end_date"] = max(entry["end_date"] or last, last)
        if writer is None:
            raise ValueError("Annual source produced no eligible ML records.")
        writer.close()
        writer = None
        if output_rows != expected_eligible:
            raise ValueError(
                f"Feature row count mismatch: {output_rows} != {expected_eligible}."
            )
        for name in ("train", "validation", "test"):
            if not split_counts[name]["rows"]:
                raise ValueError(f"Chronological {name} partition is empty.")
        if not (
            split_counts["train"]["end_date"]
            < split_counts["validation"]["start_date"]
            and split_counts["validation"]["end_date"]
            < split_counts["test"]["start_date"]
        ):
            raise ValueError("Annual chronological partitions overlap.")

        parquet = pq.ParquetFile(temporary_path)
        if parquet.metadata.num_rows != expected_eligible:
            raise ValueError("Written annual ML output row count is incorrect.")
        for row in parquet.iter_batches(batch_size=BATCH_SIZE):
            if row.schema.names[3:] != list(FEATURE_ALLOWLIST):
                raise ValueError(
                    "Written annual output contains unexpected feature columns."
                )
            if row.column("target_arr_delay_gt_15").null_count:
                raise ValueError("Written annual output contains null targets.")
            if any(row.column(name).null_count for name in FEATURE_ALLOWLIST):
                raise ValueError("Written annual output contains null feature values.")
        os.replace(temporary_path, OUTPUT_PATH)
    except Exception:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
        raise

    parquet = pq.ParquetFile(OUTPUT_PATH)
    for stats in month_counts.values():
        rows = stats["rows"]
        stats["delayed_rate"] = stats["delayed"] / rows if rows else None

    output_manifest = {
        "source_dataset": str(INPUT_PATH.relative_to(ROOT)),
        "source_dataset_sha256": _sha256_file(INPUT_PATH),
        "source_dataset_rows": source_totals["total_flights"],
        "eligible_rows": expected_eligible,
        "delayed_rows": source_totals["delayed_flights"],
        "non_delayed_rows": source_totals["non_delayed_eligible_flights"],
        "null_arrival_delay_rows": (
            source_totals["total_flights"]
            - source_totals["cancelled_flights"]
            - source_totals["diverted_flights"]
            - expected_eligible
        ),
        "cancelled_rows": source_totals["cancelled_flights"],
        "diverted_rows": source_totals["diverted_flights"],
        "included_months": months,
        "missing_months": manifest.get("missing_months", []),
        "month_distribution": dict(sorted(month_counts.items())),
        "split_months": {
            name: [month for month, split in split_by_month.items() if split == name]
            for name in ("train", "validation", "test")
        },
        "split_counts": split_counts,
        "split_strategy": (
            "Chronological, whole-month partitions. Approximately 2/3 of the "
            "included months are training, 1/6 validation, and the remaining "
            "months final test; no calendar date is split between partitions."
        ),
        "feature_allowlist": list(FEATURE_ALLOWLIST),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "numeric_features": list(NUMERIC_FEATURES),
        "leakage_denylist": sorted(LEAKAGE_DENYLIST),
        "training_numeric_medians": medians,
        "output_path": str(OUTPUT_PATH.relative_to(ROOT)),
        "output_rows": parquet.metadata.num_rows,
        "output_sha256": _sha256_file(OUTPUT_PATH),
        "output_schema": str(parquet.schema_arrow),
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "training_status": "not_started",
        "validation_status": "passed",
        "seasonal_generalization_claim": False,
    }
    OUTPUT_MANIFEST.write_text(
        json.dumps(output_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return output_manifest
