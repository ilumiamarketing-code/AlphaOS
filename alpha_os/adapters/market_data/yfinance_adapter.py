import pandas as pd
import yfinance as yf

from alpha_os.adapters.base import MarketDataAdapter

_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}


class YFinanceAdapter(MarketDataAdapter):
    """Fuente gratuita sin API key. Suficiente para prototipar; yfinance
    aplica rate limits no documentados bajo uso intensivo."""

    def get_ohlcv(self, ticker: str, interval: str = "1d", lookback: str = "6mo") -> pd.DataFrame:
        yf_interval = _INTERVAL_MAP.get(interval, interval)
        df = yf.Ticker(ticker).history(period=lookback, interval=yf_interval)
        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        return df[["open", "high", "low", "close", "volume"]]

    def get_quote(self, ticker: str) -> float:
        fast_info = yf.Ticker(ticker).fast_info
        return float(fast_info["last_price"])
