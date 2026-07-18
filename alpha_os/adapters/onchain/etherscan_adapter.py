from datetime import datetime, timedelta, timezone

import requests

from alpha_os.adapters.onchain._wallet_flow_common import build_wallet_flow_snapshot, empty_snapshot
from alpha_os.config import settings
from alpha_os.core.models import WalletFlowSnapshot, WalletTransaction

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
ETH_MAINNET_CHAIN_ID = 1

PAGE_SIZE = 100
MAX_PAGES = 2  # tope de páginas consultadas — wallets muy activas no se leen por completo


class EtherscanAdapter:
    """Etherscan API V2, gratis, requiere API key (cuenta gratuita en
    etherscan.io/register). Sin key configurada se comporta como el resto:
    devuelve un snapshot vacío en vez de fallar. Solo cubre transferencias
    nativas de ETH (endpoint `txlist`) — transferencias de tokens ERC-20
    requieren el endpoint `tokentx` por separado, fuera de este alcance
    básico. Nunca asume la identidad de una dirección — quien llama declara
    su propio label/source/confidence."""

    def get_wallet_flow(
        self,
        address: str,
        label: str,
        label_source: str,
        label_confidence: float,
        lookback_days: int = 30,
    ) -> WalletFlowSnapshot:
        if not settings.etherscan_api_key:
            return empty_snapshot(address, "ethereum", label, label_source, label_confidence, lookback_days)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback_days)

        transactions: list[WalletTransaction] = []
        try:
            for page in range(1, MAX_PAGES + 1):
                response = requests.get(
                    ETHERSCAN_V2_URL,
                    params={
                        "chainid": ETH_MAINNET_CHAIN_ID,
                        "module": "account",
                        "action": "txlist",
                        "address": address,
                        "startblock": 0,
                        "endblock": 99999999,
                        "page": page,
                        "offset": PAGE_SIZE,
                        "sort": "desc",
                        "apikey": settings.etherscan_api_key,
                    },
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("message") == "No transactions found":
                    break
                if data.get("status") != "1":
                    return empty_snapshot(address, "ethereum", label, label_source, label_confidence, lookback_days)

                txs = data.get("result", [])
                if not txs:
                    break
                stop = False
                for tx in txs:
                    tx_time = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
                    if tx_time < cutoff:
                        stop = True
                        continue
                    value_eth = int(tx["value"]) / 1e18
                    if value_eth == 0:
                        continue  # interacción de contrato sin transferencia nativa de ETH
                    transactions.append(
                        WalletTransaction(
                            tx_hash=tx["hash"],
                            timestamp=tx_time,
                            amount=value_eth,
                            direction="in" if tx["to"].lower() == address.lower() else "out",
                        )
                    )
                if stop or len(txs) < PAGE_SIZE:
                    break
        except (requests.RequestException, KeyError, ValueError):
            return empty_snapshot(address, "ethereum", label, label_source, label_confidence, lookback_days)

        return build_wallet_flow_snapshot(
            address, "ethereum", label, label_source, label_confidence, lookback_days, transactions, now, "ETH"
        )
