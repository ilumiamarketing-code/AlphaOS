from datetime import datetime, timedelta, timezone

import requests

from alpha_os.adapters.onchain._wallet_flow_common import build_wallet_flow_snapshot, empty_snapshot
from alpha_os.core.models import NetworkHealthSnapshot, WalletFlowSnapshot, WalletTransaction

RAWADDR_URL = "https://blockchain.info/rawaddr/{address}"
CHARTS_URL = "https://api.blockchain.info/charts/{chart}"
BLOCK_COUNT_URL = "https://blockchain.info/q/getblockcount"

PAGE_SIZE = 50
MAX_PAGES = 4  # tope de páginas consultadas — wallets muy activas no se leen por completo


class BlockchainInfoAdapter:
    """blockchain.info, gratis y sin API key, para Bitcoin. Nunca asume la
    identidad de una dirección — quien llama a `get_wallet_flow` declara su
    propio label/source/confidence, que simplemente se adjuntan al
    resultado sin validarlos ni inventarlos."""

    def get_wallet_flow(
        self,
        address: str,
        label: str,
        label_source: str,
        label_confidence: float,
        lookback_days: int = 30,
    ) -> WalletFlowSnapshot:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback_days)

        transactions: list[WalletTransaction] = []
        try:
            for page in range(MAX_PAGES):
                response = requests.get(
                    RAWADDR_URL.format(address=address),
                    params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
                    timeout=15,
                )
                response.raise_for_status()
                txs = response.json().get("txs", [])
                if not txs:
                    break
                stop = False
                for tx in txs:
                    tx_time = datetime.fromtimestamp(tx["time"], tz=timezone.utc)
                    if tx_time < cutoff:
                        stop = True
                        continue
                    result = tx.get("result", 0)
                    if result == 0:
                        continue
                    transactions.append(
                        WalletTransaction(
                            tx_hash=tx["hash"],
                            timestamp=tx_time,
                            amount=abs(result) / 1e8,
                            direction="in" if result > 0 else "out",
                        )
                    )
                if stop or len(txs) < PAGE_SIZE:
                    break
        except (requests.RequestException, KeyError, ValueError):
            return empty_snapshot(address, "bitcoin", label, label_source, label_confidence, lookback_days)

        return build_wallet_flow_snapshot(
            address, "bitcoin", label, label_source, label_confidence, lookback_days, transactions, now, "BTC"
        )

    def get_current_block_height(self) -> int | None:
        try:
            response = requests.get(BLOCK_COUNT_URL, timeout=10)
            response.raise_for_status()
            return int(response.text)
        except (requests.RequestException, ValueError):
            return None

    def get_network_health(self) -> NetworkHealthSnapshot:
        hash_rate_series = self._get_chart("hash-rate")
        tx_count_series = self._get_chart("n-transactions")
        fees_usd_series = self._get_chart("transaction-fees-usd")

        hash_rate = hash_rate_series[-1] if hash_rate_series else None
        tx_count = tx_count_series[-1] if tx_count_series else None
        avg_fee_usd = None
        if fees_usd_series and tx_count_series and tx_count_series[-1]:
            avg_fee_usd = fees_usd_series[-1] / tx_count_series[-1]

        hash_rate_change = self._pct_change(hash_rate_series)
        tx_count_change = self._pct_change(tx_count_series)

        return NetworkHealthSnapshot(
            chain="bitcoin",
            hash_rate=hash_rate,
            tx_count_24h=tx_count,
            avg_fee_usd=avg_fee_usd,
            hash_rate_change_30d_pct=hash_rate_change,
            tx_count_change_30d_pct=tx_count_change,
        )

    def _get_chart(self, chart: str) -> list[float]:
        try:
            response = requests.get(
                CHARTS_URL.format(chart=chart), params={"timespan": "35days", "format": "json"}, timeout=15
            )
            response.raise_for_status()
            values = response.json().get("values", [])
            return [v["y"] for v in values]
        except (requests.RequestException, KeyError, ValueError):
            return []

    @staticmethod
    def _pct_change(series: list[float]) -> float | None:
        if len(series) < 2 or not series[0]:
            return None
        return (series[-1] - series[0]) / series[0]
