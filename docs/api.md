# Public Python API

Import supported interfaces from `autoschema`. Modules beginning with `_`, and the internal structure of `core.py` and `reporting.py`, are implementation details.

```python
from autoschema import (
    AutoSchemaError,
    ConversionResult,
    convert_csv,
    convert_dataframe,
    load_result,
)
```

## Conversion functions

```python
convert_csv(
    csv_path,
    out="output",
    *,
    engine="sqlite",
    max_dependency_width=2,
    max_key_width=2,
    max_candidate_columns=30,
    max_checks=2000,
    key_columns=None,
    delimiter=",",
    encoding="utf-8-sig",
    miner="pandas",
) -> ConversionResult
```

`csv_path` and `out` accept strings or `pathlib.Path` objects. The input must have a nonempty, case-insensitively unique header and at least one data row. The destination must be new or empty. A conversion writes its database, exports, summary and report in a staging directory, then publishes the completed directory. Failure before publication cleans up the staged artifacts. Existing destination files are never replaced.

| Option | Meaning |
| --- | --- |
| `engine` | `sqlite` (built into Python) or optional `duckdb` |
| `key_columns` | Sequence of existing column names forming a unique, nonblank fact-table key; `None` enables inference |
| `max_dependency_width` | Maximum determinant columns, integer 1–3 |
| `max_key_width` | Maximum inferred primary-key columns, integer 1–3 |
| `max_candidate_columns` | Positive number of candidate determinant/key columns; identifier-like names receive priority |
| `max_checks` | Positive maximum candidates checked per dependency/key search |
| `delimiter` | One separator character, excluding newline and NUL |
| `encoding` | Python text encoding; default accepts a UTF-8 BOM |
| `miner` | Compatibility argument; only `pandas` is supported |

```python
convert_dataframe(
    frame,
    out="output",
    *,
    engine="sqlite",
    max_dependency_width=2,
    max_key_width=2,
    max_candidate_columns=30,
    max_checks=2000,
    key_columns=None,
) -> ConversionResult
```

Accepts a pandas DataFrame without modifying it. Missing values become empty strings. Values normalize to CSV-style strings, then integers or decimals are inferred only when their text round-trips safely. Leading zeros, oversized integers, signed-zero text, fixed decimal formatting and mixed blank columns remain text when needed. Original pandas dtypes, CSV quoting, original CSV bytes and SQL row order are not preserved. Duplicate row multiplicities are preserved.

Both functions compare the reconstructed `dataset` view against the normalized typed input as multisets before returning. Functional dependencies are observed input patterns, not proven domain rules. Inference uses a bounded greedy star-schema plan, not a complete or optimal normalization algorithm. Processing and verification require the data to fit in memory.

## Results and saved conversions

```python
result = convert_csv("orders.csv", out="results/orders")
reopened = load_result("results/orders")
# The summary file is accepted as well:
reopened = load_result("results/orders/schema.json")
```

`load_result()` reads the metadata and checks that the reported tables and reconstruction view exist with the reported original columns. It does not rerun inference, require the source CSV, or repeat the original row-by-row validation. Files may be moved together to a new directory before loading. Corrupt or unsupported summaries raise `InvalidResultError`. Version 0.2 reports without `report_format_version` remain readable; new reports explicitly use format 1. The database and `schema.json` are needed for reopening; ancillary exports are optional.

| Member | Result |
| --- | --- |
| `output_dir` | Absolute output `Path` |
| `database_path` | Absolute database `Path` |
| `report_path` | HTML report `Path` |
| `tables` | Fresh list of physical table names |
| `summary()` | Independent JSON-serializable summary dictionary |
| `report` | Independent copy of the same metadata |
| `read_table(name="dataset")` | Table or reconstruction view as a pandas DataFrame |
| `query(sql, parameters=None)` | Read-only query result as a pandas DataFrame |

No connection is retained between calls. Returned metadata can be modified without changing the result object's engine or table names. `query()` propagates database SQL errors, including attempts to modify a read-only database. Parameter binding follows the selected engine; prefer bound parameters over string interpolation.

```python
rows = result.query(
    "SELECT * FROM dataset WHERE customer_id = ?",
    parameters=["C01"],
)
# SQLite named parameters:
rows = result.query(
    "SELECT * FROM dataset WHERE customer_id = :customer",
    parameters={"customer": "C01"},
)
```

## Summary fields

The report dictionary contains:

| Fields | Meaning |
| --- | --- |
| `version`, `report_format_version` | Producer package version and metadata format |
| `source`, `engine`, `miner` | Input provenance and selected backend |
| `input_rows`, `input_columns`, `columns` | Original logical shape and column order |
| `duplicate_rows`, `blank_cells`, `column_profiles` | Data-quality and per-column statistics |
| `dependencies`, `primary_key_candidates`, `selected_key` | Discovered relationships and chosen fact key |
| `dimensions`, `records_columns`, `tables`, `table_rows` | Physical schema, keys, rows and columns |
| `input_cells`, `stored_cells`, `cell_reduction_percent` | Logical repeated-value reduction, including dimension keys |
| `database_bytes`, `database_to_csv_ratio` | Actual database bytes and its size relative to the source CSV; ratio is `None` for DataFrame input |
| `reconstruction_exact`, `row_order_preserved` | Exact normalized multiset verification and row-order guarantee (`False`) |
| `search`, `warnings` | Search bounds, checks performed and interpretation limits |
| `timings_seconds`, `processing_seconds` | Stage durations and total, excluding final report rendering/publication |

Cell reduction is not byte compression. Actual database size excludes additional exports, indexes can increase file size, and timings are measurements of the current run rather than performance guarantees. Summary fields may be added in compatible releases; callers should select the fields they need rather than requiring an exact set of keys.

## Error handling

```python
from autoschema import ConfigurationError, InvalidDataError, OutputExistsError

try:
    result = convert_csv("orders.csv", out="results/orders")
except OutputExistsError:
    # Choose a new directory; the existing files were not replaced.
    raise
except InvalidDataError as error:
    print(f"Review the source data: {error}")
except ConfigurationError as error:
    print(f"Review the options: {error}")
```

All library-specific exceptions inherit from `AutoSchemaError`. `ConfigurationError`, `InvalidDataError` and `InvalidResultError` also inherit from `ValueError`; `OutputExistsError` inherits from `FileExistsError`; `MissingDependencyError` inherits from `ImportError`; `ReconstructionError` inherits from `RuntimeError`. This preserves ordinary Python exception handling while allowing specific recovery.

Input/output filesystem errors remain ordinary `OSError` subclasses. Non-DataFrame input to `convert_dataframe` raises `TypeError`. Query syntax and read-only database errors retain their backend exception types. An absent optional DuckDB engine raises `MissingDependencyError` with installation guidance.
