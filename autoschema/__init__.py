"""Infer SQL tables from CSVs or pandas DataFrames, with an auditable report."""

from .core import ConversionResult, convert_csv, convert_dataframe

__all__ = ["ConversionResult", "convert_csv", "convert_dataframe"]
__version__ = "0.2.0"
