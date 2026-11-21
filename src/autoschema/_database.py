"""Private database connections and SQL quoting; optional engines are lazy imports."""

import sqlite3

from .exceptions import MissingDependencyError


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


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
        raise MissingDependencyError(
            "Install the optional engine with: python3 -m pip install duckdb"
        ) from exc
    return duckdb.connect(str(path), read_only=readonly)


def _literal(value, engine):
    if isinstance(value, str):
        if "\x00" in value:
            # SQL source cannot contain a literal NUL byte.
            function = "char" if engine == "sqlite" else "chr"
            return f" || {function}(0) || ".join(
                "'" + part.replace("'", "''") + "'" for part in value.split("\x00")
            )
        return "'" + value.replace("'", "''") + "'"
    return repr(value)
