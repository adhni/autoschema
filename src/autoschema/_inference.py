"""Private normalization, profiling and bounded schema-inference algorithms."""

import itertools
import math
import re

import pandas as pd

from .exceptions import InvalidDataError


def _sql_type(series):
    if pd.api.types.is_integer_dtype(series):
        return "BIGINT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE"
    return "VARCHAR"


def _normalize(frame):
    if frame.empty or not len(frame.columns):
        raise InvalidDataError("The dataset must contain at least one row and one column.")
    columns = list(frame.columns)
    if any(not isinstance(c, str) or not c.strip() or "\x00" in c for c in columns):
        raise InvalidDataError("Column names must be nonempty strings.")
    if len({c.casefold() for c in columns}) != len(columns):
        raise InvalidDataError("Column names must be unique, ignoring case, for SQL compatibility.")
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
        result[column] = (
            numeric if (integer or decimal) and numeric.astype(str).equals(text) else text
        )
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
                c
                for c in frame
                if c not in keys
                and cardinality[c] > 1
                and not any(set(k).issubset(keys) for k in determinants_by_attribute[c])
            ]
            if not candidates:
                continue
            maxima = grouped[candidates].nunique(dropna=False).max()
            attributes = [c for c in candidates if maxima[c] == 1]
            if attributes:
                dependencies.append(
                    {"keys": list(keys), "attributes": attributes, "distinct_keys": count}
                )
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
            if set(bridge["keys"]).issubset(set(dependency["keys"]) | attributes) and not set(
                dependency["keys"]
            ).issubset(set(bridge["keys"]) | set(bridge["attributes"])):
                attributes.difference_update(bridge["attributes"])
        direct.append(
            {**dependency, "attributes": [c for c in dependency["attributes"] if c in attributes]}
        )
    while True:
        options = []
        for index, dependency in enumerate(direct):
            keys = dependency["keys"]
            if not set(keys).issubset(remaining):
                continue
            attributes = [
                c for c in dependency["attributes"] if c in remaining and c not in protected
            ]
            savings = (len(frame) - dependency["distinct_keys"]) * len(attributes) - dependency[
                "distinct_keys"
            ] * len(keys)
            if attributes and savings > 0:
                options.append(
                    (
                        savings,
                        sum(_identifier(c) for c in keys),
                        -len(keys),
                        -index,
                        keys,
                        attributes,
                    )
                )
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
        dimensions.append(
            {"table": name, "keys": keys, "attributes": attributes, "cells_saved": savings}
        )
        protected.update(keys)
        remaining = [c for c in remaining if c not in attributes]
    return remaining, dimensions


def _find_keys(frame, columns, max_width, max_checks, explicit):
    if explicit:
        if len(set(explicit)) != len(explicit) or not set(explicit).issubset(frame.columns):
            raise InvalidDataError("key_columns must contain distinct existing column names.")
        if any((frame[c] == "").any() for c in explicit) or frame.duplicated(list(explicit)).any():
            raise InvalidDataError(
                "key_columns must uniquely identify every row and contain no blanks."
            )
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
    keys.sort(
        key=lambda key: (
            not any(_identifier(c) for c in key),
            len(key),
            -sum(_identifier(c) for c in key),
        )
    )
    return keys, checks, truncated
