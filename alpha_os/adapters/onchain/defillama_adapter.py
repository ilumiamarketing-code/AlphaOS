import requests

from alpha_os.core.models import (
    DeFiTVLSnapshot,
    DexVolumeSnapshot,
    FeesRevenueSnapshot,
    ProtocolTVLSnapshot,
)

HISTORICAL_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
PROTOCOL_URL = "https://api.llama.fi/protocol/{protocol_slug}"
DEX_OVERVIEW_URL = "https://api.llama.fi/overview/dexs/{chain}"
FEES_OVERVIEW_URL = "https://api.llama.fi/overview/fees/{chain}"


class DeFiLlamaAdapter:
    """DeFiLlama, gratis y sin API key."""

    def get_chain_tvl(self, chain: str) -> DeFiTVLSnapshot:
        try:
            response = requests.get(HISTORICAL_TVL_URL.format(chain=chain), timeout=15)
            response.raise_for_status()
            points = response.json()
        except (requests.RequestException, ValueError):
            return DeFiTVLSnapshot(chain=chain)

        if not points:
            return DeFiTVLSnapshot(chain=chain)

        latest_tvl = points[-1]["tvl"]
        change_7d = None
        if len(points) > 7:
            week_ago_tvl = points[-8]["tvl"]
            if week_ago_tvl:
                change_7d = (latest_tvl - week_ago_tvl) / week_ago_tvl

        return DeFiTVLSnapshot(chain=chain, tvl_usd=latest_tvl, tvl_change_7d_pct=change_7d)

    def get_protocol_tvl(self, protocol_slug: str) -> ProtocolTVLSnapshot:
        try:
            response = requests.get(PROTOCOL_URL.format(protocol_slug=protocol_slug), timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return ProtocolTVLSnapshot(protocol_slug=protocol_slug)

        tvl_points = data.get("tvl") or []
        latest_tvl = tvl_points[-1]["totalLiquidityUSD"] if tvl_points else None

        return ProtocolTVLSnapshot(
            protocol_slug=protocol_slug,
            name=data.get("name"),
            category=data.get("category"),
            tvl_usd=latest_tvl,
        )

    def get_dex_volume(self, chain: str) -> DexVolumeSnapshot:
        try:
            response = requests.get(DEX_OVERVIEW_URL.format(chain=chain), timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return DexVolumeSnapshot(chain=chain)

        return DexVolumeSnapshot(
            chain=chain,
            volume_24h_usd=data.get("total24h"),
            volume_7d_usd=data.get("total7d"),
            change_24h_pct=data.get("change_1d"),
        )

    def get_fees_revenue(self, chain: str) -> FeesRevenueSnapshot:
        try:
            response = requests.get(FEES_OVERVIEW_URL.format(chain=chain), timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return FeesRevenueSnapshot(chain=chain)

        return FeesRevenueSnapshot(
            chain=chain,
            fees_24h_usd=data.get("total24h"),
            fees_7d_usd=data.get("total7d"),
            change_24h_pct=data.get("change_1d"),
        )
