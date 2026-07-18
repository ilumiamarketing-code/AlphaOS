from fastapi import APIRouter, Depends, Query

from alpha_os.adapters.onchain.defillama_adapter import DeFiLlamaAdapter
from alpha_os.api.deps import get_defillama_adapter
from alpha_os.core.models import (
    DexVolumeSnapshot,
    FeesRevenueSnapshot,
    ProtocolTVLSnapshot,
    YieldOpportunitiesSnapshot,
)

router = APIRouter(prefix="/defi", tags=["defi"])


@router.get("/protocol-tvl", response_model=ProtocolTVLSnapshot)
def get_protocol_tvl(
    protocol_slug: str = Query(..., description="slug de DeFiLlama, ej. 'aave-v3', 'uniswap-v3'"),
    adapter: DeFiLlamaAdapter = Depends(get_defillama_adapter),
):
    """TVL de un protocolo específico (no una chain completa). Gratis, sin key."""
    return adapter.get_protocol_tvl(protocol_slug)


@router.get("/dex-volume", response_model=DexVolumeSnapshot)
def get_dex_volume(
    chain: str = Query("ethereum", description="chain de DeFiLlama, ej. 'ethereum', 'solana'"),
    adapter: DeFiLlamaAdapter = Depends(get_defillama_adapter),
):
    """Volumen agregado de DEXs de una chain. Gratis, sin key."""
    return adapter.get_dex_volume(chain)


@router.get("/fees", response_model=FeesRevenueSnapshot)
def get_fees_revenue(
    chain: str = Query("ethereum", description="chain de DeFiLlama"),
    adapter: DeFiLlamaAdapter = Depends(get_defillama_adapter),
):
    """Fees/revenue agregados de protocolos de una chain. Gratis, sin key."""
    return adapter.get_fees_revenue(chain)


@router.get("/yields", response_model=YieldOpportunitiesSnapshot)
def get_yield_opportunities(
    chain: str | None = Query(None, description="ej. 'Ethereum', 'Solana' — vacío = todas las chains"),
    stablecoin_only: bool = Query(False, description="solo pools de stablecoins (sin exposición a precio del activo)"),
    min_tvl_usd: float = Query(1_000_000.0, ge=0, description="pools con TVL bajo son más fáciles de manipular (APY inflado)"),
    limit: int = Query(20, ge=1, le=100),
    adapter: DeFiLlamaAdapter = Depends(get_defillama_adapter),
):
    """Lending/staking/LP yield vía yields.llama.fi/pools — agregado real
    entre >15,000 pools de todos los protocolos/chains, gratis y sin key.
    Ordenado por APY descendente dentro de los filtros dados; pools
    marcados como `outlier` por DeFiLlama se excluyen siempre."""
    return adapter.get_yield_opportunities(chain, stablecoin_only, min_tvl_usd, limit)
