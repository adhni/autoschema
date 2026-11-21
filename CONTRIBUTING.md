# Developing AutoSchema

Create a virtual environment and install the source package in editable mode:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,duckdb]'
```

On Windows, activate with `.venv\Scripts\activate`. Notebook dependencies are available with `python -m pip install -e '.[notebook]'`.

## Checks

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov --cov-report=term-missing
```

The standard-library test runner also works after installation: `python -m unittest discover -s tests -v`. Tests use temporary directories. Tests for DuckDB skip when the optional engine is absent. Existing sample results and personal notebook output directories should not be overwritten during development.

The `src/` layout requires an installation and prevents the working directory from accidentally substituting for the installed package. Import supported interfaces from `autoschema`, rather than private modules. Keep public parameters, exception behavior and report format compatibility documented in `docs/api.md` and `CHANGELOG.md`.

## Build and verify a distribution

```sh
python -m build
python -m twine check dist/*
python scripts/check_distribution.py dist/autoschema-0.3.0-py3-none-any.whl
```

`python -m build` produces a source archive and builds the wheel from that archive. The distribution check creates a fresh virtual environment, installs the wheel and its dependencies, then verifies imports, version metadata, type-marker inclusion, conversions, reopening saved results, SQL queries and the installed console command from outside the repository. It requires package-download access for dependencies.

The wheel contains only library code and metadata; notebooks, datasets and generated results stay in the checkout. The source archive additionally includes tests and the API documentation. CI configuration runs tests across the selected Python versions on Linux and Windows, includes a pandas minimum-version job, and retains built artifacts. Those remote jobs run only when this project is pushed to a repository with Actions enabled.

## Versioning

Update `src/autoschema/_version.py` and the changelog when preparing a release. Build and inspect a new distribution before sharing it. The package version, CLI version and conversion producer version all come from that file. `report_format_version` describes persisted metadata independently of package versions.

The build and verification commands do not publish or upload the library. There is no automatic package-upload workflow.
