"""Stable exceptions for callers that need to handle conversion failures."""


class AutoSchemaError(Exception):
    """Base class for AutoSchema configuration, data and artifact errors."""


class ConfigurationError(AutoSchemaError, ValueError):
    """A conversion option is invalid or unsupported."""


class InvalidDataError(AutoSchemaError, ValueError):
    """Input data or an explicit key cannot be converted safely."""


class OutputExistsError(AutoSchemaError, FileExistsError):
    """The destination already contains files and will not be overwritten."""


class ReconstructionError(AutoSchemaError, RuntimeError):
    """The database did not reconstruct the normalized input exactly."""


class MissingDependencyError(AutoSchemaError, ImportError):
    """An optional database engine is not installed."""


class InvalidResultError(AutoSchemaError, ValueError):
    """A saved result is incomplete, corrupt or uses an unsupported report format."""
