from datetime import datetime, timedelta, timezone

import requests

from alpha_os.adapters.onchain._wallet_flow_common import build_wallet_flow_snapshot, empty_snapshot
from alpha_os.config import settings
from alpha_os.core.models import (
    NetworkHealthSnapshot,
    TokenFlowSnapshot,
    TokenTransferSummary,
    WalletFlowSnapshot,
    WalletTransaction,
)

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
ETH_MAINNET_CHAIN_ID = 1
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
STANDARD_TRANSFER_GAS = 21000  # ETH nativo; llamadas a contratos usan bastante más

PAGE_SIZE = 100
MAX_PAGES = 2  # tope de páginas consultadas — wallets muy activas no se leen por completo
TOP_N_TOKENS = 15  # wallets activas reciben spam/airdrops de docenas de contratos irrelevantes


def _empty_token_snapshot(
    address: str, label: str, label_source: str, label_confidence: float, lookback_days: int
) -> TokenFlowSnapshot:
    return TokenFlowSnapshot(
        address=address,
        label=label,
        label_source=label_source,
        label_confidence=label_confidence,
        lookback_days=lookback_days,
        effective_lookback_days=0,
    )


class EtherscanAdapter:
    """Etherscan API V2, gratis, requiere API key (cuenta gratuita en
    etherscan.io/register). Sin key configurada se comporta como el resto:
    devuelve un snapshot vacío en vez de fallar. Cubre transferencias
    nativas de ETH (endpoint `txlist`, vía get_wallet_flow) y transferencias
    de tokens ERC-20 (endpoint `tokentx`, vía get_token_transfers) por
    separado, ya que un token no comparte el mismo modelo que ETH nativo
    (decimales/símbolo propios por contrato). Nunca asume la identidad de
    una dirección — quien llama declara su propio label/source/confidence."""

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

    def get_token_transfers(
        self,
        address: str,
        label: str,
        label_source: str,
        label_confidence: float,
        lookback_days: int = 30,
    ) -> TokenFlowSnapshot:
        if not settings.etherscan_api_key:
            return _empty_token_snapshot(address, label, label_source, label_confidence, lookback_days)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback_days)

        raw_transfers: list[dict] = []
        try:
            for page in range(1, MAX_PAGES + 1):
                response = requests.get(
                    ETHERSCAN_V2_URL,
                    params={
                        "chainid": ETH_MAINNET_CHAIN_ID,
                        "module": "account",
                        "action": "tokentx",
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
                    return _empty_token_snapshot(address, label, label_source, label_confidence, lookback_days)

                txs = data.get("result", [])
                if not txs:
                    break
                stop = False
                for tx in txs:
                    tx_time = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
                    if tx_time < cutoff:
                        stop = True
                        continue
                    raw_transfers.append(tx)
                if stop or len(txs) < PAGE_SIZE:
                    break
        except (requests.RequestException, KeyError, ValueError):
            return _empty_token_snapshot(address, label, label_source, label_confidence, lookback_days)

        if not raw_transfers:
            return _empty_token_snapshot(address, label, label_source, label_confidence, lookback_days)

        oldest_ts = min(int(tx["timeStamp"]) for tx in raw_transfers)
        oldest_date = datetime.fromtimestamp(oldest_ts, tz=timezone.utc).date()
        effective_days = min((now.date() - oldest_date).days + 1, lookback_days)

        by_contract: dict[str, dict] = {}
        for tx in raw_transfers:
            contract = tx["contractAddress"].lower()
            decimals = int(tx.get("tokenDecimal") or 18)
            amount = int(tx["value"]) / (10**decimals)
            entry = by_contract.setdefault(
                contract,
                {"symbol": tx.get("tokenSymbol") or "?", "decimals": decimals, "inflow": 0.0, "outflow": 0.0, "tx_count": 0},
            )
            if tx["to"].lower() == address.lower():
                entry["inflow"] += amount
            else:
                entry["outflow"] += amount
            entry["tx_count"] += 1

        tokens = [
            TokenTransferSummary(
                token_symbol=v["symbol"],
                token_contract=contract,
                token_decimals=v["decimals"],
                inflow=v["inflow"],
                outflow=v["outflow"],
                net_flow=v["inflow"] - v["outflow"],
                tx_count=v["tx_count"],
            )
            for contract, v in by_contract.items()
        ]
        # Ordenado por volumen total — wallets activas reciben decenas de
        # tokens irrelevantes (airdrops/spam); nos quedamos con lo relevante.
        tokens.sort(key=lambda t: t.inflow + t.outflow, reverse=True)
        tokens = tokens[:TOP_N_TOKENS]

        return TokenFlowSnapshot(
            address=address,
            label=label,
            label_source=label_source,
            label_confidence=label_confidence,
            lookback_days=lookback_days,
            effective_lookback_days=effective_days,
            tokens=tokens,
        )

    def get_network_health(self) -> NetworkHealthSnapshot:
        """A diferencia de Bitcoin, Ethereum es Proof-of-Stake desde The
        Merge (2022) — no existe hash rate que reportar, así que ese campo
        queda `None` para esta chain (nunca se inventa un valor placeholder).
        Tampoco hay conteo de tx/24h ni histórico de gas gratis: el endpoint
        `stats&action=dailyavggasprice` de Etherscan es exclusivo del plan
        Pro (verificado en vivo: responde "Sorry, it looks like you are
        trying to access an API Pro endpoint"), así que los campos de
        cambio 30d también quedan `None` en vez de estimarse. Lo único que
        sí es real y gratis: gas price actual (`gastracker&action=gasoracle`)
        convertido a USD con el precio ETH/USD de CoinGecko, para una
        transferencia estándar de 21,000 gas — una llamada a contrato puede
        costar varias veces más, así que esto es un piso, no un promedio
        real de todas las transacciones."""
        if not settings.etherscan_api_key:
            return NetworkHealthSnapshot(chain="ethereum")

        try:
            response = requests.get(
                ETHERSCAN_V2_URL,
                params={
                    "chainid": ETH_MAINNET_CHAIN_ID,
                    "module": "gastracker",
                    "action": "gasoracle",
                    "apikey": settings.etherscan_api_key,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1":
                return NetworkHealthSnapshot(chain="ethereum")
            propose_gas_gwei = float(data["result"]["ProposeGasPrice"])
        except (requests.RequestException, KeyError, ValueError):
            return NetworkHealthSnapshot(chain="ethereum")

        avg_fee_usd = None
        try:
            price_response = requests.get(
                COINGECKO_PRICE_URL, params={"ids": "ethereum", "vs_currencies": "usd"}, timeout=15
            )
            price_response.raise_for_status()
            eth_usd_price = price_response.json()["ethereum"]["usd"]
            avg_fee_usd = propose_gas_gwei * STANDARD_TRANSFER_GAS * 1e-9 * eth_usd_price
        except (requests.RequestException, KeyError, ValueError):
            pass  # gas price sin conversión a USD sigue siendo parcialmente útil, no se descarta el resto

        return NetworkHealthSnapshot(chain="ethereum", avg_fee_usd=avg_fee_usd)
