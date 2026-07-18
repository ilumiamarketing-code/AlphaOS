import numpy as np
import pandas as pd

from alpha_os.adapters.base import MarketDataAdapter


class MockMarketDataAdapter(MarketDataAdapter):
    """Datos sintéticos deterministas para tests y desarrollo offline.
    Nunca debe usarse como base de una señal real."""

    def __init__(self, seed: int = 42):
        self._rng = np.random.default_rng(seed)

    def get_ohlcv(self, ticker: str, interval: str = "1d", lookback: str = "6mo") -> pd.DataFrame:
        periods = 180
        dates = pd.date_range(end=pd.Timestamp.utcnow(), periods=periods, freq="D")
        close = 100 + np.cumsum(self._rng.normal(0, 1, periods))
        high = close + self._rng.uniform(0, 1, periods)
        low = close - self._rng.uniform(0, 1, periods)
        open_ = close + self._rng.normal(0, 0.5, periods)
        volume = self._rng.integers(1_000_000, 5_000_000, periods)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=dates,
        )

    def get_quote(self, ticker: str) -> float:
        return float(self.get_ohlcv(ticker)["close"].iloc[-1])
