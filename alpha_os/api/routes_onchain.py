from typing import Literal

from fastapi import APIRouter, Depends, Query

from alpha_os.adapters.onchain.blockchain_info_adapter import BlockchainInfoAdapter
from alpha_os.adapters.onchain.defillama_adapter import DeFiLlamaAdapter
from alpha_os.adapters.onchain.etherscan_adapter import EtherscanAdapter
from alpha_os.api.deps import get_blockchain_info_adapter, get_defillama_adapter, get_etherscan_adapter
from alpha_os.core.models import DeFiTVLSnapshot, NetworkHealthSnapshot, WalletFlowSnapshot

router = APIRouter(prefix="/onchain", tags=["onchain"])


@router.get("/wallet-flow", response_model=WalletFlowSnapshot)
def get_wallet_flow(
    address: str,
    label: str = Query(..., description="Cómo llamas tú a esta wallet — nunca se infiere automáticamente"),
    label_source: str = Query(..., description="De dónde viene esa atribución (ej. 'proof of reserves 2026-01', 'declaración pública del exchange')"),
    label_confidence: float = Query(..., ge=0, le=1),
    chain: Literal["bitcoin", "ethereum"] = "bitcoin",
    lookback_days: int = Query(30, ge=1, le=90),
    bitcoin_adapter: BlockchainInfoAdapter = Depends(get_blockchain_info_adapter),
    ethereum_adapter: EtherscanAdapter = Depends(get_etherscan_adapter),
):
    """Bitcoin (blockchain.info, gratis) o Ethereum (Etherscan, requiere
    ETHERSCAN_API_KEY — sin key configurada se comporta igual que el resto
    de adapters: vacío, no falla). El label/source/confidence los declara
    quien llama — este sistema nunca asume la identidad de una dirección
    (spec: "nunca inventar wallets")."""
    adapter = bitcoin_adapter if chain == "bitcoin" else ethereum_adapter
    return adapter.get_wallet_flow(address, label, label_source, label_confidence, lookback_days)


@router.get("/network-health", response_model=NetworkHealthSnapshot)
def get_network_health(adapter: BlockchainInfoAdapter = Depends(get_blockchain_info_adapter)):
    return adapter.get_network_health()


@router.get("/defi-tvl", response_model=DeFiTVLSnapshot)
def get_defi_tvl(chain: str = "Ethereum", adapter: DeFiLlamaAdapter = Depends(get_defillama_adapter)):
    return adapter.get_chain_tvl(chain)


# El halving countdown vive en /calendar/halving-countdown (routes_calendar.py)
# — es un evento de calendario, no un dato on-chain de un ticker específico.
