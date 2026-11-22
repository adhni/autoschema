"""Behavioral contracts for installed-package callers and persisted results."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from autoschema import (
    AutoSchemaError,
    ConfigurationError,
    InvalidDataError,
    InvalidResultError,
    MissingDependencyError,
    OutputExistsError,
    __version__,
    convert_csv,
    convert_dataframe,
    load_result,
    preview_csv,
    preview_dataframe,
)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.frame = pd.DataFrame(
            {"row_id": [1, 2, 3, 4], "group_id": ["A", "B"] * 2, "label": ["Alpha", "Beta"] * 2}
        )

    def convert(self, **kwargs):
        return convert_dataframe(self.frame, self.root / "result", **kwargs)

    def test_long_column_names_export_with_distinct_repeatable_table_names(self):
        from collections import Counter

        prefix = "customer_" + "x" * 260
        first, second = prefix + "_first_id", prefix + "_second_id"
        frame = pd.DataFrame(
            {
                "row_id": range(24),
                first: ["A", "B"] * 12,
                "city": ["London", "Paris"] * 12,
                second: ["C", "C", "D", "D"] * 6,
                "name": ["Amina", "Amina", "Yusuf", "Yusuf"] * 6,
            }
        )
        result = convert_dataframe(frame, self.root / "long", key_columns=["row_id"])
        dimensions = result.summary()["dimensions"]
        self.assertEqual(len(dimensions), 2)
        self.assertEqual(len({d["table"] for d in dimensions}), 2)
        for dimension in dimensions:
            self.assertLessEqual(len(dimension["table"]), 80)
            self.assertTrue((result.output_dir / (dimension["table"] + ".csv")).is_file())
        self.assertEqual(
            Counter(result.read_table().itertuples(index=False, name=None)),
            Counter(frame.itertuples(index=False, name=None)),
        )
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.executescript((result.output_dir / "dataset.sql").read_text(encoding="utf-8"))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM dataset").fetchone()[0], len(frame))
        self.assertEqual(preview_dataframe(frame, key_columns=["row_id"])["dimensions"], dimensions)

    def test_preview_matches_conversion_without_writing_or_opening_database(self):
        original = self.frame.copy(deep=True)
        with patch(
            "autoschema.core.write_artifacts", side_effect=AssertionError("database opened")
        ):
            plan = preview_dataframe(self.frame, key_columns=["row_id"])
        self.assertEqual(list(self.root.iterdir()), [])
        pd.testing.assert_frame_equal(self.frame, original)
        self.assertIsNone(plan["reconstruction_exact"])
        self.assertIsNone(plan["database_bytes"])
        self.assertIsNone(plan["database_to_csv_ratio"])
        self.assertNotIn("validate", plan["timings_seconds"])
        json.dumps(plan)
        converted = self.convert(key_columns=["row_id"]).summary()
        for key in (
            "tables",
            "table_rows",
            "dimensions",
            "selected_key",
            "dependencies",
            "input_cells",
            "stored_cells",
            "cell_reduction_percent",
            "search",
        ):
            self.assertEqual(plan[key], converted[key], key)

    def test_csv_preview_uses_csv_validation_and_does_not_require_optional_engine(self):
        source = self.root / "input.csv"
        self.frame.to_csv(source, index=False, sep=";")
        with patch.dict(sys.modules, {"duckdb": None}):
            plan = preview_csv(source, delimiter=";", engine="duckdb")
        self.assertEqual(plan["columns"], list(self.frame))
        self.assertEqual(list(self.root.iterdir()), [source])
        with self.assertRaises(InvalidDataError):
            preview_csv(source, delimiter=";", key_columns=["group_id"])
        with self.assertRaises(ConfigurationError):
            preview_csv(source, delimiter="||")
        with self.assertRaises(ConfigurationError):
            preview_dataframe(self.frame, max_checks=0)
        with self.assertRaises(TypeError):
            preview_dataframe("not a DataFrame")
        source.write_text("a,b\n1,2,3\n")
        with self.assertRaises(InvalidDataError):
            preview_csv(source)

    def test_cli_preview_json_and_text_leave_destination_untouched(self):
        source = self.root / "input.csv"
        self.frame.to_csv(source, index=False)
        output = self.root / "existing"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("keep")
        command = [
            sys.executable,
            "-m",
            "autoschema",
            str(source),
            "--preview",
            "--out",
            str(output),
        ]
        completed = subprocess.run(command + ["--json"], text=True, capture_output=True, check=True)
        self.assertIsNone(json.loads(completed.stdout)["reconstruction_exact"])
        completed = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertIn("Primary key:", completed.stdout)
        self.assertIn("No files written", completed.stdout)
        self.assertNotIn("PASS", completed.stdout)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(output.iterdir()), [sentinel])

    def test_reopen_result_after_moving_artifacts(self):
        result = self.convert()
        moved = self.root / "moved"
        result.output_dir.rename(moved)
        reopened = load_result(moved)
        self.assertEqual(reopened.summary(), result.summary())
        pd.testing.assert_frame_equal(reopened.read_table(), self.frame)
        pd.testing.assert_frame_equal(load_result(moved / "schema.json").read_table(), self.frame)
        self.assertEqual(reopened.output_dir, moved.resolve())

    def test_reports_are_defensive_copies(self):
        result = self.convert()
        for returned in (result.report, result.summary()):
            returned["engine"] = "bad"
            returned["table_rows"].clear()
            returned["columns"].append("injected")
        self.assertEqual(result.summary()["engine"], "sqlite")
        self.assertIn("records", result.tables)
        self.assertEqual(list(result.read_table()), list(self.frame))

    def test_query_binds_named_and_positional_parameters(self):
        result = self.convert()
        named = result.query(
            "SELECT row_id FROM dataset WHERE group_id = :group ORDER BY row_id", {"group": "A"}
        )
        positional = result.query(
            "SELECT row_id FROM dataset WHERE group_id = ? ORDER BY row_id", ["A"]
        )
        pd.testing.assert_frame_equal(named, positional)
        self.assertEqual(named["row_id"].tolist(), [1, 3])
        with self.assertRaises(sqlite3.OperationalError):
            result.query("UPDATE records SET row_id = 99")

    def test_invalid_options_fail_before_reading_or_creating_files(self):
        cases = [
            {"engine": "postgres"},
            {"max_dependency_width": True},
            {"max_dependency_width": 0},
            {"max_key_width": 4},
            {"max_key_width": False},
            {"max_checks": 0},
            {"max_checks": 1.5},
            {"max_candidate_columns": True},
            {"key_columns": "row_id"},
            {"key_columns": []},
            {"key_columns": [None]},
            {"key_columns": 4},
            {"delimiter": "\n"},
            {"delimiter": "\x00"},
            {"delimiter": "||"},
            {"miner": "desbordante"},
            {"encoding": None},
            {"encoding": ""},
        ]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ConfigurationError):
                convert_csv(self.root / "does-not-exist.csv", out=self.root / "result", **options)
        self.assertFalse((self.root / "result").exists())

    def test_typed_data_and_output_errors_remain_builtin_compatible(self):
        with self.assertRaises(InvalidDataError) as failure:
            convert_dataframe(pd.DataFrame({"x": []}), self.root / "empty")
        self.assertIsInstance(failure.exception, AutoSchemaError)
        self.assertIsInstance(failure.exception, ValueError)
        with self.assertRaises(InvalidDataError):
            self.convert(key_columns=["group_id"])
        result = self.convert()
        with self.assertRaises(OutputExistsError) as failure:
            self.convert()
        self.assertIsInstance(failure.exception, FileExistsError)
        self.assertTrue(result.database_path.is_file())

    def test_file_destination_is_not_replaced(self):
        output = self.root / "result"
        output.write_text("keep me")
        with self.assertRaises(OutputExistsError):
            self.convert()
        self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_failed_export_publishes_no_partial_results(self):
        for existing_empty in (False, True):
            with self.subTest(existing_empty=existing_empty):
                output = self.root / f"failure-{existing_empty}"
                if existing_empty:
                    output.mkdir()
                with patch.object(pd.DataFrame, "to_csv", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        convert_dataframe(self.frame, output)
                if existing_empty:
                    self.assertEqual(list(output.iterdir()), [])
                else:
                    self.assertFalse(output.exists())
                self.assertEqual(list(self.root.glob(".autoschema-*")), [])

    def test_failed_html_report_publishes_no_partial_results(self):
        with patch("autoschema.core.render_report", side_effect=OSError("report failure")):
            with self.assertRaisesRegex(OSError, "report failure"):
                self.convert()
        self.assertFalse((self.root / "result").exists())
        self.assertEqual(list(self.root.glob(".autoschema-*")), [])

    def test_competing_output_writer_is_not_overwritten(self):
        from autoschema.reporting import render_report

        output = self.root / "result"

        def competing_writer(report):
            output.mkdir()
            (output / "other.txt").write_text("other run")
            return render_report(report)

        with patch("autoschema.core.render_report", side_effect=competing_writer):
            with self.assertRaises(OutputExistsError):
                self.convert()
        self.assertEqual((output / "other.txt").read_text(encoding="utf-8"), "other run")
        self.assertFalse((output / "dataset.sqlite").exists())

    def test_missing_optional_engine_has_actionable_error(self):
        with patch.dict(sys.modules, {"duckdb": None}):
            with self.assertRaises(MissingDependencyError) as failure:
                self.convert(engine="duckdb")
        self.assertIsInstance(failure.exception, ImportError)
        self.assertIn("duckdb", str(failure.exception))
        self.assertFalse((self.root / "result").exists())

    def test_empty_existing_directory_is_supported(self):
        (self.root / "result").mkdir()
        result = self.convert()
        self.assertTrue(result.report_path.is_file())

    def test_legacy_report_without_format_version_can_be_loaded(self):
        result = self.convert()
        metadata = result.summary()
        metadata.pop("report_format_version")
        metadata["version"] = "0.2.0"
        (result.output_dir / "schema.json").write_text(json.dumps(metadata))
        pd.testing.assert_frame_equal(load_result(result.output_dir).read_table(), self.frame)

    def test_corrupt_and_incomplete_saved_results_are_rejected(self):
        result = self.convert()
        path = result.output_dir / "schema.json"
        original = result.summary()
        variants = [
            [],
            {},
            {**original, "engine": "bad"},
            {**original, "report_format_version": 99},
            {**original, "columns": []},
            {**original, "table_rows": {"records": -1}},
            {**original, "reconstruction_exact": False},
            {**original, "columns": ["wrong"]},
        ]
        for metadata in variants:
            path.write_text(json.dumps(metadata))
            with self.subTest(metadata=metadata), self.assertRaises(InvalidResultError):
                load_result(result.output_dir)
        path.write_text("not valid json")
        with self.assertRaises(InvalidResultError):
            load_result(result.output_dir)
        path.write_text(json.dumps(original))
        result.database_path.unlink()
        with self.assertRaises(InvalidResultError):
            load_result(result.output_dir)

    def test_cli_version_json_and_error_status_from_another_directory(self):
        version = subprocess.run(
            [sys.executable, "-m", "autoschema", "--version"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(version.stdout.strip(), f"autoschema {__version__}")
        source = self.root / "input.csv"
        self.frame.to_csv(source, index=False)
        command = [
            sys.executable,
            "-m",
            "autoschema",
            str(source),
            "--out",
            str(self.root / "cli"),
            "--json",
        ]
        completed = subprocess.run(
            command, cwd=self.root, text=True, capture_output=True, check=True
        )
        self.assertTrue(json.loads(completed.stdout)["reconstruction_exact"])
        repeated = subprocess.run(command, cwd=self.root, text=True, capture_output=True)
        self.assertEqual(repeated.returncode, 1)
        self.assertIn("not empty", repeated.stderr)
        self.assertNotIn("Traceback", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
