"""Alpaca specific exceptions."""

class AlpacaConnectionError(Exception):
    """WebSocket connection failures."""
    pass

class AlpacaDataError(Exception):
    """Data normalization/validation failures."""
    pass

class AlpacaAuthError(Exception):
    """Authentication failures (invalid API key)."""
    pass
