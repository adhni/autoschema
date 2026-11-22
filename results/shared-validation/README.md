# Validation run results

`summary.md` and `summary.json` record the executed shared Python/R contracts.
The local `python/` and `r/` folders contain complete per-case database, SQL, CSV
and HTML artifacts; they are generated and excluded from Git. Run the command in
[the validation guide](../../docs/validation.md) to create a fresh result folder.
The shared GitHub Actions workflow uploads all per-case artifacts for inspection.

Inputs and derived outputs involving public data retain the licenses and
attribution documented in [the fixture credits](../../r/autoschemaR/inst/validation/README.md).
The remaining fixtures are synthetic. Timings are single observations and do not
establish large-dataset limits.
