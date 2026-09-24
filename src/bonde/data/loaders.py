"""
Data Loaders for Stage 0 Engine
Loads chronological Bar objects from pandas DataFrames or CSV files.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Union
import pandas as pd
import zoneinfo

from .models import Bar, NY_TZ


def load_bars_from_dataframe(df: pd.DataFrame, symbol: str) -> List[Bar]:
    """
    Converts a pandas DataFrame into a strictly sorted List[Bar].
    Expected columns: timestamp (or index), open, high, low, close, volume.
    """
    bars = []
    df_copy = df.copy()

    if "timestamp" not in df_copy.columns and isinstance(df_copy.index, pd.DatetimeIndex):
        df_copy["timestamp"] = df_copy.index

    # Sort strictly chronologically
    df_copy = df_copy.sort_values("timestamp")

    for _, row in df_copy.iterrows():
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=NY_TZ)
        else:
            ts = ts.astimezone(NY_TZ)

        bar = Bar(
            timestamp=ts,
            symbol=row.get("symbol", symbol),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        bars.append(bar)

    return bars


def load_bars_from_csv(filepath: Union[str, Path], symbol: str) -> List[Bar]:
    """Loads CSV and converts to List[Bar]."""
    df = pd.read_csv(filepath)
    return load_bars_from_dataframe(df, symbol)
