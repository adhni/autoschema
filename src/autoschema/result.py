"""Typed result objects and reopening conversions in a later Python session."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from ._database import _connect, quote
from .exceptions import InvalidResultError

SQLParameters = Union[Sequence[Any], Mapping[str, Any]]


@dataclass(frozen=True, init=False)
class ConversionResult:
    """A completed conversion with no retained database connection.

    ``output_dir`` and ``database_path`` are absolute paths. ``report`` and
    ``summary()`` return copies, so changing a returned dictionary cannot change
    the result's engine, table names or metadata. Use ``load_result`` to reopen
    an existing conversion without repeating inference.
    """

    output_dir: Path
    database_path: Path
    _report: dict[str, Any] = field(repr=False)

    def __init__(
        self,
        output_dir: Union[str, Path],
        database_path: Union[str, Path],
        report: Mapping[str, Any],
    ) -> None:
        object.__setattr__(self, "output_dir", Path(output_dir).resolve())
        object.__setattr__(self, "database_path", Path(database_path).resolve())
        object.__setattr__(self, "_report", deepcopy(dict(report)))

    @property
    def report(self) -> dict[str, Any]:
        """An independent copy of the JSON-serializable conversion metadata."""
        return deepcopy(self._report)

    @property
    def report_path(self) -> Path:
        """Path to the self-contained HTML processing report."""
        return self.output_dir / "report.html"

    @property
    def tables(self) -> list[str]:
        """Physical table names; the reconstruction view is named ``dataset``."""
        return list(self._report["table_rows"])

    def summary(self) -> dict[str, Any]:
        """Return an independent, JSON-serializable conversion summary."""
        return self.report

    def query(self, sql: str, parameters: Optional[SQLParameters] = None) -> pd.DataFrame:
        """Execute a read-only query and return its rows as a DataFrame.

        Parameter values are bound by the selected database engine. SQLite
        supports positional ``?`` and named ``:name`` parameters. Backend SQL
        errors propagate unchanged. This method does not hold a connection open.
        """
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("sql must be a nonempty SQL query.")
        con = _connect(self.database_path, self._report["engine"], readonly=True)
        try:
            if self._report["engine"] == "sqlite":
                con.execute("PRAGMA query_only=ON")
            cursor = con.execute(sql, [] if parameters is None else parameters)
            if cursor.description is None:
                raise ValueError("query() requires a statement that returns rows.")
            return pd.DataFrame(cursor.fetchall(), columns=[c[0] for c in cursor.description])
        finally:
            con.close()

    def read_table(self, name: str = "dataset") -> pd.DataFrame:
        """Read one physical table, or the full joining ``dataset`` view."""
        if name not in self.tables + ["dataset"]:
            raise ValueError(f"Unknown table: {name}")
        return self.query(f"SELECT * FROM {quote(name)}")


def load_result(out: Union[str, Path]) -> ConversionResult:
    """Reopen a saved conversion without rerunning inference or changing files.

    Accepts a result directory or its ``schema.json`` file. Report format 1 and
    legacy 0.2 reports are supported. Checks required metadata, the database and
    its table/view columns. This is a structural check, not a repeat of the
    original input comparison; the source CSV is not needed to reopen a result.

    Raises ``InvalidResultError`` for incomplete or incompatible artifacts.
    Backend errors while opening a damaged database are chained as the cause.
    """
    output = Path(out).resolve()
    if output.name == "schema.json" and output.is_file():
        output = output.parent
    try:
        report = json.loads((output / "schema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidResultError(f"Cannot read a result summary from {output}.") from exc
    if not isinstance(report, dict):
        raise InvalidResultError("Result summary must be a JSON object.")
    format_version = report.get("report_format_version", 1)
    if type(format_version) is not int or format_version != 1:
        raise InvalidResultError("Unsupported report format version.")
    engine = report.get("engine")
    columns = report.get("columns")
    tables = report.get("table_rows")
    if (
        engine not in ("sqlite", "duckdb")
        or report.get("reconstruction_exact") is not True
        or not isinstance(columns, list)
        or not columns
        or any(not isinstance(c, str) or not c or "\x00" in c for c in columns)
        or not isinstance(tables, dict)
        or "records" not in tables
        or any(not isinstance(t, str) or not t or "\x00" in t for t in tables)
        or any(type(count) is not int or count < 0 for count in tables.values())
    ):
        raise InvalidResultError(
            "Result summary is missing valid engine, table, column or verification metadata."
        )
    database = output / ("dataset.sqlite" if engine == "sqlite" else "dataset.duckdb")
    if not database.is_file():
        raise InvalidResultError(f"Result database is missing: {database.name}.")
    result = ConversionResult(output, database, report)
    con = None
    try:
        con = _connect(database, engine, readonly=True)
        if engine == "sqlite":
            con.execute("PRAGMA query_only=ON")
        for table in tables:
            con.execute(f"SELECT * FROM {quote(table)} LIMIT 0")
        cursor = con.execute("SELECT * FROM dataset LIMIT 0")
        if [c[0] for c in cursor.description] != columns:
            raise InvalidResultError("The dataset view does not match the reported columns.")
    except ImportError:
        raise
    except InvalidResultError:
        raise
    except Exception as exc:
        raise InvalidResultError(
            "The saved database cannot be read or is missing reported tables."
        ) from exc
    finally:
        if con is not None:
            con.close()
    return result
