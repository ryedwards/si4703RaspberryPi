"""Exceptions for the si4703 library."""


class Si4703Error(Exception):
    """Base exception for all Si4703 errors."""


class TuneTimeoutError(Si4703Error):
    """Raised when a tune or seek operation does not complete within the timeout."""


class SeekFailedError(Si4703Error):
    """Raised when a seek reaches the band limit without finding a valid station."""


class NotInitializedError(Si4703Error):
    """Raised when a method is called before :meth:`~si4703.Si4703Radio.power_on`."""
