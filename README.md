# AutoSchema

Turn a CSV or pandas DataFrame into inferred relational SQL tables, a reconstruction view, readable exports, and a visual processing report. Use it as a Python library or from the command line. SQLite works with just pandas; DuckDB is optional.

## Start here

An already-run, synthetic retail example is in **[`results/retail-demo/`](results/retail-demo/)**. Open **[`report.html`](results/retail-demo/report.html)** in your browser to see the pipeline, inferred table relationships, column profiles, processing times, and before/after storage statistics. No server or internet connection is needed. The folder also contains the SQL tables as CSVs and a complete SQL export with inserts.

The sample has **4,800 rows × 23 columns** covering customers, orders, order lines, products, warehouses, and inventory locations. It includes blank delivery notes, Unicode, apostrophes, and postcodes with leading zeros. With the default search it produces six physical tables and a `dataset` view that reconstructs all input rows exactly. This is synthetic test data, not a real-world benchmark.

For a guided introduction, open **[`notebooks/autoschema_walkthrough.ipynb`](notebooks/autoschema_walkthrough.ipynb)**. It walks through CSV and DataFrame conversion, summary statistics, inferred keys and relationships, SQL queries, charts, the visual report, and reconstruction verification. Setup instructions are included in the notebook; each run saves to a fresh folder under `results/notebook-runs/`.

## Installation

Python 3.9 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
# Optional second database engine:
python -m pip install -e '.[duckdb]'
```

Use `python -m pip install .` for a regular installation or `python -m pip install -e .` for development. Optional notebook tools are available with `python -m pip install -e '.[notebook]'`, and contributor tools with `python -m pip install -e '.[dev,duckdb]'`. This is a local source package; no PyPI publication is implied.

The package uses a `src/` layout. Install it into your active interpreter before importing it, including when working from the repository root. Dependencies and extras are declared in `pyproject.toml`; `requirements.txt` is a compatibility entry point for the same editable installation.

## Python library

```python
from autoschema import convert_csv

result = convert_csv(
    "data/retail_complex.csv",
    out="results/my-retail-run",  # new or empty directory
    key_columns=["order_id", "line_number"],  # optional domain key
)

stats = result.summary()  # JSON-serializable dictionary
print(stats["table_rows"])
print(stats["cell_reduction_percent"])
print(stats["reconstruction_exact"])
print(result.report_path)  # open this HTML file in your browser

customers = result.read_table("dim_customer_id")  # pandas DataFrame
sales = result.query("""
    SELECT category, SUM(quantity) AS units
    FROM dataset
    GROUP BY category
    ORDER BY units DESC
""")
print(sales)
```

For a DataFrame already in memory:

```python
import pandas as pd
from autoschema import convert_dataframe

frame = pd.DataFrame(
    {
        "row_id": [1, 2, 3, 4, 5, 6],
        "customer_id": ["C01", "C02", "C01", "C02", "C01", "C02"],
        "customer_name": ["Amina", "Yusuf", "Amina", "Yusuf", "Amina", "Yusuf"],
    }
)
result = convert_dataframe(frame, out="results/my-frame", key_columns=["row_id"])
print(result.read_table())  # defaults to the complete dataset view
```

The input DataFrame is not modified. Values are normalized to CSV-style strings and conservatively inferred as numeric; missing DataFrame values become empty strings. This preserves logical CSV values, not arbitrary pandas dtypes or Python objects. `result.tables` lists physical tables, `result.database_path` points to the database, and `result.query(sql, parameters)` runs read-only queries without retaining a connection. `summary()` returns an independent dictionary.

Reopen saved results in a later session without rerunning conversion:

```python
from autoschema import load_result

result = load_result("results/my-retail-run")
print(result.query("SELECT COUNT(*) AS rows FROM dataset"))
```

Public methods are annotated and the distribution includes a `py.typed` marker. Conversion failures have documented exception types, and failed runs clean up staged artifacts before any complete result is published. See the [API reference](docs/api.md) for parameters, summaries, errors and saved-result compatibility, and the [changelog](CHANGELOG.md) for migration details.

A runnable example is included:

```sh
python3 -m examples.library_usage --out results/library-run
```

## Command line

```sh
# Defaults: SQLite, pandas, dependencies and keys up to two columns.
python3 -m autoschema data/retail_complex.csv --out results/retail-run

# Give an explicit primary key and print the full statistics as JSON.
python3 -m autoschema data/retail_complex.csv --out results/retail-keyed \
  --key order_id line_number --json

# Optional DuckDB engine.
python3 -m autoschema data/retail_complex.csv --out results/retail-duckdb --engine duckdb

# Larger bounded search for a different dataset; costs more CPU and memory.
python3 -m autoschema your.csv --out results/your-run \
  --max-dependency-width 3 --max-key-width 3 \
  --max-candidate-columns 40 --max-checks 5000

# Semicolon-separated input.
python3 -m autoschema your.csv --delimiter ';' --out results/semicolon-run
```

After installation, `autoschema ...` is equivalent to `python3 -m autoschema ...`. The standalone `autoschema.py` runner was retired in 0.3 to avoid shadowing the installed package; use either supported entry point. Defaults now use SQLite/pandas, so Desbordante is not required. The old `--miner desbordante` flag returns an explicit unsupported-adapter error; no Desbordante results are claimed.

Use a **new or empty output directory** for every run. AutoSchema refuses to overwrite any existing artifacts. `results/` is visible and tracked by Git; `output/` is ignored and may be hidden by editor settings.

## Outputs and statistics

Every successful run writes:

| File | Contents |
| --- | --- |
| `dataset.sqlite` or `dataset.duckdb` | Physical tables, primary/foreign keys, and the joining `dataset` view |
| `report.html` | Self-contained visual pipeline, schema cards, reduction charts, searchable column profiles, timings and inference limits |
| `schema.json` | Full machine-readable summary |
| `schema.sql` | Table and view definitions |
| `dataset.sql` | Definitions plus data inserts, for the selected engine |
| `records.csv`, `dim_*.csv` | Readable copies of each physical table |

The summary includes row/column counts, duplicate rows, blank cells, inferred types, cardinalities, numeric min/mean/max, discovered dependencies, key candidates, chosen dimensions, table sizes, search bounds, stage timings, and exact reconstruction validation.

`cell_reduction_percent` compares input rows × columns with the sum of physical table rows × columns, including their keys. It measures repeated values removed. `database_bytes` and `database_to_csv_ratio` report the actual database file size, separately. A normalized database can be **larger** than its CSV because of indexes and database overhead; this is not guaranteed byte compression. SQL and CSV export sizes are excluded from that ratio. Processing time includes reading, profiling, discovery, planning, database writing, verification and data exports; report rendering is excluded.

To inspect the demo in your terminal:

```sh
sqlite3 -header -column results/retail-demo/dataset.sqlite \
  'SELECT * FROM dataset LIMIT 5;'

# Restore the complete SQLite SQL export into a new database:
sqlite3 restored.sqlite < results/retail-demo/dataset.sql
```

## How inference works

1. Read the CSV with strict field-count and header checks. Keep empty fields, literal `NA`, leading zeros, and text formatting intact. Infer integers/decimals only when conversion round-trips to the same text and fits the SQL type.
2. Profile types, distinct values, blanks, duplicates and numeric ranges.
3. Search for exact functional dependencies: for example, `customer_id → customer_name, customer_city`, or `(product_id, warehouse_id) → bin_location, reorder_point`. Conflicting mappings are not treated as dependencies. Blank determinants are excluded.
4. Prefer direct relationships over transitive ones and greedily move repeated attributes into dimensions when doing so reduces stored cells. Keep dimension keys in `records` for joins. This produces a star-shaped schema rather than arbitrary recursive normalization.
5. Detect primary keys, preferring identifier-like column names over accidentally unique measurements. An explicit `key_columns` / `--key` is validated and kept in `records`.
6. Write primary and foreign keys, build the `dataset` joining view, and compare the reconstructed rows to the normalized input as multisets. Duplicates and column order are preserved; SQL row order is unspecified.
7. Export SQL/CSV files, summary statistics, and the report.

Dependencies are heuristics inferred from this file, not proven domain rules. Equivalent determinants can produce different valid schemas; the greedy plan is not guaranteed optimal or a full 3NF/BCNF decomposition. Constant attributes remain in the fact table. No primary key is imposed if none is found within the search bounds. Inference does not approximate noisy dependencies, repair data, or infer relationships across multiple source files.

The implementation loads the entire dataset and reconstruction counters into memory. It is intended for exploratory datasets that fit in RAM, not unbounded files. Dependency/key widths default to two (maximum three), candidate determinant columns to 30, and candidate checks to 2,000 per search. Identifiers receive priority when a column budget applies. The report discloses budget limits and warnings. Increase bounds deliberately on wide datasets. CSV NUL characters, duplicate/case-colliding headers, malformed records, and empty datasets are rejected.

## Reproduce and test

```sh
# Deterministic synthetic retail data, seed 42; four lines per order.
python3 examples/generate_retail.py
python3 -m autoschema data/retail_complex.csv --out results/new-demo

# Increase complexity/row count; still must fit in memory.
python3 examples/generate_retail.py --orders 10000 --out data/retail_larger.csv

# Install development tools and run the checks.
python3 -m pip install -e '.[dev,duckdb]'
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest --cov
```

Tests cover composite dependencies and keys, duplicate preservation, conflicting mappings, transitive relationships, lexical values, Unicode, SQL dump restoration, output protection, bounded searches, read-only queries and report links. SQLite and optional DuckDB are exercised. The original Gapminder sample remains in `data/gapminder.csv`; historical exports are in `examples/result/` and the root of `results/`.

Gapminder source: historical country observations distributed in [Plotly sample datasets](https://github.com/plotly/datasets). The retail sample is generated locally by `examples/generate_retail.py` and contains no real customer information.

Build and release-verification instructions are in [CONTRIBUTING.md](CONTRIBUTING.md). CI configuration checks installed-package behavior, supported-version combinations, source/wheel builds and distribution metadata.
