"""Public conversion API and orchestration; inference and storage remain private."""

from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Optional, Union

import pandas as pd

from ._inference import (
    _candidate_columns,
    _discover,
    _find_keys,
    _identifier,
    _normalize,
    _plan,
    _profile,
)
from ._storage import write_artifacts
from ._version import __version__
from .exceptions import ConfigurationError, InvalidDataError, OutputExistsError
from .reporting import render_report
from .result import ConversionResult

PathLike = Union[str, Path]


def _validate_options(
    engine,
    max_dependency_width,
    max_key_width,
    max_candidate_columns,
    max_checks,
    key_columns,
    miner,
):
    if engine not in ("sqlite", "duckdb"):
        raise ConfigurationError("engine must be sqlite or duckdb.")
    if miner != "pandas":
        raise ConfigurationError(
            "Only miner='pandas' is supported; the Desbordante adapter is not implemented."
        )
    for name, value in (
        ("max_dependency_width", max_dependency_width),
        ("max_key_width", max_key_width),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3:
            raise ConfigurationError(f"{name} must be an integer between 1 and 3.")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (max_candidate_columns, max_checks)
    ):
        raise ConfigurationError("Search budgets must be positive integers.")
    if key_columns is not None:
        if isinstance(key_columns, (str, bytes)) or not isinstance(key_columns, Sequence):
            raise ConfigurationError("key_columns must be a sequence of column names.")
        if not key_columns or any(not isinstance(c, str) or not c for c in key_columns):
            raise ConfigurationError("key_columns must contain at least one nonempty column name.")


def convert_csv(
    csv_path: PathLike,
    out: PathLike = "output",
    *,
    engine: str = "sqlite",
    max_dependency_width: int = 2,
    max_key_width: int = 2,
    max_candidate_columns: int = 30,
    max_checks: int = 2000,
    key_columns: Optional[Sequence[str]] = None,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    miner: str = "pandas",
) -> ConversionResult:
    """Convert a CSV into inferred SQL tables and verified, inspectable artifacts.

    Parameters
    ----------
    csv_path : str or pathlib.Path
        CSV with a nonempty, case-insensitively unique header.
    out : str or pathlib.Path
        New or empty destination directory. Existing files are never replaced.
    engine : {"sqlite", "duckdb"}
        Database engine. DuckDB requires the optional ``duckdb`` extra.
    key_columns : sequence of str, optional
        Explicit fact-table primary key. Must uniquely identify rows without blanks.
    max_dependency_width, max_key_width : int
        Maximum columns per determinant/key (1 to 3, default 2).
    max_candidate_columns, max_checks : int
        Positive search budgets. Reaching them is disclosed in the summary.
    delimiter, encoding : str
        CSV separator and text encoding. UTF-8 BOMs are accepted by default.
    miner : str
        Compatibility option; only ``"pandas"`` is supported.

    Returns
    -------
    ConversionResult
        Paths, an independent JSON summary, and read-only query methods.

    Raises
    ------
    ConfigurationError
        An option is unsupported or invalid.
    InvalidDataError
        The CSV is malformed, empty, or its explicit key is invalid.
    OutputExistsError
        The output directory is not empty.
    ReconstructionError
        Exact reconstruction or foreign-key validation fails.

    Notes
    -----
    Empty CSV fields remain empty strings. Values are conservatively inferred as
    numeric. Duplicate rows are preserved; row order is unspecified. All input
    must fit in memory. Failed conversions do not publish partial artifacts.
    """
    _validate_options(
        engine,
        max_dependency_width,
        max_key_width,
        max_candidate_columns,
        max_checks,
        key_columns,
        miner,
    )
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in "\r\n\x00":
        raise ConfigurationError("delimiter must be one non-newline, non-NUL character.")
    started = perf_counter()
    if not isinstance(encoding, str) or not encoding:
        raise ConfigurationError("encoding must be a nonempty text encoding name.")
    source = Path(csv_path)
    try:
        with source.open(encoding=encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            header = next(reader, [])
            if (
                not header
                or any(not c.strip() or "\x00" in c for c in header)
                or len({c.casefold() for c in header}) != len(header)
            ):
                raise InvalidDataError(
                    "CSV headers must be nonempty and unique, ignoring case, with no NUL characters."
                )
            rows = []
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise InvalidDataError(
                        f"CSV record ending at line {reader.line_num} has {len(row)} fields; expected {len(header)}."
                    )
                if any("\x00" in value for value in row):
                    raise InvalidDataError(
                        "NUL characters in CSV files are unsupported. Remove them before importing."
                    )
                rows.append(row)
    except (csv.Error, UnicodeError) as exc:
        raise InvalidDataError(f"Invalid CSV input: {exc}") from exc
    except LookupError as exc:
        raise ConfigurationError(f"Unknown CSV encoding: {encoding}") from exc
    frame = pd.DataFrame(rows, columns=header)
    return _convert(
        frame,
        out,
        engine=engine,
        max_dependency_width=max_dependency_width,
        max_key_width=max_key_width,
        max_candidate_columns=max_candidate_columns,
        max_checks=max_checks,
        key_columns=key_columns,
        miner=miner,
        source={"kind": "csv", "name": source.name, "bytes": source.stat().st_size},
        read_seconds=perf_counter() - started,
    )


def convert_dataframe(
    frame: pd.DataFrame,
    out: PathLike = "output",
    *,
    engine: str = "sqlite",
    max_dependency_width: int = 2,
    max_key_width: int = 2,
    max_candidate_columns: int = 30,
    max_checks: int = 2000,
    key_columns: Optional[Sequence[str]] = None,
) -> ConversionResult:
    """Convert an in-memory DataFrame without modifying it.

    Options and output behavior match :func:`convert_csv`. Missing values become
    empty strings; values normalize to CSV-style strings with conservative numeric
    inference. Arbitrary pandas dtypes and Python objects are not preserved.
    Raises ``TypeError`` for non-DataFrame input and the same AutoSchema exceptions
    as ``convert_csv`` for configuration, data, output and reconstruction failures.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame.")
    _validate_options(
        engine,
        max_dependency_width,
        max_key_width,
        max_candidate_columns,
        max_checks,
        key_columns,
        "pandas",
    )
    return _convert(
        frame,
        out,
        engine=engine,
        max_dependency_width=max_dependency_width,
        max_key_width=max_key_width,
        max_candidate_columns=max_candidate_columns,
        max_checks=max_checks,
        key_columns=key_columns,
        miner="pandas",
        source={"kind": "dataframe", "name": "DataFrame", "bytes": None},
        read_seconds=0,
    )


def _convert(
    frame,
    out,
    *,
    engine,
    max_dependency_width,
    max_key_width,
    max_candidate_columns,
    max_checks,
    key_columns,
    miner,
    source,
    read_seconds,
):
    destination = Path(out).resolve()
    if destination.exists() and not destination.is_dir():
        raise OutputExistsError(f"Output path is a file: {destination}.")
    if destination.exists() and any(destination.iterdir()):
        raise OutputExistsError(
            f"Output directory is not empty: {destination}. Choose a new output directory."
        )
    timing = {"read": read_seconds}
    started = perf_counter()
    data = _normalize(frame)
    profile = _profile(data)
    timing["profile"] = perf_counter() - started
    warnings = [
        "Dependencies describe this input; review inferred relationships before using them with future data.",
        "Processing and exact reconstruction validation load data into memory; this is not a streaming converter.",
    ]
    started = perf_counter()
    search_columns = _candidate_columns(data, max_candidate_columns)
    dependencies, dependency_checks, dependency_truncated = _discover(
        data, search_columns, max_dependency_width, max_checks
    )
    timing["discover"] = perf_counter() - started
    started = perf_counter()
    explicit = list(key_columns) if key_columns is not None else []
    # Validate explicit keys before planning, and keep them in the fact table.
    if explicit:
        _find_keys(data, [], max_key_width, max_checks, explicit)
    remaining, dimensions = _plan(data, dependencies, explicit)
    key_search_columns = _candidate_columns(data[remaining], max_candidate_columns)
    keys, key_checks, key_truncated = _find_keys(
        data[remaining], key_search_columns, max_key_width, max_checks, explicit
    )
    selected = keys[0] if keys else []
    timing["plan"] = perf_counter() - started
    if len(search_columns) < len(data.columns):
        warnings.append(
            f"Dependency determinants were limited to {len(search_columns)} of {len(data.columns)} columns."
        )
    if dependency_truncated or key_truncated:
        warnings.append("A search budget was reached; additional dependencies or keys may exist.")
    if not selected:
        warnings.append(
            "No primary key was found within the search bounds. Duplicate rows are preserved."
        )
    elif not any(_identifier(c) for c in selected) and not explicit:
        warnings.append(
            "The selected primary key has no identifier-like column name; consider key_columns to set a domain key."
        )
    if not dimensions:
        warnings.append(
            "No beneficial decomposition was found within the search bounds; all columns remain in records."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Build all artifacts away from the destination so a failed export never
    # exposes a database without its summary, report or data files.
    with tempfile.TemporaryDirectory(prefix=".autoschema-", dir=destination.parent) as temporary:
        output = Path(temporary) / "artifacts"
        output.mkdir()
        table_profiles, database_bytes = write_artifacts(
            data,
            dimensions,
            remaining,
            selected,
            output,
            engine,
            timing,
        )
        input_cells = len(data) * len(data.columns)
        stored_cells = sum(t["cells"] for t in table_profiles)
        report = {
            "version": __version__,
            "report_format_version": 1,
            "source": source,
            "engine": engine,
            "miner": miner,
            "input_rows": len(data),
            "input_columns": len(data.columns),
            "columns": list(data),
            "duplicate_rows": int(data.duplicated().sum()),
            "blank_cells": sum(p["blank_count"] for p in profile),
            "column_profiles": profile,
            "cardinality": {p["name"]: p["distinct"] for p in profile},
            "dependencies": dependencies,
            "primary_key_candidates": keys,
            "selected_key": selected,
            "dimensions": dimensions,
            "records_columns": remaining,
            "tables": table_profiles,
            "table_rows": {t["name"]: t["rows"] for t in table_profiles},
            "input_cells": input_cells,
            "stored_cells": stored_cells,
            "cell_reduction_percent": round(100 * (1 - stored_cells / input_cells), 2),
            "database_bytes": database_bytes,
            "database_to_csv_ratio": round(database_bytes / source["bytes"], 3)
            if source["bytes"]
            else None,
            "reconstruction_exact": True,
            "row_order_preserved": False,
            "search": {
                "max_dependency_width": max_dependency_width,
                "max_key_width": max_key_width,
                "max_candidate_columns": max_candidate_columns,
                "max_checks": max_checks,
                "determinant_columns": search_columns,
                "dependency_checks": dependency_checks,
                "key_checks": key_checks,
                "dependency_budget_reached": dependency_truncated,
                "key_budget_reached": key_truncated,
            },
            "timings_seconds": {k: round(v, 6) for k, v in timing.items()},
            "processing_seconds": round(sum(timing.values()), 6),
            "warnings": warnings,
        }
        (output / "schema.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (output / "report.html").write_text(render_report(report), encoding="utf-8")
        # Recheck after inference: another run may have used this destination.
        if destination.exists():
            try:
                destination.rmdir()  # only an empty destination can be removed
            except OSError as exc:
                raise OutputExistsError(
                    f"Output directory is no longer empty: {destination}."
                ) from exc
        output.rename(destination)
    database = destination / ("dataset.sqlite" if engine == "sqlite" else "dataset.duckdb")
    return ConversionResult(destination, database, report)
