"""Shared offline CSV contracts for Python and native R; execute with --help."""

import argparse
import csv
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from autoschema import InvalidDataError, __version__, convert_csv, load_result, preview_csv

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "r/autoschemaR/inst/validation"


def cases(fixtures=FIXTURES):
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    if manifest["format_version"] != 1:
        raise ValueError("Unsupported shared fixture manifest.")
    return manifest["cases"]


def source_rows(case, fixtures=FIXTURES):
    path = fixtures / case["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["sha256"], (
        f"Changed fixture: {path}"
    )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(
            stream, delimiter=case.get("options", {}).get("delimiter", ","), strict=True
        )
        columns = next(reader)
        rows = [tuple(row) for row in reader if row]
    return columns, rows


def lexical_rows(rows):
    # CSV conversions infer numbers only when their spelling round-trips safely.
    return Counter(tuple(str(value) for value in row) for row in rows)


def physical_csv_rows(rows, types):
    """Compare numeric exports exactly as typed values; text spelling stays exact."""

    def value(item, sql_type):
        if sql_type in ("INTEGER", "BIGINT"):
            return ("integer", Decimal(str(item)))
        if sql_type == "DOUBLE":
            return ("double", float(item).hex())
        return ("text", str(item))

    result = Counter()
    for row in rows:
        assert len(row) == len(types), "Physical CSV record has the wrong field count."
        result[tuple(value(item, sql_type) for item, sql_type in zip(row, types))] += 1
    return result


def has_dependency(report, dependency):
    return any(
        set(item["keys"]) == set(dependency["keys"])
        and set(dependency["attributes"]).issubset(item["attributes"])
        for item in report["dependencies"]
    )


def validate_output(case, output, fixtures=FIXTURES):
    """Use stdlib CSV/SQLite, independently of either library's reconstruction code."""
    columns, expected_rows = source_rows(case, fixtures)
    expected = lexical_rows(expected_rows)
    metadata = json.loads((output / "schema.json").read_text(encoding="utf-8"))
    assert metadata["reconstruction_exact"] is True
    assert metadata["columns"] == columns
    assert metadata["input_rows"] == len(expected_rows)
    assert metadata["input_columns"] == len(columns)
    assert metadata["blank_cells"] == case["expected"]["blank_cells"]
    assert metadata["duplicate_rows"] == case["expected"]["duplicate_rows"]
    assert columns == case["expected"]["columns"]
    assert len(expected_rows) == case["expected"]["rows"]
    connection = sqlite3.connect((output / "dataset.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        assert lexical_rows(connection.execute("SELECT * FROM dataset")) == expected, (
            "Database changed logical CSV values or duplicate multiplicities."
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        for table, count in metadata["table_rows"].items():
            quoted = '"' + table.replace('"', '""') + '"'
            assert connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0] == count
            cursor = connection.execute(f"SELECT * FROM {quoted}")
            declared_types = [
                row[2].upper() for row in connection.execute(f"PRAGMA table_info({quoted})")
            ]
            with (output / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
                exported = csv.reader(stream, strict=True)
                assert next(exported) == [column[0] for column in cursor.description]
                assert physical_csv_rows(exported, declared_types) == physical_csv_rows(
                    cursor, declared_types
                ), "Physical CSV export changed values."
    finally:
        connection.close()
    connection = sqlite3.connect(":memory:")
    try:
        with (output / "dataset.sql").open(encoding="utf-8", newline="") as stream:
            connection.executescript(stream.read())
        assert lexical_rows(connection.execute("SELECT * FROM dataset")) == expected, (
            "SQL export changed logical values."
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    reopened = load_result(output)
    assert lexical_rows(reopened.read_table().itertuples(index=False, name=None)) == expected
    assert (output / "report.html").is_file()
    assert (output / "schema.sql").is_file()
    options = case.get("options", {})
    if "key_columns" in options:
        assert metadata["selected_key"] == options["key_columns"]
    for dependency in case.get("required_dependencies", []):
        assert has_dependency(metadata, dependency), f"Missing dependency: {dependency}"
    for dependency in case.get("forbidden_dependencies", []):
        assert not has_dependency(metadata, dependency), (
            f"Accepted conflicting mapping: {dependency}"
        )
    if "expected_dimensions" in case:
        assert len(metadata["dimensions"]) == case["expected_dimensions"]
    if case.get("expect_search_warning"):
        assert any(
            "budget" in warning.lower() or "limited" in warning.lower()
            for warning in metadata["warnings"]
        )
    assert metadata["search"]["dependency_checks"] <= options.get("max_checks", 2000)
    assert metadata["search"]["key_checks"] <= options.get("max_checks", 2000)
    assert metadata["stored_cells"] == sum(
        t["rows"] * len(t["columns"]) for t in metadata["tables"]
    )
    return metadata


def check_python_case(case, parent, fixtures=FIXTURES):
    source = fixtures / case["file"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == case["sha256"]
    output = parent / case["id"]
    options = case.get("options", {})
    if case.get("expected_error"):
        for operation in (
            lambda: preview_csv(source, **options),
            lambda: convert_csv(source, output, **options),
        ):
            try:
                operation()
            except InvalidDataError:
                pass
            else:
                raise AssertionError("Invalid input was accepted.")
        assert not output.exists()
        return {"id": case["id"], "status": "pass", "outcome": "rejected_invalid_data"}
    preview = preview_csv(source, **options)
    assert preview["reconstruction_exact"] is None
    assert preview["database_bytes"] is None
    assert not output.exists()
    started = time.perf_counter()
    result = convert_csv(source, output, **options)
    elapsed = time.perf_counter() - started
    report = validate_output(case, output, fixtures)
    for key in ("tables", "table_rows", "selected_key", "dimensions", "stored_cells"):
        assert preview[key] == report[key], f"Preview/conversion mismatch: {key}"
    return {
        "id": case["id"],
        "status": "pass",
        "outcome": "converted",
        "conversion_seconds": round(elapsed, 6),
        "rows": report["input_rows"],
        "columns": report["input_columns"],
        "tables": len(result.tables),
        "cell_reduction_percent": report["cell_reduction_percent"],
    }


def write_report(output, report):
    comparisons = {}
    native_index = {case["id"]: case for case in report.get("r", {}).get("cases", [])}
    for case in report["python"]:
        native = native_index.get(case["id"], {})
        if (
            case["status"] != "pass"
            or native.get("status") != "pass"
            or case.get("outcome") != "converted"
        ):
            continue
        reports = [
            json.loads((output / engine / case["id"] / "schema.json").read_text(encoding="utf-8"))
            for engine in ("python", "r")
        ]

        def grouping(item):
            return (
                sorted(item["records_columns"]),
                sorted((sorted(d["keys"]), sorted(d["attributes"])) for d in item["dimensions"]),
            )

        python_types, r_types = [
            {p["name"]: p["sql_type"] for p in item["column_profiles"]} for item in reports
        ]
        comparisons[case["id"]] = {
            "schema_grouping_equal": grouping(reports[0]) == grouping(reports[1]),
            "table_names_equal": set(reports[0]["table_rows"]) == set(reports[1]["table_rows"]),
            "selected_keys_equal": reports[0]["selected_key"] == reports[1]["selected_key"],
            "declared_sql_type_differences": [
                {"column": column, "python": python_types[column], "r": r_types[column]}
                for column in python_types
                if python_types[column] != r_types[column]
            ],
        }
    report["comparisons"] = comparisons
    (output / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Shared Python/R validation",
        "",
        f"Python package: {__version__}; Python: {platform.python_version()}; platform: {platform.platform()}.",
        f"R package: {report.get('r', {}).get('package_version', 'not run')}; R: {report.get('r', {}).get('r_version', 'not run')}.",
        "",
        "Conversion times are single observations, excluding preview, validation-runner checks and R startup. These small fixtures do not establish scale limits.",
        "",
        "| Case | Python | R | Python seconds | R seconds | Schema grouping |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    r_index = {case["id"]: case for case in report.get("r", {}).get("cases", [])}
    for py in report["python"]:
        native = r_index.get(py["id"], {})
        comparison = comparisons.get(py["id"])
        grouping_status = (
            "-"
            if comparison is None
            else "same"
            if comparison["schema_grouping_equal"]
            else "different"
        )
        lines.append(
            f"| {py['id']} | {py['status']} | {native.get('status', 'not run')} | {py.get('conversion_seconds', '-')} | {native.get('conversion_seconds', '-')} | {grouping_status} |"
        )
    lines.extend(
        [
            "",
            "Both implementations must preserve logical CSV values and row multiplicities, including in complete SQL exports. SQL types, table names and complete inferred schemas may differ.",
            "For invalid cases, pass means that preview and conversion both rejected the input without publishing output.",
            "Schema grouping compares column assignments and determinant/attribute sets, ignoring table names and ordering. Detailed name, key and SQL declaration differences are in summary.json; INTEGER versus BIGINT is a declaration difference, not a data-loss finding.",
            "",
        ]
    )
    errors = []
    if report.get("r", {}).get("error"):
        errors.append("R worker: " + report["r"]["error"])
    for engine, items in (
        ("Python", report["python"]),
        ("R", report.get("r", {}).get("cases", [])),
    ):
        errors.extend(
            f"{engine} {item['id']}: {item.get('error', 'failed')}"
            for item in items
            if item["status"] != "pass"
        )
    if errors:
        lines.extend(["Failures:", "", "```text", "\n".join(errors), "```", ""])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory for case artifacts and summaries"
    )
    parser.add_argument("--python-only", action="store_true", help="Run without an R installation")
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument(
        "--r-library", type=Path, help="Optional library containing an installed autoschemaR"
    )
    args = parser.parse_args(argv)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_package": __version__,
        "platform": platform.platform(),
        "python": [],
        "all_passed": False,
        "r_skipped": args.python_only,
    }
    python_dir = output / "python"
    python_dir.mkdir()
    for case in cases():
        try:
            outcome = check_python_case(case, python_dir)
        except Exception as exc:
            outcome = {"id": case["id"], "status": "fail", "error": f"{type(exc).__name__}: {exc}"}
        report["python"].append(outcome)
        print(f"Python {case['id']}: {outcome['status']}", flush=True)
    if not args.python_only:
        native_dir = output / "r"
        native_dir.mkdir()
        env = os.environ.copy()
        if args.r_library:
            env["R_LIBS_USER"] = str(args.r_library.resolve())
        try:
            completed = subprocess.run(
                [
                    args.rscript,
                    "--vanilla",
                    str(REPO / "scripts/shared_validation.R"),
                    str(FIXTURES),
                    str(native_dir),
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            completed = None
            report["r"] = {"status": "fail", "error": str(exc)}
        if completed is None:
            pass
        elif completed.returncode:
            report["r"] = {"status": "fail", "error": completed.stderr[-4000:]}
        elif (native_dir / "summary.json").is_file():
            report["r"] = json.loads((native_dir / "summary.json").read_text(encoding="utf-8"))
            for case, outcome in zip(cases(), report["r"]["cases"]):
                assert case["id"] == outcome["id"]
                if outcome["status"] == "pass" and not case.get("expected_error"):
                    try:
                        validate_output(case, native_dir / case["id"])
                    except Exception as exc:
                        outcome.update(
                            status="fail", error=f"Independent oracle: {type(exc).__name__}: {exc}"
                        )
                print(f"R {case['id']}: {outcome['status']}", flush=True)
        else:
            report["r"] = {"status": "fail", "error": "R runner did not write its summary."}
    python_ok = all(case["status"] == "pass" for case in report["python"])
    r_ok = args.python_only or (
        len(report.get("r", {}).get("cases", [])) == len(cases())
        and all(case["status"] == "pass" for case in report["r"]["cases"])
    )
    report["all_passed"] = python_ok and r_ok
    write_report(output, report)
    print(f"Summary: {output / 'summary.md'}", flush=True)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
