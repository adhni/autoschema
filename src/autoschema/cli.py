"""Command-line interface shared by all supported entry points."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Optional

from ._version import __version__
from .core import convert_csv
from .exceptions import AutoSchemaError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="autoschema",
        description="Infer SQL tables from CSV, verify reconstruction, and write a visual report.",
    )
    parser.add_argument("--version", action="version", version=f"autoschema {__version__}")
    parser.add_argument("csv", help="Path to the input CSV")
    parser.add_argument("--out", default="output", help="Empty output directory (default: output)")
    parser.add_argument("--engine", choices=["sqlite", "duckdb"], default="sqlite")
    parser.add_argument(
        "--miner",
        choices=["pandas", "desbordante"],
        default="pandas",
        help="Dependency miner; Desbordante is reserved and currently unsupported",
    )
    parser.add_argument(
        "--max-dependency-width",
        type=int,
        default=2,
        help="Maximum determinant width, 1–3 (default: 2)",
    )
    parser.add_argument(
        "--max-key-width",
        type=int,
        default=2,
        help="Maximum primary-key search width, 1–3 (default: 2)",
    )
    parser.add_argument("--max-candidate-columns", type=int, default=30)
    parser.add_argument(
        "--max-checks", type=int, default=2000, help="Maximum candidates per dependency/key search"
    )
    parser.add_argument(
        "--key",
        nargs="+",
        dest="key_columns",
        help="Explicit primary-key columns, e.g. --key order_id line_number",
    )
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--json", action="store_true", help="Print the full JSON summary")
    args = vars(parser.parse_args(argv))
    print_json = args.pop("json")
    source = args.pop("csv")
    try:
        result = convert_csv(source, **args)
    except (AutoSchemaError, OSError, ValueError) as exc:
        print(f"autoschema: {exc}", file=sys.stderr)
        return 1
    report = result.report
    if print_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"Converted {report['input_rows']:,} rows × {report['input_columns']} columns into {len(report['tables'])} SQL tables."
        )
        for table in report["tables"]:
            print(f"  {table['name']}: {table['rows']:,} rows × {len(table['columns'])} columns")
        print(
            f"Exact reconstruction: PASS | Stored cells reduced: {report['cell_reduction_percent']:.1f}% | Processing: {report['processing_seconds']:.3f}s"
        )
        print(f"Database: {result.database_path}")
        print(f"Visual report: {result.report_path}")
        print(f"SQL + CSV exports: {result.output_dir}")
    return 0
