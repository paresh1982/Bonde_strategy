from datetime import datetime, timezone
from typing import Dict, Optional

from bonde.data.models import NY_TZ
from bonde.live.models import LiveBar, Quote, DataQualityStatus
from .errors import AlpacaDataError

def normalize_alpaca_bar(raw_bar, security_id_map: Optional[Dict[str, str]] = None) -> LiveBar:
    """Convert an Alpaca Bar object (or dict) to normalized LiveBar."""
    try:
        is_dict = isinstance(raw_bar, dict)
        
        symbol = raw_bar.get('symbol') if is_dict else getattr(raw_bar, 'symbol', None)
        timestamp = raw_bar.get('timestamp') if is_dict else getattr(raw_bar, 'timestamp', None)
        open_price = float(raw_bar.get('open') if is_dict else getattr(raw_bar, 'open', 0))
        high_price = float(raw_bar.get('high') if is_dict else getattr(raw_bar, 'high', 0))
        low_price = float(raw_bar.get('low') if is_dict else getattr(raw_bar, 'low', 0))
        close_price = float(raw_bar.get('close') if is_dict else getattr(raw_bar, 'close', 0))
        volume = int(raw_bar.get('volume') if is_dict else getattr(raw_bar, 'volume', 0))
        
        if not symbol:
            raise ValueError("Symbol is required")
        if timestamp is None:
            raise ValueError("Timestamp is required")
        if open_price <= 0 or high_price <= 0 or low_price <= 0 or close_price <= 0:
            raise ValueError("Prices must be > 0")
        if volume < 0:
            raise ValueError("Volume must be >= 0")
            
        # Convert timestamp to NY_TZ
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            
        ny_timestamp = timestamp.astimezone(NY_TZ)
        
        security_id = (security_id_map or {}).get(symbol, f"SEC_{symbol}")
        
        return LiveBar(
            timestamp=ny_timestamp,
            symbol=symbol,
            security_id=security_id,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            quality_status=DataQualityStatus.VALID
        )
    except Exception as e:
        raise AlpacaDataError(f"Failed to normalize bar: {e}") from e

def normalize_alpaca_quote(raw_quote, security_id_map: Optional[Dict[str, str]] = None) -> Quote:
    """Convert an Alpaca Quote object (or dict) to normalized Quote."""
    try:
        is_dict = isinstance(raw_quote, dict)
        
        symbol = raw_quote.get('symbol') if is_dict else getattr(raw_quote, 'symbol', None)
        timestamp = raw_quote.get('timestamp') if is_dict else getattr(raw_quote, 'timestamp', None)
        bid_price = float(raw_quote.get('bid_price') if is_dict else getattr(raw_quote, 'bid_price', 0))
        ask_price = float(raw_quote.get('ask_price') if is_dict else getattr(raw_quote, 'ask_price', 0))
        bid_size = int(raw_quote.get('bid_size') if is_dict else getattr(raw_quote, 'bid_size', 0))
        ask_size = int(raw_quote.get('ask_size') if is_dict else getattr(raw_quote, 'ask_size', 0))
        
        if not symbol:
            raise ValueError("Symbol is required")
        if timestamp is None:
            raise ValueError("Timestamp is required")
        if bid_price <= 0 or ask_price <= 0:
            raise ValueError("Prices must be > 0")
        if bid_size < 0 or ask_size < 0:
            raise ValueError("Sizes must be >= 0")
            
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            
        ny_timestamp = timestamp.astimezone(NY_TZ)
        
        security_id = (security_id_map or {}).get(symbol, f"SEC_{symbol}")
        
        return Quote(
            timestamp=ny_timestamp,
            symbol=symbol,
            security_id=security_id,
            bid=bid_price,
            ask=ask_price,
            bid_size=bid_size,
            ask_size=ask_size
        )
    except Exception as e:
        raise AlpacaDataError(f"Failed to normalize quote: {e}") from e
