import pandas as pd

from alpha_os.adapters.base import MarketDataAdapter
from alpha_os.analysis import technical
from alpha_os.core.models import RelativeVolumeObservation


class RelativeVolumeAdapter:
    """Volumen vs. su propia media de 20 periodos. Un dato puro, sin
    dirección — el módulo institucional decide cómo (no) usarlo."""

    def __init__(self, market_data: MarketDataAdapter):
        self.market_data = market_data

    def get_observation(self, ticker: str) -> RelativeVolumeObservation | None:
        ohlcv = self.market_data.get_ohlcv(ticker)
        if len(ohlcv) < 21:
            return None
        z = technical.volume_zscore(ohlcv["volume"]).iloc[-1]
        if pd.isna(z):
            return None
        return RelativeVolumeObservation(ticker=ticker, volume_zscore=float(z))
