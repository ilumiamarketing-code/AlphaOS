from itertools import combinations

import pandas as pd

from alpha_os.adapters.base import MarketDataAdapter
from alpha_os.core.models import CrossAssetCorrelation


class CrossAssetCorrelationAdapter:
    """Reutiliza el mismo patrón que PortfolioManager._correlation_pairs,
    pero devuelve todos los pares calculados (no solo los de alta
    correlación) — el spec quiere detectar cuándo dos activos DEJAN de estar
    correlacionados, lo que requiere el valor real, no un filtro binario."""

    def __init__(self, market_data: MarketDataAdapter):
        self.market_data = market_data

    def get_correlations(
        self, tickers: list[str], lookback: str = "3mo"
    ) -> list[CrossAssetCorrelation]:
        closes: dict[str, pd.Series] = {}
        for ticker in tickers:
            try:
                series = self.market_data.get_ohlcv(ticker, interval="1d", lookback=lookback)["close"]
            except Exception:
                continue
            # Cripto viene en UTC, equities/índices en la tz de su bolsa
            # (ej. America/New_York) — misma fecha calendario, timestamps
            # distintos. Sin esto, dropna() no encuentra ninguna fila en
            # común entre cripto y activos tradicionales.
            closes[ticker] = series.tz_localize(None) if series.index.tz is not None else series

        results: list[CrossAssetCorrelation] = []
        for a, b in combinations(closes.keys(), 2):
            joined = pd.concat([closes[a], closes[b]], axis=1, keys=[a, b]).dropna()
            if len(joined) < 10:
                continue
            corr = joined[a].pct_change().corr(joined[b].pct_change())
            if corr is not None and not pd.isna(corr):
                results.append(
                    CrossAssetCorrelation(
                        asset_a=a, asset_b=b, correlation=round(float(corr), 3), window_days=len(joined)
                    )
                )
        return results
