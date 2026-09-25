"""Alpaca configuration model."""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from .errors import AlpacaAuthError


@dataclass(frozen=True)
class AlpacaConfig:
    """Configuration for Alpaca adapter."""

    api_key: str = ""
    secret_key: str = ""
    symbols: Optional[List[str]] = None
    feed: str = "iex"
    base_url: str = "https://paper-api.alpaca.markets"
    data_feed_url: str = "wss://stream.data.alpaca.markets"
    max_reconnect_attempts: int = 3
    reconnect_base_delay_seconds: float = 1.0
    reconnect_max_delay_seconds: float = 30.0
    staleness_warning_seconds: float = 60.0
    staleness_halt_seconds: float = 90.0
    max_symbols: int = 30
    checkpoint_interval_seconds: float = 300.0
    data_source_label: str = "IEX"
    max_buffer_size: int = 10000

    def __post_init__(self):
        if self.symbols is not None and len(self.symbols) > self.max_symbols:
            raise ValueError(
                f"Symbols count ({len(self.symbols)}) exceeds maximum limit of {self.max_symbols}"
            )

    @classmethod
    def from_env(cls, symbols: Optional[List[str]] = None) -> "AlpacaConfig":
        """Read configuration from environment variables."""
        api_key = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")

        if not api_key or not secret_key:
            raise AlpacaAuthError(
                "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in environment variables."
            )

        return cls(api_key=api_key, secret_key=secret_key, symbols=symbols)
