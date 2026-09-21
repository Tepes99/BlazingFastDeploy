class ShipError(Exception):
    """A user-facing error with no traceback required."""


class ValidationError(ShipError):
    """Configuration or manifest validation failed."""


class CommandError(ShipError):
    """A local or remote process failed."""

    def __init__(self, message: str, *, output: str = "") -> None:
        super().__init__(message)
        self.output = output
