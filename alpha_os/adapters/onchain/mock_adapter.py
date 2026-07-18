from alpha_os.adapters.base import OnChainAdapter
from alpha_os.core.models import Evidence


class MockOnChainAdapter(OnChainAdapter):
    """Placeholder hasta conectar Glassnode/Nansen/CryptoQuant. Sin datos
    reales todavía, así que no se inventan cifras on-chain."""

    def get_whale_flows(self, ticker: str) -> list[Evidence]:
        return []

    def get_exchange_flows(self, ticker: str) -> list[Evidence]:
        return []

    def get_funding_rate(self, ticker: str) -> float | None:
        return None

    def get_stablecoin_supply_change(self) -> Evidence | None:
        return None
