"""Run from the repo: python3 -m examples.library_usage [--out results/my-run]."""

import argparse
import json
from pathlib import Path

from autoschema import convert_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default=str(Path(__file__).resolve().parents[1] / "data/retail_complex.csv")
    )
    parser.add_argument("--out", default="results/library-demo")
    args = parser.parse_args()
    result = convert_csv(args.csv, out=args.out, key_columns=["order_id", "line_number"])
    stats = result.summary()
    print(
        json.dumps(
            {
                key: stats[key]
                for key in [
                    "input_rows",
                    "input_columns",
                    "table_rows",
                    "cell_reduction_percent",
                    "database_bytes",
                    "reconstruction_exact",
                ]
            },
            indent=2,
        )
    )
    print("\nSales by category:")
    print(
        result.query(
            "SELECT category, SUM(quantity) AS units FROM dataset GROUP BY category ORDER BY units DESC"
        ).to_string(index=False)
    )
    print(f"\nOpen the visual report: {result.report_path}")


if __name__ == "__main__":
    main()
