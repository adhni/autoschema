# AutoSchema

Convert a CSV into inferred relational SQL tables and a reconstruction view named `dataset`.

## Setup

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python autoschema.py data/gapminder.csv
```

Use your own CSV by replacing the path. Use `--out output2` for subsequent runs; existing databases are not overwritten.

## Verified sample runs

```sh
python3 -m pip install pandas duckdb
python3 autoschema.py data/gapminder.csv --engine sqlite --miner pandas --out output/sqlite
python3 autoschema.py data/gapminder.csv --engine duckdb --miner pandas --out output/duckdb
```

Both runs were verified with the included Gapminder sample: 1,704 input rows, 142 countries, and exact reconstruction (`reconstruction_exact: true`). Each produces a `records` table with 1,704 rows, a `dim_country` table with 142 rows, and a `dataset` view with the original eight columns.

Outputs: `dataset.sqlite` or `dataset.duckdb`, `schema.sql` (DDL), and `schema.json` (profiling and validation), in the selected output directory. Generated `output/` files are ignored by Git. Use a new `--out` directory when repeating a run; existing databases are not overwritten. Query the reconstruction view, for example:

```sql
SELECT country, year, lifeExp FROM dataset ORDER BY country, year LIMIT 5;
```

The included example in `examples/result` is the SQLite/pandas run. The Desbordante miner remains untested; the verified commands above use pandas. Inference is heuristic: unique numeric measurements may be selected as keys, composite dependencies are not decomposed, and performance is not benchmarked. The implementation loads the CSV into memory. Normalizing repeated attributes does not guarantee a smaller file than the CSV. Review inferred relationships before production use.

Sample data: Gapminder historical country observations, distributed in Plotly Express sample datasets (https://github.com/plotly/datasets).
