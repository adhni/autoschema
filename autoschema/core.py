"""Bounded dependency discovery and lossless, verified star-schema export."""

import csv
import itertools
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def _sql_type(series):
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE"
    return "VARCHAR"


def _normalize(frame):
    if frame.empty or not len(frame.columns):
        raise ValueError("The dataset must contain at least one row and one column.")
    columns = list(frame.columns)
    if any(not isinstance(c, str) or not c.strip() or "\x00" in c for c in columns):
        raise ValueError("Column names must be nonempty strings.")
    if len({c.casefold() for c in columns}) != len(columns):
        raise ValueError("Column names must be unique, ignoring case, for SQL compatibility.")
    result = frame.copy()
    for column in columns:
        # CSV empty fields and DataFrame missing values become empty strings.
        text = result[column].astype(object).where(result[column].notna(), "").map(str)
        numeric = pd.to_numeric(text, errors="coerce")
        integer = (
            text.str.fullmatch(r"-?(0|[1-9][0-9]*)").all()
            and pd.api.types.is_integer_dtype(numeric)
            and numeric.min() >= -(2**63)
            and numeric.max() <= 2**63 - 1
        )
        decimal = (
            text.str.fullmatch(r"-?(0|[1-9][0-9]*)\.[0-9]+").all()
            and numeric.notna().all()
            and numeric.map(math.isfinite).all()
            and not ((numeric == 0) & text.str.startswith("-")).any()
        )
        # Keep leading zeros, formatting, oversized integers and mixed blanks intact.
        result[column] = numeric if (integer or decimal) and numeric.astype(str).equals(text) else text
    return result


def _identifier(column):
    name = column.casefold()
    return name in {"id", "code", "key", "uuid"} or name.endswith(("_id", "_code", "_key", "_uuid"))


def _candidate_columns(frame, limit):
    columns = list(frame)
    # Spend the bounded search budget on identifiers first, then original order.
    return sorted(columns, key=lambda c: (not _identifier(c), columns.index(c)))[:limit]


def _profile(frame):
    result = []
    for column in frame:
        series = frame[column]
        unique = int(series.nunique(dropna=False))
        item = {
            "name": column,
            "sql_type": _sql_type(series),
            "distinct": unique,
            "distinct_percent": round(100 * unique / len(frame), 2),
            "blank_count": int((series == "").sum()),
        }
        if pd.api.types.is_numeric_dtype(series):
            item.update(min=series.min().item(), max=series.max().item(), mean=float(series.mean()))
        result.append(item)
    return result


def _discover(frame, search_columns, max_width, max_checks):
    """Find exact minimal FDs among nonunique, nonblank determinants."""
    rows = len(frame)
    cardinality = {c: int(frame[c].nunique(dropna=False)) for c in frame}
    dependencies = []
    determinants_by_attribute = {c: [] for c in frame}
    checks = 0
    truncated = False
    for width in range(1, max_width + 1):
        for keys in itertools.combinations(search_columns, width):
            if checks >= max_checks:
                truncated = True
                break
            checks += 1
            if any((frame[c] == "").any() for c in keys):
                continue
            grouped = frame.groupby(list(keys), dropna=False, sort=False)
            count = grouped.ngroups
            if not 1 < count < rows:
                continue
            candidates = [
                c for c in frame if c not in keys and cardinality[c] > 1
                and not any(set(k).issubset(keys) for k in determinants_by_attribute[c])
            ]
            if not candidates:
                continue
            maxima = grouped[candidates].nunique(dropna=False).max()
            attributes = [c for c in candidates if maxima[c] == 1]
            if attributes:
                dependencies.append({"keys": list(keys), "attributes": attributes, "distinct_keys": count})
                for attribute in attributes:
                    determinants_by_attribute[attribute].append(keys)
        if truncated:
            break
    return dependencies, checks, truncated


def _plan(frame, dependencies, protected):
    remaining = list(frame)
    dimensions = []
    protected = set(protected)
    used_names = {"records", "dataset"}
    direct = []
    for dependency in dependencies:
        attributes = set(dependency["attributes"])
        for bridge in dependencies:
            # Prefer customer_id -> city over the transitive order_id -> city.
            # Ignore equivalent determinants to avoid removing both sides of a cycle.
            if set(bridge["keys"]).issubset(set(dependency["keys"]) | attributes) and not set(dependency["keys"]).issubset(set(bridge["keys"]) | set(bridge["attributes"])):
                attributes.difference_update(bridge["attributes"])
        direct.append({**dependency, "attributes": [c for c in dependency["attributes"] if c in attributes]})
    while True:
        options = []
        for index, dependency in enumerate(direct):
            keys = dependency["keys"]
            if not set(keys).issubset(remaining):
                continue
            attributes = [c for c in dependency["attributes"] if c in remaining and c not in protected]
            savings = (len(frame) - dependency["distinct_keys"]) * len(attributes) - dependency["distinct_keys"] * len(keys)
            if attributes and savings > 0:
                options.append((savings, sum(_identifier(c) for c in keys), -len(keys), -index, keys, attributes))
        if not options:
            break
        savings, _, _, _, keys, attributes = max(options)
        base = "dim_" + re.sub(r"[^A-Za-z0-9_]", "_", "_".join(keys))
        name = base
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base}_{suffix}"
            suffix += 1
        used_names.add(name.casefold())
        dimensions.append({"table": name, "keys": keys, "attributes": attributes, "cells_saved": savings})
        protected.update(keys)
        remaining = [c for c in remaining if c not in attributes]
    return remaining, dimensions


def _find_keys(frame, columns, max_width, max_checks, explicit):
    if explicit:
        if len(set(explicit)) != len(explicit) or not set(explicit).issubset(frame.columns):
            raise ValueError("key_columns must contain distinct existing column names.")
        if any((frame[c] == "").any() for c in explicit) or frame.duplicated(list(explicit)).any():
            raise ValueError("key_columns must uniquely identify every row and contain no blanks.")
        return [list(explicit)], 1, False
    keys = []
    checks = 0
    truncated = False
    for width in range(1, max_width + 1):
        for combination in itertools.combinations(columns, width):
            if any(set(key).issubset(combination) for key in keys):
                continue
            if checks >= max_checks:
                truncated = True
                break
            checks += 1
            if any((frame[c] == "").any() for c in combination):
                continue
            if not frame.duplicated(list(combination)).any():
                keys.append(list(combination))
        if truncated:
            break
    # A complete identifier key is preferred to an accidentally unique measurement.
    keys.sort(key=lambda key: (not any(_identifier(c) for c in key), len(key), -sum(_identifier(c) for c in key)))
    return keys, checks, truncated


def _connect(path, engine, readonly=False):
    if engine == "sqlite":
        if readonly:
            return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys=ON")
        return con
    try:
        import duckdb
    except ImportError as exc:
        raise ImportError('Install DuckDB with: python3 -m pip install "autoschema[duckdb]"') from exc
    return duckdb.connect(str(path), read_only=readonly)


def _literal(value, engine):
    if isinstance(value, str):
        if "\x00" in value:
            # SQL source cannot contain a literal NUL byte.
            function = "char" if engine == "sqlite" else "chr"
            return f" || {function}(0) || ".join("'" + part.replace("'", "''") + "'" for part in value.split("\x00"))
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


@dataclass
class ConversionResult:
    """Paths and statistics from a completed conversion; no live connection is held."""

    output_dir: Path
    database_path: Path
    report: dict

    @property
    def report_path(self):
        return self.output_dir / "report.html"

    @property
    def tables(self):
        return list(self.report["table_rows"])

    def summary(self):
        """Return an independent copy of the JSON-serializable summary."""
        return json.loads(json.dumps(self.report))

    def query(self, sql, parameters=None):
        """Run a read-only SELECT against the result database and return a DataFrame."""
        con = _connect(self.database_path, self.report["engine"], readonly=True)
        try:
            if self.report["engine"] == "sqlite":
                con.execute("PRAGMA query_only=ON")
            cursor = con.execute(sql, [] if parameters is None else parameters)
            return pd.DataFrame(cursor.fetchall(), columns=[c[0] for c in cursor.description])
        finally:
            con.close()

    def read_table(self, name="dataset"):
        if name not in self.tables + ["dataset"]:
            raise ValueError(f"Unknown table: {name}")
        return self.query(f"SELECT * FROM {quote(name)}")


def convert_csv(csv_path, out="output", *, engine="sqlite", max_dependency_width=2,
                max_key_width=2, max_candidate_columns=30, max_checks=2000,
                key_columns=None, delimiter=",", encoding="utf-8-sig", miner="pandas"):
    """Convert a CSV into verified relational tables, exports and an HTML report.

    Inference is exact for the observed rows and bounded by the search options.
    Empty fields stay empty strings; row order is not a relational guarantee.
    Existing output artifacts are never overwritten.
    """
    started = perf_counter()
    source = Path(csv_path)
    if len(delimiter) != 1:
        raise ValueError("delimiter must be one character.")
    try:
        with source.open(encoding=encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            header = next(reader, [])
            if not header or any(not c.strip() or "\x00" in c for c in header) or len({c.casefold() for c in header}) != len(header):
                raise ValueError("CSV headers must be nonempty and unique, ignoring case, with no NUL characters.")
            rows = []
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise ValueError(f"CSV record ending at line {reader.line_num} has {len(row)} fields; expected {len(header)}.")
                if any("\x00" in value for value in row):
                    raise ValueError("NUL characters in CSV files are unsupported. Remove them before importing.")
                rows.append(row)
    except csv.Error as exc:
        raise ValueError(f"Invalid CSV record: {exc}. NUL characters are unsupported in CSV input.") from exc
    frame = pd.DataFrame(rows, columns=header)
    return _convert(frame, out, engine=engine, max_dependency_width=max_dependency_width,
                    max_key_width=max_key_width, max_candidate_columns=max_candidate_columns,
                    max_checks=max_checks, key_columns=key_columns, miner=miner,
                    source={"kind": "csv", "name": source.name, "bytes": source.stat().st_size},
                    read_seconds=perf_counter() - started)


def convert_dataframe(frame, out="output", *, engine="sqlite", max_dependency_width=2,
                      max_key_width=2, max_candidate_columns=30, max_checks=2000,
                      key_columns=None):
    """Convert a DataFrame without changing it; missing values become empty strings.

    Values are normalized to CSV-style strings, with conservative numeric inference.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame.")
    return _convert(frame, out, engine=engine, max_dependency_width=max_dependency_width,
                    max_key_width=max_key_width, max_candidate_columns=max_candidate_columns,
                    max_checks=max_checks, key_columns=key_columns, miner="pandas",
                    source={"kind": "dataframe", "name": "DataFrame", "bytes": None}, read_seconds=0)


def _convert(frame, out, *, engine, max_dependency_width, max_key_width,
             max_candidate_columns, max_checks, key_columns, miner, source, read_seconds):
    from .reporting import render_report

    if engine not in ("sqlite", "duckdb"):
        raise ValueError("engine must be sqlite or duckdb.")
    if miner not in ("pandas", "desbordante"):
        raise ValueError("miner must be pandas or desbordante.")
    for name, value in (("max_dependency_width", max_dependency_width), ("max_key_width", max_key_width)):
        if not isinstance(value, int) or not 1 <= value <= 3:
            raise ValueError(f"{name} must be between 1 and 3.")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (max_candidate_columns, max_checks)):
        raise ValueError("Search budgets must be positive integers.")
    if isinstance(key_columns, str):
        raise ValueError("key_columns must be a sequence of column names, such as ['order_id', 'line_number'].")
    output = Path(out).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}. Choose a new --out directory.")
    timing = {"read": read_seconds}
    started = perf_counter()
    data = _normalize(frame)
    profile = _profile(data)
    timing["profile"] = perf_counter() - started
    warnings = [
        "Dependencies describe this input; review inferred relationships before using them with future data.",
        "Processing and exact reconstruction validation load data into memory; this is not a streaming converter.",
    ]
    if miner == "desbordante":
        # Preserve the old flag without silently accepting an unavailable integration.
        raise ValueError("The Desbordante adapter is not supported by the library yet. Use miner='pandas'.")
    started = perf_counter()
    search_columns = _candidate_columns(data, max_candidate_columns)
    dependencies, dependency_checks, dependency_truncated = _discover(data, search_columns, max_dependency_width, max_checks)
    timing["discover"] = perf_counter() - started
    started = perf_counter()
    explicit = list(key_columns) if key_columns is not None else []
    # Validate explicit keys before planning, and keep them in the fact table.
    if explicit:
        _find_keys(data, [], max_key_width, max_checks, explicit)
    remaining, dimensions = _plan(data, dependencies, explicit)
    key_search_columns = _candidate_columns(data[remaining], max_candidate_columns)
    keys, key_checks, key_truncated = _find_keys(data[remaining], key_search_columns, max_key_width, max_checks, explicit)
    selected = keys[0] if keys else []
    timing["plan"] = perf_counter() - started
    if len(search_columns) < len(data.columns):
        warnings.append(f"Dependency determinants were limited to {len(search_columns)} of {len(data.columns)} columns.")
    if dependency_truncated or key_truncated:
        warnings.append("A search budget was reached; additional dependencies or keys may exist.")
    if not selected:
        warnings.append("No primary key was found within the search bounds. Duplicate rows are preserved.")
    elif not any(_identifier(c) for c in selected) and not explicit:
        warnings.append("The selected primary key has no identifier-like column name; consider key_columns to set a domain key.")
    if not dimensions:
        warnings.append("No beneficial decomposition was found within the search bounds; all columns remain in records.")
    output.mkdir(parents=True, exist_ok=True)
    database = output / ("dataset.sqlite" if engine == "sqlite" else "dataset.duckdb")
    table_data = {d["table"]: data[d["keys"] + d["attributes"]].drop_duplicates() for d in dimensions}
    table_data["records"] = data[remaining]
    schema = []
    table_profiles = []
    started = perf_counter()
    con = _connect(database, engine)
    try:
        con.execute("BEGIN TRANSACTION")
        for name, table in table_data.items():
            dimension = next((d for d in dimensions if d["table"] == name), None)
            primary_key = dimension["keys"] if dimension else selected
            definitions = [quote(c) + " " + _sql_type(data[c]) for c in table]
            if primary_key:
                definitions.append("PRIMARY KEY (" + ", ".join(map(quote, primary_key)) + ")")
            foreign_keys = []
            if name == "records":
                for d in dimensions:
                    columns = ", ".join(map(quote, d["keys"]))
                    definitions.append(f'FOREIGN KEY ({columns}) REFERENCES {quote(d["table"])} ({columns})')
                    foreign_keys.append({"columns": d["keys"], "references": d["table"]})
            statement = f"CREATE TABLE {quote(name)} (" + ", ".join(definitions) + ");"
            con.execute(statement)
            schema.append(statement)
            insert = f"INSERT INTO {quote(name)} VALUES (" + ", ".join("?" for _ in table) + ")"
            # Batch inserts avoid materializing another full list of input rows.
            iterator = table.itertuples(index=False, name=None)
            while True:
                batch = list(itertools.islice(iterator, 1000))
                if not batch:
                    break
                con.executemany(insert, batch)
            table_profiles.append({"name": name, "rows": len(table), "columns": list(table),
                                   "primary_key": primary_key, "foreign_keys": foreign_keys,
                                   "cells": len(table) * len(table.columns)})
        owners = {attribute: d["table"] for d in dimensions for attribute in d["attributes"]}
        select = ", ".join(f"{quote(owners.get(c, 'records'))}.{quote(c)} AS {quote(c)}" for c in data)
        joins = " ".join(
            f'JOIN {quote(d["table"])} ON ' + " AND ".join(
                f'records.{quote(c)} = {quote(d["table"])}.{quote(c)}' for c in d["keys"]
            ) for d in dimensions
        )
        view = f"CREATE VIEW dataset AS SELECT {select} FROM records {joins};"
        con.execute(view)
        schema.append(view)
        timing["write_database"] = perf_counter() - started
        started = perf_counter()
        expected = Counter(data.itertuples(index=False, name=None))
        # Compare multisets, including duplicates, without relying on SQL row order.
        actual = Counter()
        cursor = con.execute("SELECT * FROM dataset")
        while True:
            batch = cursor.fetchmany(1000)
            if not batch:
                break
            actual.update(batch)
        if actual != expected:
            raise RuntimeError("Reconstruction mismatch; no output should be used.")
        if engine == "sqlite" and con.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed.")
        con.commit()
        if engine == "duckdb":
            con.execute("CHECKPOINT")
        timing["validate"] = perf_counter() - started
    except BaseException:
        con.close()
        database.unlink(missing_ok=True)
        raise
    else:
        con.close()
    started = perf_counter()
    (output / "schema.sql").write_text("\n".join(schema) + "\n", encoding="utf-8")
    with (output / "dataset.sql").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("BEGIN TRANSACTION;\n")
        stream.write("\n".join(schema[:-1]) + "\n")
        for name, table in table_data.items():
            table.to_csv(output / f"{name}.csv", index=False, lineterminator="\n")
            for row in table.itertuples(index=False, name=None):
                stream.write(f"INSERT INTO {quote(name)} VALUES (" + ", ".join(_literal(v, engine) for v in row) + ");\n")
        stream.write(schema[-1] + "\nCOMMIT;\n")
    timing["export"] = perf_counter() - started
    input_cells = len(data) * len(data.columns)
    stored_cells = sum(t["cells"] for t in table_profiles)
    database_bytes = database.stat().st_size
    report = {
        "version": "0.2.0", "source": source, "engine": engine, "miner": miner,
        "input_rows": len(data), "input_columns": len(data.columns), "columns": list(data),
        "duplicate_rows": int(data.duplicated().sum()),
        "blank_cells": sum(p["blank_count"] for p in profile),
        "column_profiles": profile, "cardinality": {p["name"]: p["distinct"] for p in profile},
        "dependencies": dependencies, "primary_key_candidates": keys, "selected_key": selected,
        "dimensions": dimensions, "records_columns": remaining,
        "tables": table_profiles, "table_rows": {t["name"]: t["rows"] for t in table_profiles},
        "input_cells": input_cells, "stored_cells": stored_cells,
        "cell_reduction_percent": round(100 * (1 - stored_cells / input_cells), 2),
        "database_bytes": database_bytes,
        "database_to_csv_ratio": round(database_bytes / source["bytes"], 3) if source["bytes"] else None,
        "reconstruction_exact": True, "row_order_preserved": False,
        "search": {"max_dependency_width": max_dependency_width, "max_key_width": max_key_width,
                   "max_candidate_columns": max_candidate_columns, "max_checks": max_checks,
                   "determinant_columns": search_columns, "dependency_checks": dependency_checks,
                   "key_checks": key_checks, "dependency_budget_reached": dependency_truncated,
                   "key_budget_reached": key_truncated},
        "timings_seconds": {k: round(v, 6) for k, v in timing.items()},
        "processing_seconds": round(sum(timing.values()), 6), "warnings": warnings,
    }
    (output / "schema.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "report.html").write_text(render_report(report), encoding="utf-8")
    return ConversionResult(output, database, report)
