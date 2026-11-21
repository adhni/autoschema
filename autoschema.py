"""Compatibility runner; the public library lives in the autoschema package."""

from autoschema.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
