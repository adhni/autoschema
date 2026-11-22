"""Infer SQL tables from CSVs or pandas DataFrames, with an auditable report."""

from ._version import __version__
from .core import convert_csv, convert_dataframe, preview_csv, preview_dataframe
from .exceptions import (
    AutoSchemaError,
    ConfigurationError,
    InvalidDataError,
    InvalidResultError,
    MissingDependencyError,
    OutputExistsError,
    ReconstructionError,
)
from .result import ConversionResult, load_result

__all__ = [
    "AutoSchemaError",
    "ConfigurationError",
    "ConversionResult",
    "InvalidDataError",
    "InvalidResultError",
    "MissingDependencyError",
    "OutputExistsError",
    "ReconstructionError",
    "__version__",
    "convert_csv",
    "convert_dataframe",
    "load_result",
    "preview_csv",
    "preview_dataframe",
]
