# Changelog

## 0.3.0 — local development release

- Move the installable library into `src/autoschema` and separate inference, database storage, orchestration, and result handling.
- Keep the root-level `convert_csv`, `convert_dataframe`, and `ConversionResult` imports; add `load_result` for saved conversions.
- Add public type annotations, a packaged `py.typed` marker, defensive result metadata and documented exception classes.
- Stage all conversion artifacts before publishing them, with cleanup on failed database, export, or report generation.
- Add CLI `--version` and a single version source shared with package metadata.
- Add `dev`, `notebook`, and `duckdb` extras, an API reference, distribution checks and CI configuration.
- Expand regression tests for artifact reopening, invalid options, output protection, failure cleanup and installed CLI behavior.

### Migration from 0.2

Install the project before importing it: `python -m pip install -e .` for development, or `python -m pip install .` for a regular installation. Source directories are no longer implicitly importable from the repository root.

Use `autoschema ...` or `python -m autoschema ...` in place of the retired root `autoschema.py` script. Keeping that script at the root would shadow the installed package. Conversion function names and ordinary calls remain compatible. An explicit empty `key_columns=[]` is now rejected; use `None` for inference.

Both `result.report` and `result.summary()` now return independent copies. Treat the result's paths and metadata as immutable. Existing 0.2 `schema.json` reports can be reopened with `load_result`.

## 0.2.0

- Add importable CSV/DataFrame conversion, bounded composite dependency/key discovery, SQL/CSV exports and visual HTML reports.
- Include synthetic retail data, a runnable library example, reconstruction regression tests and an executed walkthrough notebook.
