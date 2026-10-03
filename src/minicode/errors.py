"""Exceptions exposed by MiniCode."""


class MiniCodeError(Exception):
    """Base class for expected MiniCode failures."""


class ConfigurationError(MiniCodeError):
    """Raised when application configuration is invalid."""


class ProviderError(MiniCodeError):
    """Raised when a model provider fails."""


class ToolError(MiniCodeError):
    """Raised when a tool cannot complete."""


class PolicyDenied(ToolError):
    """Raised when policy prevents an operation."""


class RunAborted(MiniCodeError):
    """Raised when a run is cancelled or aborted."""
