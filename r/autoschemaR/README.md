# autoschemaR

A native R implementation of AutoSchema. Preview inferred tables, convert CSVs
or R data frames into SQLite, inspect summary statistics, draw base R charts,
and open a self-contained HTML processing report. No Python or reticulate is used.

This is a development package, version **0.1.0.9000**, and is not published on CRAN.
SQLite is supported in this first version; DuckDB and per-relationship editing
are not implemented.

## Install

From the repository root:

```r
install.packages(c("DBI", "RSQLite", "jsonlite", "readr"))
install.packages("r/autoschemaR", repos = NULL, type = "source")
```

Or install the package subdirectory from GitHub:

```r
install.packages("remotes")
remotes::install_github("adhni/autoschema", subdir = "r/autoschemaR")
```

R 4.1 or newer is required. Source installation of dependencies may require the
usual R build tools when compatible binary packages are unavailable.

## Preview, convert and query

```r
library(autoschemaR)

orders <- data.frame(
  row_id = 1:12,
  customer_id = rep(c("C01", "C02"), 6),
  city = rep(c("London", "Paris"), 6)
)

plan <- preview_dataframe(orders, key_columns = "row_id")
plan$tables
plan$cell_reduction_percent
# Preview creates no database or files and has no reconstruction verification.

result <- convert_dataframe(
  orders, out = "results/r-orders", key_columns = "row_id"
)
print(result)
summary(result)$reconstruction_exact
summary(result)$table_rows
read_table(result)  # complete joining dataset view
query(result, "SELECT * FROM dataset WHERE customer_id = ?", list("C01"))

plot(result)                    # logical cell counts
plot(result, type = "timings")  # processing stage durations
browseURL(result$report_path)   # local HTML report

reopened <- load_result("results/r-orders")
read_table(reopened, "dim_customer_id")
```

For a CSV, use `preview_csv()` and `convert_csv()`:

```r
# From the repository root, using the supplied synthetic sample:
plan <- preview_csv("data/retail_complex.csv",
                    key_columns = c("order_id", "line_number"))
result <- convert_csv("data/retail_complex.csv", out = "results/r-retail",
                      key_columns = c("order_id", "line_number"))
summary(result)$selected_key
plot(result, type = "bytes")  # actual CSV and database sizes; excludes exports
```

Use a **new output directory** for each conversion. Existing paths, including
empty directories, are refused. A failed write, verification or report generation
cleans up its staging directory instead of publishing incomplete output.
Run `?preview_dataframe`, `?read_table` and `?summary.autoschema_result` for the
installed API reference, or see `inst/examples/walkthrough.R` for a complete script.

## Outputs

Every conversion creates:

| File | Contents |
| --- | --- |
| `dataset.sqlite` | Dimension tables, records, primary/foreign keys and dataset view |
| `dataset.sql` | Complete schema, data inserts and reconstruction view |
| `schema.sql` | Table and view definitions |
| `schema.json` | Profiles, dependencies, keys, search budgets, statistics and timings |
| `report.html` | Offline processing stages, schema cards, statistics and charts |
| `records.csv`, `dim_*.csv` | Physical table contents |

The HTML report makes no network requests. Queries open a fresh read-only SQLite
connection and return ordinary R data frames. `load_result()` validates structure,
not original-source row equality. It can also open Python-generated SQLite results
with report format 1; Python can reopen R-generated SQLite results using its own
`load_result()`. The serialized result format is shared, not the in-memory object.

## How inference works

1. Validate headers and normalize values, keeping text formatting when numeric
   conversion would lose it. CSV parsing uses [readr](https://readr.tidyverse.org/reference/read_delim)
   with character columns, no automatic missing-value strings and no name repair.
2. Profile cardinality, blanks, duplicate rows and numeric ranges.
3. Discover exact single or composite functional dependencies. Blank determinants
   and constant/unique determinants are excluded.
4. Greedily move attributes to dimensions when this saves cells. Protect join keys
   and explicit domain keys in the records table.
5. Write the schema through [DBI and RSQLite](https://rsqlite.r-dbi.org/reference/SQLite.html).
   Compare the joined dataset to the normalized input as exact typed row multisets,
   preserving duplicate multiplicities, then check foreign keys.
6. Export artifacts and publish the complete result directory.

Search defaults match Python: determinant/key widths 2 (maximum 3), 30 candidate
columns, and 2,000 checks per search. Identifier-like column names receive priority.
Preview and conversion share inference code. A preview is descriptive; changes to
the returned list do not configure a conversion.

## Limits and R-specific behavior

The full input and verification data must fit in memory. Relationships observed
in one file may not hold for future data; the planner is a heuristic rather than
an optimal 3NF/BCNF normalization algorithm. Noisy relationships are not inferred.
Cell reduction measures repeated values, not byte compression. A database can be
larger than its CSV.

- Missing R values become empty strings. CSV text `NA` stays text. Duplicate rows
  are retained; row order, original CSV bytes and arbitrary R classes are not.
- CSV values convert to integer/double only when their text round-trips through
  R's character representation. Integer text outside R's 32-bit integer range
  remains text. Leading zeros, fixed decimals and signed-zero text are retained
  when necessary. Finite native R numeric columns without missing values retain
  their precision in SQLite and SQL exports.
- R and Python may infer different SQL types because their numeric formatting and
  integer ranges differ. Equivalent data and long/colliding identifiers can also
  produce different valid table names. Identical schemas across runtimes are not
  a general guarantee.
- List, matrix and complex columns, NUL bytes, empty datasets, malformed CSV
  records and case-colliding/empty headers are rejected.
- Delimiters are one byte and exclude newline and double quote; UTF-8 is the
  default input encoding and UTF-8 BOMs are accepted.
- Errors derive from `autoschema_error`, with `autoschema_configuration_error`,
  `autoschema_invalid_data`, `autoschema_output_error`,
  `autoschema_reconstruction_error` and `autoschema_invalid_result` subclasses.

## Develop and check

```sh
Rscript -e 'install.packages(c("roxygen2", "testthat", "withr"))'
Rscript -e 'roxygen2::roxygenise("r/autoschemaR")'
R CMD build r/autoschemaR
R CMD check --no-manual autoschemaR_0.1.0.9000.tar.gz
```

A separate GitHub Actions workflow checks the R package on Linux, Windows and
macOS. Python package checks remain separate. No CRAN submission is configured.

Licensed under MIT; see `LICENSE` and the repository's full license text.
