from fastapi import APIRouter, Depends, Query

from alpha_os.adapters.calendar.coinmarketcal_adapter import CoinMarketCalAdapter
from alpha_os.adapters.calendar.snapshot_adapter import SnapshotGovernanceAdapter
from alpha_os.adapters.onchain.blockchain_info_adapter import BlockchainInfoAdapter
from alpha_os.analysis.crypto_calendar import next_btc_halving_estimate
from alpha_os.api.deps import (
    get_blockchain_info_adapter,
    get_coinmarketcal_adapter,
    get_snapshot_governance_adapter,
)
from alpha_os.core.models import CoinCalendarSnapshot, GovernanceSnapshot, HalvingEstimate

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/halving-countdown", response_model=HalvingEstimate | None)
def get_halving_countdown(adapter: BlockchainInfoAdapter = Depends(get_blockchain_info_adapter)):
    """Determinístico (cada 210,000 bloques), no depende de fuente externa."""
    height = adapter.get_current_block_height()
    if height is None:
        return None
    return next_btc_halving_estimate(height)


@router.get("/governance", response_model=GovernanceSnapshot)
def get_governance(
    space: str = Query(..., description="Espacio DAO en Snapshot, ej. 'stakedao.eth', 'ens.eth' — tú decides cuál"),
    adapter: SnapshotGovernanceAdapter = Depends(get_snapshot_governance_adapter),
):
    """Gratis, sin key (Snapshot.org GraphQL público)."""
    return adapter.get_proposals(space)


@router.get("/events", response_model=CoinCalendarSnapshot)
def get_coin_events(
    coin_slug: str = Query(
        ..., description="slug del proyecto en CoinMarketCal, ej. 'bitcoin', 'ethereum' — no el ticker (colisionan)"
    ),
    adapter: CoinMarketCalAdapter = Depends(get_coinmarketcal_adapter),
):
    """Requiere COINMARKETCAL_API_KEY en .env (registro gratis en
    coinmarketcal.com/developer). Sin key, devuelve vacío en vez de fallar."""
    return adapter.get_coin_events(coin_slug)
