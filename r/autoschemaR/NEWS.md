# autoschemaR 0.1.0.9000

- Quote physical CSV exports so empty single-column records are retained when read back.
- Add 17 shared offline dataset contracts with attributed public snapshots and a combined Python/R validation runner.

- Validate unsupported encodings across readr versions and preserve exact newline bytes in SQL exports on Windows.
- Initial native R implementation with CSV/data-frame conversion and schema previews.
- Add bounded composite dependency/key discovery and greedy dimension planning.
- Write SQLite tables, SQL/CSV exports and portable JSON metadata, with exact
  reconstruction and foreign-key checks before output publication.
- Add read-only parameterized queries, result reopening, summary/print/plot methods,
  an offline HTML report, installed API documentation and behavioral tests.
- Support SQLite report interchange with the Python library; Python is not a runtime
  or test dependency of the R package.
