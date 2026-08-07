class ContextStatError(Exception):
    """Expected user-facing error."""


class BackendUnavailableError(ContextStatError):
    """Requested optional backend is not installed."""


class OnlineNotAllowedError(ContextStatError):
    """An online operation was requested without explicit permission."""


class ConfigurationError(ContextStatError):
    """Configuration is invalid."""
