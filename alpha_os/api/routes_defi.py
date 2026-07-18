from fastapi import APIRouter, Depends, Query

from alpha_os.adapters.onchain.defillama_adapter import DeFiLlamaAdapter
from alpha_os.api.deps import get_defillama_adapter
from alpha_os.core.models import DexVolumeSnapshot, FeesRevenueSnapshot, ProtocolTVLSnapshot

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
