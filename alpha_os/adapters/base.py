from abc import ABC, abstractmethod

import pandas as pd

from alpha_os.core.models import Evidence, FundamentalSnapshot, MacroSnapshot


class MarketDataAdapter(ABC):
    """Fuente de precios/volumen. Cualquier proveedor (yfinance, Polygon,
    Bloomberg) implementa esta interfaz para que el resto del sistema sea
    agnóstico a dónde vienen los datos."""

    @abstractmethod
    def get_ohlcv(self, ticker: str, interval: str, lookback: str) -> pd.DataFrame:
        """interval: '1m'..'1mo'. lookback: string tipo '5d', '1y'.
        Devuelve columnas [open, high, low, close, volume] indexadas por fecha."""

    @abstractmethod
    def get_quote(self, ticker: str) -> float:
        """Último precio disponible."""


class FundamentalDataAdapter(ABC):
    @abstractmethod
    def get_snapshot(self, ticker: str) -> FundamentalSnapshot:
        """Métricas fundamentales más recientes disponibles. Campos sin dato
        deben quedar en None, nunca inventados."""


class MacroDataAdapter(ABC):
    @abstractmethod
    def get_snapshot(self) -> MacroSnapshot:
        """Estado macro agregado (no depende de un ticker). Campos sin dato
        deben quedar en None, nunca inventados."""


class NewsAdapter(ABC):
    @abstractmethod
    def get_recent_news(self, ticker: str, limit: int = 10) -> list[Evidence]:
        """Titulares recientes convertidos a Evidence con su source_tier."""


class OnChainAdapter(ABC):
    @abstractmethod
    def get_whale_flows(self, ticker: str) -> list[Evidence]:
        """Movimientos relevantes de grandes tenedores."""

    @abstractmethod
    def get_exchange_flows(self, ticker: str) -> list[Evidence]:
        """Entradas/salidas netas de exchanges."""

    @abstractmethod
    def get_funding_rate(self, ticker: str) -> float | None:
        """Funding rate de perpetuos, si aplica."""

    @abstractmethod
    def get_stablecoin_supply_change(self) -> Evidence | None:
        """Cambio reciente en el suministro agregado de stablecoins."""
