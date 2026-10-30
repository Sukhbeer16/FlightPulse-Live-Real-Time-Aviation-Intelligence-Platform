"""Focused tests for BTS validation, cleaning, and feature behavior."""

import io
import csv
from email.message import Message
import json
from pathlib import Path
import urllib.error
import zipfile

import pandas as pd
import pytest

from pipelines.ingestion import bts_ingestion
from pipelines.ingestion.bts_ingestion import process_bts_csv
from pipelines.ingestion.data_cleaning import clean_dataframe
from pipelines.ingestion.data_validation import validate_csv
from pipelines.ingestion.feature_creation import (
    ACTUAL_OUTCOME_COLUMNS,
    create_features,
    create_training_frame,
)


def _bts_archive(member_name: str | None = None) -> bytes:
    """Build a small ZIP fixture with the expected BTS member name."""
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            member_name or bts_ingestion.EXPECTED_ARCHIVE_CSV,
            "FlightDate\n2024-01-01\n",
        )
    return content.getvalue()


class _FakeResponse:
    """Minimal streaming HTTP response with optional connection interruption."""

    def __init__(
        self,
        body: bytes,
        status: int,
        headers: dict[str, str],
        interrupt_after: int | None = None,
    ) -> None:
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = headers
        self.interrupt_after = interrupt_after
        self.delivered = 0
        self.interrupted = False

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.body.close()

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if (
            self.interrupt_after is not None
            and not self.interrupted
            and self.delivered >= self.interrupt_after
        ):
            self.interrupted = True
            raise bts_ingestion.urllib.error.URLError("simulated interruption")
        if self.interrupt_after is not None and not self.interrupted:
            size = min(size, self.interrupt_after - self.delivered)
        block = self.body.read(size)
        self.delivered += len(block)
        return block


def _queue_http_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[_FakeResponse | urllib.error.HTTPError],
) -> list[dict[str, str]]:
    """Mock urlopen with ordered responses and capture request headers."""
    requests: list[dict[str, str]] = []
    pending = iter(responses)

    def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        del timeout
        requests.append(dict(request.headers))  # type: ignore[attr-defined]
        response = next(pending)
        if isinstance(response, urllib.error.HTTPError):
            raise response
        return response

    monkeypatch.setattr(bts_ingestion.urllib.request, "urlopen", fake_urlopen)
    return requests


def _http_416(total: int) -> urllib.error.HTTPError:
    headers = Message()
    headers["Content-Range"] = f"bytes */{total}"
    return bts_ingestion.urllib.error.HTTPError(
        bts_ingestion.SOURCE_URL,
        416,
        "Range Not Satisfiable",
        headers,
        io.BytesIO(),
    )
def _base_rows() -> pd.DataFrame:
    """Return small synthetic rows for isolated unit tests only."""
    return pd.DataFrame(
        [
            {
                "FlightDate": "2024-01-08",
                "Reporting_Airline": "AA",
                "Origin": "JFK",
                "Dest": "LAX",
                "CRSDepTime": "0815",
                "DepTime": "0820",
                "DepDelay": "5",
                "CRSArrTime": "1130",
                "ArrTime": "1140",
                "ArrDelay": "10",
                "Cancelled": "0",
                "Diverted": "0",
                "Distance": "2475",
                "CRSElapsedTime": "375",
            },
            {
                "FlightDate": "2024-01-09",
                "Reporting_Airline": "DL",
                "Origin": "ATL",
                "Dest": "ORD",
                "CRSDepTime": "2400",
                "DepTime": "0010",
                "DepDelay": "10",
                "CRSArrTime": "0150",
                "ArrTime": "0210",
                "ArrDelay": "20",
                "Cancelled": "0",
                "Diverted": "0",
                "Distance": "606",
                "CRSElapsedTime": "110",
            },
        ]
    )


def test_validate_csv_reports_schema_nulls_duplicates_and_invalid_values(
    tmp_path: Path,
) -> None:
    """CSV checks count missing values, numeric/range errors, and duplicates."""
    rows = _base_rows()
    rows.loc[0, "DepDelay"] = None
    rows.loc[1, "CRSDepTime"] = "1260"
    rows.loc[1, "Distance"] = "-5"
    path = tmp_path / "bts.csv"
    pd.concat([rows, rows.iloc[[0]]], ignore_index=True).to_csv(path, index=False)

    report = validate_csv(path, chunksize=1)

    assert report["total_rows"] == 3
    assert report["duplicate_rows"] == 1
    assert report["missing_values"]["DepDelay"] == 2
    assert report["invalid_values"]["CRSDepTime"] == 1
    assert report["invalid_values"]["Distance"] == 1
    assert report["invalid_date_rows"] == 0


def test_validate_csv_rejects_missing_required_columns(tmp_path: Path) -> None:
    """A file without target/identity contract fields fails explicitly."""
    path = tmp_path / "not_bts.csv"
    pd.DataFrame({"FlightDate": ["2024-01-01"]}).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing required BTS columns"):
        validate_csv(path)


def test_validate_csv_counts_invalid_and_out_of_scope_dates(tmp_path: Path) -> None:
    """Date parsing and the January-only scope are checked separately."""
    rows = _base_rows()
    rows.loc[0, "FlightDate"] = "not-a-date"
    rows.loc[1, "FlightDate"] = "2024-02-01"
    path = tmp_path / "date-issues.csv"
    rows.to_csv(path, index=False)

    report = validate_csv(path, chunksize=1)

    assert report["invalid_date_rows"] == 1
    assert report["out_of_scope_date_rows"] == 1


def test_cleaning_filters_dates_identity_and_duplicates_without_imputation() -> None:
    """Cleaning keeps in-period unique flights and leaves missing data null."""
    rows = _base_rows()
    rows.loc[0, "ArrDelay"] = None
    rows.loc[0, "Distance"] = "-5"
    rows.loc[0, "CRSDepTime"] = "1260"
    rows.loc[1, "FlightDate"] = "2024-02-01"
    rows.loc[1, "Origin"] = ""
    frame = pd.concat([rows.iloc[[0]], rows.iloc[[0]], rows.iloc[[1]]], ignore_index=True)

    cleaned = clean_dataframe(frame)

    assert len(cleaned) == 1
    assert pd.isna(cleaned.loc[0, "ArrDelay"])
    assert pd.isna(cleaned.loc[0, "Distance"])
    assert pd.isna(cleaned.loc[0, "CRSDepTime"])
    assert pd.isna(cleaned.loc[0, "departure_hour"])
    assert pd.isna(cleaned.loc[0, "is_delayed"])
    assert cleaned.loc[0, "is_trainable"] == False


def test_features_and_target_use_scheduled_time_and_exclude_cancelled_diverted() -> None:
    """Labels use the 15-minute threshold and null non-operating outcomes."""
    rows = _base_rows()
    rows.loc[0, "ArrDelay"] = "15"
    rows.loc[1, "ArrDelay"] = "16"
    cancelled = rows.iloc[[0]].copy()
    cancelled.loc[:, "Cancelled"] = "1"
    diverted = rows.iloc[[1]].copy()
    diverted.loc[:, "Diverted"] = "1"
    rows = pd.concat([rows, cancelled, diverted], ignore_index=True)

    features = create_features(rows)

    assert features["is_delayed"].tolist()[:2] == [0, 1]
    assert pd.isna(features.loc[2, "is_delayed"])
    assert pd.isna(features.loc[3, "is_delayed"])
    assert features["departure_hour"].tolist() == [8, 0, 8, 0]
    assert features["day_of_week"].tolist()[:2] == [0, 1]
    assert features["month"].tolist() == [1, 1, 1, 1]
    assert features["route"].tolist()[:2] == ["JFK-LAX", "ATL-ORD"]
    assert features["scheduled_flight_duration_minutes"].tolist() == [
        375,
        110,
        375,
        110,
    ]
    assert features["arrival_delay_category"].tolist() == [
        "on_time",
        "delayed",
        "cancelled",
        "diverted",
    ]


def test_training_frame_contains_no_actual_outcome_predictors() -> None:
    """Training selection excludes actual times, delay values, and status flags."""
    features = create_features(_base_rows())

    training = create_training_frame(features)

    assert len(training) == 2
    assert training["is_delayed"].tolist() == [0, 1]
    assert not ACTUAL_OUTCOME_COLUMNS.intersection(training.columns)
    assert "CRSDepTime" in training.columns
    assert "scheduled_flight_duration_minutes" in training.columns


def test_pipeline_writes_parquet_quality_and_eda_from_imported_csv(
    tmp_path: Path,
) -> None:
    """The end-to-end processor generates outputs from its supplied CSV only."""
    input_path = tmp_path / "source.csv"
    rows = _base_rows()
    rows["Cancelled"] = "0"
    rows["Diverted"] = "0"
    rows.to_csv(input_path, index=False)
    data_directory = tmp_path / "data"
    repository_root = tmp_path / "repo"

    report = process_bts_csv(
        input_path,
        data_directory,
        repository_root,
        chunksize=1,
    )

    parquet_path = data_directory / "processed" / "bts_ontime_2024_01.parquet"
    raw_path = data_directory / "raw" / "source.csv"
    assert report["processed_rows"] == 2
    assert parquet_path.is_file()
    assert raw_path.read_bytes() == input_path.read_bytes()
    assert raw_path.with_name("source.csv.provenance.json").is_file()
    assert (repository_root / "docs" / "data_quality_report.md").is_file()
    assert (
        repository_root / "reports" / "eda" / "2024-01" / "overview.csv"
    ).is_file()
    processed = pd.read_parquet(parquet_path)
    assert len(processed) == 2
    assert processed["is_delayed"].tolist() == [0, 1]


def test_download_resumes_partial_archive_without_losing_received_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupted HTTP transfers retry from the received prefix with Range."""
    content = _bts_archive()
    cut = len(content) // 2
    monkeypatch.setattr(bts_ingestion.time, "sleep", lambda _: None)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content,
                200,
                {
                    "Content-Length": str(len(content)),
                    "ETag": '"bts-january-2024"',
                },
                interrupt_after=cut,
            ),
            _FakeResponse(
                content[cut:],
                206,
                {
                    "Content-Length": str(len(content) - cut),
                    "Content-Range": f"bytes {cut}-{len(content) - 1}/{len(content)}",
                    "ETag": '"bts-january-2024"',
                },
            ),
        ],
    )
    target = tmp_path / "source.zip"

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[1]["Range"] == f"bytes={cut}-"
    assert requests[1]["If-range"] == '"bts-january-2024"'
    assert requests[0]["Accept-encoding"] == "identity"


def test_range_resume_validates_content_range_and_sends_if_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid 206 response appends at the exact offset using stored validators."""
    content = _bts_archive()
    cut = len(content) // 2
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content[:cut])
    bts_ingestion._write_download_metadata(partial, '"stable-etag"', len(content))
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content[cut:],
                206,
                {
                    "Content-Range": f"bytes {cut}-{len(content) - 1}/{len(content)}",
                    "Content-Length": str(len(content) - cut),
                    "ETag": '"stable-etag"',
                },
            )
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[0]["Range"] == f"bytes={cut}-"
    assert requests[0]["If-range"] == '"stable-etag"'


def test_last_modified_protects_resume_when_etag_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Last-Modified is used as the If-Range validator when ETag is absent."""
    content = _bts_archive()
    cut = len(content) // 2
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content[:cut])
    modified = "Thu, 11 Apr 2024 17:42:11 GMT"
    bts_ingestion._write_download_metadata(
        partial, None, len(content), last_modified=modified
    )
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content[cut:],
                206,
                {
                    "Content-Range": f"bytes {cut}-{len(content) - 1}/{len(content)}",
                    "Content-Length": str(len(content) - cut),
                    "Last-Modified": modified,
                },
            )
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[0]["If-range"] == modified


def test_chunked_identity_response_can_complete_without_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A complete, valid ZIP can be verified when transfer encoding omits length."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content,
                200,
                {
                    "Transfer-Encoding": "chunked",
                    "ETag": '"etag"',
                },
            )
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content


@pytest.mark.parametrize(
    "content_range",
    [
        "bytes 0-5/10",
        "bytes 5-4/10",
        "bytes 5-10/10",
        "bytes 5-9/*",
        "bytes 5-9/10 extra",
    ],
)
def test_invalid_content_range_preserves_existing_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content_range: str,
) -> None:
    """Malformed ranges, wrong starts, and invalid end/total are rejected."""
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    existing = b"prefix"
    partial.write_bytes(existing)
    bts_ingestion._write_download_metadata(partial, '"etag"', 10)
    _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                b"12345",
                206,
                {
                    "Content-Range": content_range,
                    "Content-Length": "5",
                    "ETag": '"etag"',
                },
            )
        ],
    )

    with pytest.raises(RuntimeError, match="Content-Range"):
        bts_ingestion.download_archive(target)

    assert partial.read_bytes() == existing
    assert not target.exists()


def test_changed_total_restarts_with_full_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A total-size change never gets appended to an old partial."""
    content = _bts_archive()
    cut = len(content) // 2
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content[:cut])
    bts_ingestion._write_download_metadata(partial, '"etag"', len(content) + 1)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content[cut:],
                206,
                {
                    "Content-Range": f"bytes {cut}-{len(content) - 1}/{len(content)}",
                    "Content-Length": str(len(content) - cut),
                    "ETag": '"etag"',
                },
            ),
            _FakeResponse(
                content,
                200,
                {"Content-Length": str(len(content)), "ETag": '"new-etag"'},
            ),
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert "Range" in requests[0]
    assert "Range" not in requests[1]


def test_body_length_mismatch_does_not_change_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean-EOF truncation is retained and completed with a ranged retry."""
    content = _bts_archive()
    cut = len(content) // 2
    missing = 1
    received_end = len(content) - missing
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content[:cut])
    bts_ingestion._write_download_metadata(partial, '"etag"', len(content))
    monkeypatch.setattr(bts_ingestion.time, "sleep", lambda _: None)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content[cut:received_end],
                206,
                {
                    "Content-Range": f"bytes {cut}-{len(content) - 1}/{len(content)}",
                    "Content-Length": str(len(content) - cut),
                    "ETag": '"etag"',
                },
            ),
            _FakeResponse(
                content[received_end:],
                206,
                {
                    "Content-Range": (
                        f"bytes {received_end}-{len(content) - 1}/{len(content)}"
                    ),
                    "Content-Length": str(missing),
                    "ETag": '"etag"',
                },
            ),
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[1]["Range"] == f"bytes={received_end}-"


def test_etag_mismatch_restarts_instead_of_appending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If-Range and changed ETags force a fresh full-body request."""
    content = _bts_archive()
    cut = len(content) // 2
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(b"old-version")
    bts_ingestion._write_download_metadata(partial, '"old-etag"', 100)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                b"ignored",
                206,
                {
                    "Content-Range": (
                        f"bytes {len(b'old-version')}-{len(b'old-version') + 6}/100"
                    ),
                    "Content-Length": "7",
                    "ETag": '"new-etag"',
                },
            ),
            _FakeResponse(
                content,
                200,
                {"Content-Length": str(len(content)), "ETag": '"new-etag"'},
            ),
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[0]["If-range"] == '"old-etag"'
    assert "Range" not in requests[1]


def test_server_ignoring_range_replaces_partial_with_full_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response to a range request is handled as a fresh archive."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(b"old-prefix")
    bts_ingestion._write_download_metadata(partial, '"etag"', 100)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content,
                200,
                {"Content-Length": str(len(content)), "ETag": '"etag"'},
            )
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[0]["Range"] == f"bytes={len(b'old-prefix')}-"


def test_unverified_legacy_partial_is_backed_up_before_fresh_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy partial without validators is preserved, never blindly resumed."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    legacy_bytes = b"unverified legacy prefix"
    partial.write_bytes(legacy_bytes)
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content,
                200,
                {"Content-Length": str(len(content)), "ETag": '"stable-etag"'},
            )
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert partial.with_name(partial.name + ".unverified").read_bytes() == legacy_bytes
    assert "Range" not in requests[0]


def test_encoded_response_is_rejected_without_promoting_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lengths must describe archive bytes, so unexpected content encoding fails."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content,
                200,
                {
                    "Content-Length": str(len(content)),
                    "Content-Encoding": "gzip",
                    "ETag": '"etag"',
                },
            )
        ],
    )

    with pytest.raises(RuntimeError, match="encoded content"):
        bts_ingestion.download_archive(target)

    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_valid_416_promotes_only_complete_valid_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 416 is accepted only when total size and archive contents agree."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content)
    bts_ingestion._write_download_metadata(partial, '"etag"', len(content))
    _queue_http_responses(monkeypatch, [_http_416(len(content))])

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert not partial.exists()


def test_invalid_416_restarts_and_does_not_promote_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong total in 416 triggers a new full download, not promotion."""
    content = _bts_archive()
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content)
    bts_ingestion._write_download_metadata(partial, '"etag"', len(content))
    requests = _queue_http_responses(
        monkeypatch,
        [
            _http_416(len(content) + 1),
            _FakeResponse(
                content,
                200,
                {"Content-Length": str(len(content)), "ETag": '"etag"'},
            ),
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert "Range" in requests[0]
    assert "Range" not in requests[1]


@pytest.mark.parametrize(
    "body",
    [
        b"not a zip file",
        _bts_archive("unexpected.csv"),
        _bts_archive("On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_1.csv"),
    ],
    ids=["corrupt-zip", "unexpected-csv-member", "missing-january-identity"],
)
def test_invalid_archive_is_never_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    """ZIP integrity and exact BTS member identity are required for completion."""
    target = tmp_path / "source.zip"
    def full_response() -> _FakeResponse:
        return _FakeResponse(
            body,
            200,
            {"Content-Length": str(len(body)), "ETag": '"etag"'},
        )

    _queue_http_responses(monkeypatch, [full_response(), full_response()])

    with pytest.raises(RuntimeError, match="failed validation"):
        bts_ingestion.download_archive(target)

    assert not target.exists()
    assert target.with_name(target.name + ".part").exists()


def test_extract_bts_csv_accepts_exact_expected_member(
    tmp_path: Path,
) -> None:
    """Extraction compares expected member names, not ZipInfo objects."""
    archive_path = tmp_path / "source.zip"
    archive_path.write_bytes(_bts_archive())

    extracted = bts_ingestion.extract_bts_csv(archive_path, tmp_path / "raw")

    assert extracted.name == bts_ingestion.CSV_NAME
    assert extracted.read_text(encoding="utf-8") == "FlightDate\n2024-01-01\n"


def test_interrupted_206_keeps_verified_prefix_for_next_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted range response preserves bytes and resumes from new size."""
    content = _bts_archive()
    initial_offset = len(content) // 3
    target = tmp_path / "source.zip"
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content[:initial_offset])
    bts_ingestion._write_download_metadata(partial, '"etag"', len(content))
    requests = _queue_http_responses(
        monkeypatch,
        [
            _FakeResponse(
                content[initial_offset:],
                206,
                {
                    "Content-Range": (
                        f"bytes {initial_offset}-{len(content) - 1}/{len(content)}"
                    ),
                    "Content-Length": str(len(content) - initial_offset),
                    "ETag": '"etag"',
                },
                interrupt_after=20,
            ),
            _FakeResponse(
                content[initial_offset + 20:],
                206,
                {
                    "Content-Range": (
                        f"bytes {initial_offset + 20}-{len(content) - 1}/{len(content)}"
                    ),
                    "Content-Length": str(len(content) - initial_offset - 20),
                    "ETag": '"etag"',
                },
            ),
        ],
    )

    assert bts_ingestion.download_archive(target) == target
    assert target.read_bytes() == content
    assert requests[1]["Range"] == f"bytes={initial_offset + 20}-"


def test_pipeline_omits_only_globally_empty_trailing_header(tmp_path: Path) -> None:
    """BTS's trailing blank header is omitted from Parquet but raw CSV is kept."""
    input_path = tmp_path / "trailing-header.csv"
    rows = _base_rows()
    with input_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow([*rows.columns, ""])
        for row in rows.itertuples(index=False, name=None):
            writer.writerow([*row, ""])

    report = process_bts_csv(
        input_path,
        tmp_path / "data",
        tmp_path / "repo",
        chunksize=1,
    )

    assert report["column_count"] == len(rows.columns) + 1
    assert report["named_column_count"] == len(rows.columns)
    assert report["processed_columns_dropped"] == ["Unnamed: 14"]
    processed = pd.read_parquet(
        tmp_path / "data" / "processed" / "bts_ontime_2024_01.parquet"
    )
    assert not any(str(column).startswith("Unnamed: ") for column in processed.columns)
