"""Private database writing, exact verification and data exports."""

import itertools
from collections import Counter
from time import perf_counter

from ._database import _connect, _literal, quote
from ._inference import _sql_type
from .exceptions import ReconstructionError


def write_artifacts(data, dimensions, remaining, selected, output, engine, timing):
    """Write into a private staging directory and return physical table profiles."""
    database = output / ("dataset.sqlite" if engine == "sqlite" else "dataset.duckdb")
    table_data = {
        d["table"]: data[d["keys"] + d["attributes"]].drop_duplicates() for d in dimensions
    }
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
                    definitions.append(
                        f"FOREIGN KEY ({columns}) REFERENCES {quote(d['table'])} ({columns})"
                    )
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
            table_profiles.append(
                {
                    "name": name,
                    "rows": len(table),
                    "columns": list(table),
                    "primary_key": primary_key,
                    "foreign_keys": foreign_keys,
                    "cells": len(table) * len(table.columns),
                }
            )
        owners = {attribute: d["table"] for d in dimensions for attribute in d["attributes"]}
        select = ", ".join(
            f"{quote(owners.get(c, 'records'))}.{quote(c)} AS {quote(c)}" for c in data
        )
        joins = " ".join(
            f"JOIN {quote(d['table'])} ON "
            + " AND ".join(
                f"records.{quote(c)} = {quote(d['table'])}.{quote(c)}" for c in d["keys"]
            )
            for d in dimensions
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
            raise ReconstructionError("Reconstruction mismatch; no output should be used.")
        if engine == "sqlite" and con.execute("PRAGMA foreign_key_check").fetchall():
            raise ReconstructionError("Foreign-key validation failed.")
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
                stream.write(
                    f"INSERT INTO {quote(name)} VALUES ("
                    + ", ".join(_literal(v, engine) for v in row)
                    + ");\n"
                )
        stream.write(schema[-1] + "\nCOMMIT;\n")
    timing["export"] = perf_counter() - started
    return table_profiles, database.stat().st_size
