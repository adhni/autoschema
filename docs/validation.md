# Shared Python and R validation

The suite contains **17 cases**: 10 valid conversions and 7 expected rejections.
It runs offline against checked-in public snapshots and deterministic synthetic
fixtures. It verifies logical data fidelity rather than identical schemas across
language runtimes.

## Coverage

| Inputs | What is checked |
| --- | --- |
| Palmer Penguins, original (344 rows) | Mixed measurements and literal `NA` strings |
| Penguins with `NA` replaced by blanks | Empty-field preservation and duplicate counts |
| UCI Bike Sharing, daily (731 rows) | Explicit date key and composite calendar dependency |
| Synthetic orders | Composite order/line key, customer relationships, quoted text and blanks |
| Conflicting customer mappings | An inconsistent customer-to-city relation is not accepted |
| 129-column synthetic input | Bounded candidate/check budgets and warnings |
| Long identifiers | Exportable names and complete original columns |
| Unusual text | BOM, semicolon delimiter, Unicode, quotes and LF/CRLF/CR preservation |
| Numeric text | Leading zeros, fixed decimals, oversized integers and signed zeros |
| Quoted empty single-column rows | Blank rows and duplicate multiplicities |
| Seven rejection cases | Duplicate/case-colliding headers, ragged records, unterminated quote, empty data, NUL bytes and invalid explicit key |

Attribution, licenses, exact transformations and hashes are recorded alongside the
[fixtures](../r/autoschemaR/inst/validation/README.md). Public files retain their
upstream licenses; synthetic fixtures and validation code use MIT.

## Run both implementations

Install the Python and native R packages first. From the repository root:

```sh
python -m pip install -e '.[dev]'
Rscript -e 'install.packages(c("DBI", "RSQLite", "jsonlite", "readr"), repos="https://cloud.r-project.org")'
R CMD INSTALL r/autoschemaR
python scripts/shared_validation.py --out results/shared-validation-new
```

Use a new destination each time. `--r-library /path/to/library` selects an R
library if the native package was installed outside the default library;
`--rscript /path/to/Rscript` selects an interpreter. `--python-only` skips R.
The run creates per-case SQLite/SQL/CSV/HTML artifacts plus `summary.json` and a
concise `summary.md`. Errors are recorded and result in a nonzero exit status.

Python checks each valid output through an independent standard-library CSV and
SQLite oracle, including R-generated databases. It compares exact logical CSV
values and duplicate multiplicities against the source, executes the complete SQL
export, verifies physical-table CSVs, checks foreign keys, reopens saved results, and verifies metadata and
specified relationships. SQL files are read with newline translation disabled so
embedded CRLF values are not changed by the validator itself. Text CSV fields
must match exactly; numeric CSV fields may use different spellings only if they
parse to the exact stored integer or double value, with no tolerance.

The R worker and native package tests independently compare returned values to
base R CSV parsing, or explicit expected records for the unusual/single-column
cases. Invalid inputs must fail preview and conversion without publishing output.
The R package has no Python test or runtime dependency.

## Regular test commands

```sh
python -m pytest
R CMD build r/autoschemaR
R CMD check --no-manual autoschemaR_0.1.0.9000.tar.gz
```

The canonical manifest and CSVs live in `r/autoschemaR/inst/validation` so built R
packages retain their standalone tests. Python source distributions include these
test inputs as well; the Python wheel does not include them.

The Python and R CI matrices run their respective manifest contracts. A separate
**Shared dataset validation** workflow runs both implementations together and
uploads the result artifacts, including the independent SQL checks.

## Interpreting results

SQL types, inferred keys without an explicit override, table ordering/names and
complete schemas may differ. Those differences are reported rather than treated
as data loss. Exact source-value preservation and the explicitly stated domain
contracts must hold in both implementations.

The initial suite found and fixed a Python CSV-export bug: with LF line endings,
minimal quoting left a bare carriage return unquoted, which split a logical
record when read back. Text fields are now explicitly quoted. The committed
results reflect the corrected exporter. It also found an R export bug: empty
single-column records became blank lines, so CSV readers could skip them. R now
quotes physical CSV exports to preserve those rows.

Conversion durations are single-run observations, exclude preview and oracle
checks, and exclude R startup. They are diagnostics, not performance guarantees.
These small fixtures do not establish memory limits or million-row throughput.
The next performance milestone is a separate, controlled 10k/100k/1m-row benchmark
with process memory measurement and explicit runtime budgets.
