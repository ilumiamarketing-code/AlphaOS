from pydantic import BaseModel

from alpha_os.core.models import Evidence


class OnChainSnapshot(BaseModel):
    ticker: str
    whale_flows: list[Evidence] = []
    exchange_net_flow: list[Evidence] = []
    funding_rate: float | None = None
    open_interest_change_pct: float | None = None
    stablecoin_supply_change: Evidence | None = None


def get_onchain_snapshot(ticker: str) -> OnChainSnapshot:
    """Pendiente de adapter on-chain real (Glassnode/Nansen/CryptoQuant).
    Solo aplica a activos cripto."""
    return OnChainSnapshot(ticker=ticker)
