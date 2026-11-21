import csv
import json
import random
import sqlite3
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

from autoschema import convert_csv, convert_dataframe
from autoschema.cli import main


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def convert(self, frame, **kwargs):
        return convert_dataframe(frame, out=self.root / "result", **kwargs)

    def assert_sql_roundtrip(self, result):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript((result.output_dir / "dataset.sql").read_text())
        actual = Counter(connection.execute("SELECT * FROM dataset").fetchall())
        expected = Counter(result.read_table().itertuples(index=False, name=None))
        self.assertEqual(actual, expected)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_composite_dependencies_and_primary_key(self):
        rows = []
        rng = random.Random(7)
        for order in range(25):
            for line in range(1, 5):
                product = rng.randrange(3)
                warehouse = rng.randrange(3)
                rows.append({"order_id": f"O{order}", "line_number": line,
                             "product_id": f"P{product}", "warehouse_id": f"W{warehouse}",
                             "bin": "AB"[(product + warehouse) % 2],
                             "quantity": (order + line) % 5 + 1})
        frame = pd.DataFrame(rows)
        result = self.convert(frame, key_columns=["order_id", "line_number"])
        matching = [d for d in result.report["dimensions"] if set(d["keys"]) == {"product_id", "warehouse_id"}]
        self.assertTrue(matching)
        self.assertIn("bin", matching[0]["attributes"])
        self.assertEqual(result.report["selected_key"], ["order_id", "line_number"])
        self.assertEqual(Counter(result.read_table().itertuples(index=False, name=None)), Counter(frame.itertuples(index=False, name=None)))
        self.assert_sql_roundtrip(result)

    def test_duplicate_rows_blanks_and_text_fidelity(self):
        frame = pd.DataFrame({
            "id": ["001", "001", "002", "003"],
            "value": ["1.00", "1.00", "", "NA"],
            "note": ["O'Brien, café\nnext line", "O'Brien, café\nnext line", "<script>alert(1)</script>", "a\x00b"],
            "huge": ["9223372036854775808", "9223372036854775808", "18446744073709551615", "0000"],
        })
        result = self.convert(frame)
        self.assertEqual(result.report["duplicate_rows"], 1)
        self.assertEqual(result.report["blank_cells"], 1)
        self.assertEqual(result.report["selected_key"], [])
        self.assertEqual(Counter(result.read_table().itertuples(index=False, name=None)), Counter(frame.itertuples(index=False, name=None)))
        self.assert_sql_roundtrip(result)
        self.assertFalse(b"\x00" in (result.output_dir / "dataset.sql").read_bytes())

    def test_conflicting_dependency_stays_in_records(self):
        frame = pd.DataFrame({"customer_id": ["A", "A", "B", "B", "A", "B"], "city": ["X", "Y", "X", "Y", "Y", "X"]})
        result = self.convert(frame)
        self.assertFalse(result.report["dimensions"])
        self.assertEqual(len(result.read_table()), 6)

    def test_dimension_keys_cannot_be_removed_by_later_dimensions(self):
        frame = pd.DataFrame([{"a_id": f"A{i % 4}", "b_id": f"B{i % 4}", "city": f"City {i % 4}", "row_id": i} for i in range(40)])
        result = self.convert(frame)
        for dimension in result.report["dimensions"]:
            self.assertTrue(set(dimension["keys"]).issubset(result.report["records_columns"]))
        self.assertEqual(result.report["selected_key"], ["row_id"])
        self.assert_sql_roundtrip(result)

    def test_auto_key_prefers_identifier_composite_over_measurement(self):
        frame = pd.DataFrame([{"order_id": f"O{o}", "line_number": line, "measurement": o * 3 + line + 0.5} for o in range(5) for line in range(3)])
        result = self.convert(frame)
        self.assertEqual(result.report["selected_key"], ["order_id", "line_number"])

    def test_explicit_invalid_key_and_existing_outputs_are_rejected(self):
        frame = pd.DataFrame({"id": ["A", "A"], "value": [1, 2]})
        with self.assertRaisesRegex(ValueError, "uniquely"):
            self.convert(frame, key_columns=["id"])
        result = self.convert(frame)
        before = result.database_path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.convert(frame)
        self.assertEqual(result.database_path.read_bytes(), before)

    def test_empty_and_ambiguous_headers_are_rejected(self):
        with self.assertRaises(ValueError):
            self.convert(pd.DataFrame({"x": []}))
        with self.assertRaises(ValueError):
            self.convert(pd.DataFrame([[1, 2]], columns=["x", "X"]))
        path = self.root / "bad.csv"
        path.write_text("x,x\n1,2\n")
        with self.assertRaises(ValueError):
            convert_csv(path, out=self.root / "bad")

    def test_csv_delimiter_and_unicode(self):
        path = self.root / "input.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(["id", "note"])
            writer.writerows([["001", "Café; A"], ["002", "a\nb"], ["003", "NA"]])
        result = convert_csv(path, out=self.root / "csv", delimiter=";")
        self.assertEqual(result.read_table()["note"].tolist(), ["Café; A", "a\nb", "NA"])
        self.assert_sql_roundtrip(result)

    def test_malformed_csv_and_nul_are_rejected(self):
        for name, contents in [("extra", "x,y\n1,2,3\n"), ("short", "x,y\n1\n"), ("nul", "x,y\n1,a\x00b\n")]:
            source = self.root / f"{name}.csv"
            source.write_text(contents)
            with self.assertRaises(ValueError):
                convert_csv(source, out=self.root / name)

    def test_shared_customer_attributes_are_not_duplicated_in_orders(self):
        rows = [{"order_id": f"O{o}", "customer_id": f"C{o % 3}", "customer_name": f"Customer {o % 3}", "city": f"City {o % 3}", "line_number": line, "quantity": (o + line) % 7} for o in range(20) for line in range(1, 4)]
        result = self.convert(pd.DataFrame(rows), key_columns=["order_id", "line_number"])
        dimension = next(d for d in result.report["dimensions"] if d["keys"] == ["customer_id"])
        self.assertIn("customer_name", dimension["attributes"])
        self.assert_sql_roundtrip(result)

    def test_unsafe_identifier_names_stay_inside_output_directory(self):
        frame = pd.DataFrame({"../../group_id": ["A", "B"] * 10, 'display "name"': ["Alpha", "Beta"] * 10, "row_id": range(20)})
        result = self.convert(frame)
        for table in result.tables:
            self.assertTrue((result.output_dir / f"{table}.csv").exists())
            self.assertNotIn("/", table)
        self.assert_sql_roundtrip(result)

    def test_search_budget_reported_and_dataframe_unchanged(self):
        frame = pd.DataFrame({"row_id": [1, 2, 3], "a": [None, "A", "B"], "b": [4, 4, 5]})
        before = frame.copy(deep=True)
        result = self.convert(frame, max_checks=1, max_candidate_columns=2)
        pd.testing.assert_frame_equal(frame, before)
        self.assertTrue(result.report["search"]["dependency_budget_reached"])
        self.assertTrue(any("limited" in w for w in result.report["warnings"]))
        self.assertEqual(result.report["blank_cells"], 1)

    def test_nullable_and_categorical_dataframe_values(self):
        frame = pd.DataFrame({
            "row_id": [1, 2, 3],
            "count": pd.Series([1, None, 2], dtype="Int64"),
            "flag": pd.Series([True, None, False], dtype="boolean"),
            "category": pd.Series(["A", None, "B"], dtype="category"),
            "signed_zero": ["-0.0", "0.0", "1.0"],
        })
        before = frame.copy(deep=True)
        result = self.convert(frame)
        actual = result.read_table()
        self.assertEqual(actual["count"].tolist(), ["1", "", "2"])
        self.assertEqual(actual["flag"].tolist(), ["True", "", "False"])
        self.assertEqual(actual["category"].tolist(), ["A", "", "B"])
        self.assertEqual(actual["signed_zero"].tolist(), ["-0.0", "0.0", "1.0"])
        pd.testing.assert_frame_equal(frame, before)
        self.assert_sql_roundtrip(result)

    def test_three_column_dependency_search(self):
        rows = []
        for repeat in range(6):
            for a in range(2):
                for b in range(2):
                    for c in range(2):
                        rows.append({"a_id": a, "b_id": b, "c_id": c, "row_id": len(rows), "parity": str((a + b + c) % 2)})
        result = self.convert(pd.DataFrame(rows), max_dependency_width=3)
        dimension = next(d for d in result.report["dimensions"] if len(d["keys"]) == 3)
        self.assertEqual(dimension["keys"], ["a_id", "b_id", "c_id"])
        self.assert_sql_roundtrip(result)

    def test_summary_profiles_and_report_links(self):
        result = self.convert(pd.DataFrame({"row_id": [1, 2, 3], '<unsafe & "name">': [4, 4, 8]}))
        stats = result.summary()
        self.assertEqual(stats["column_profiles"][1]["mean"], 16 / 3)
        self.assertEqual(json.loads((result.output_dir / "schema.json").read_text()), stats)
        self.assertEqual(stats["input_cells"], 6)
        self.assertEqual(stats["stored_cells"], sum(t["cells"] for t in stats["tables"]))
        stats["input_rows"] = 100
        self.assertEqual(result.summary()["input_rows"], 3)
        html = result.report_path.read_text()
        self.assertIn("&lt;unsafe &amp; &quot;name&quot;&gt;", html)

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.links.extend(v for k, v in attrs if k == "href")

        links = Links()
        links.feed(html)
        for link in links.links:
            self.assertTrue((result.output_dir / link).exists(), link)

    def test_query_cannot_mutate_database(self):
        result = self.convert(pd.DataFrame({"id": [1, 2], "value": [3, 4]}))
        with self.assertRaises(sqlite3.OperationalError):
            result.query("DELETE FROM records")
        self.assertEqual(len(result.read_table()), 2)
        with self.assertRaises(ValueError):
            result.read_table("not_a_table")

    def test_duckdb_export_and_query(self):
        try:
            import duckdb
        except ImportError:
            self.skipTest("Optional DuckDB is not installed")
        frame = pd.DataFrame({"id": [1, 2, 3], "note": ["a\x00b", "O'Brien", ""]})
        result = self.convert(frame, engine="duckdb")
        self.assertEqual(result.read_table()["note"].tolist(), list(frame["note"]))
        con = duckdb.connect(":memory:")
        self.addCleanup(con.close)
        con.execute((result.output_dir / "dataset.sql").read_text())
        self.assertEqual(Counter(con.execute("SELECT * FROM dataset").fetchall()), Counter(frame.itertuples(index=False, name=None)))

    def test_cli_errors_are_actionable(self):
        from contextlib import redirect_stderr
        from io import StringIO
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = main([str(self.root / "missing.csv"), "--out", str(self.root / "cli")])
        self.assertEqual(code, 1)
        self.assertIn("autoschema:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
