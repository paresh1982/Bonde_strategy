"""Alpaca adapter for Live Market Data."""

from .config import AlpacaConfig
from .errors import AlpacaConnectionError, AlpacaDataError, AlpacaAuthError
from .normalizer import normalize_alpaca_bar, normalize_alpaca_quote
from .connection import AlpacaConnectionManager
from .adapter import AlpacaMarketDataAdapter

__all__ = [
    "AlpacaConfig",
    "AlpacaMarketDataAdapter",
    "AlpacaConnectionManager",
    "normalize_alpaca_bar",
    "normalize_alpaca_quote",
    "AlpacaConnectionError",
    "AlpacaDataError",
    "AlpacaAuthError",
]
