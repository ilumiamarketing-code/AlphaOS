import requests

from alpha_os.core.models import (
    DeFiTVLSnapshot,
    DexVolumeSnapshot,
    FeesRevenueSnapshot,
    ProtocolTVLSnapshot,
    YieldOpportunitiesSnapshot,
    YieldPoolSnapshot,
)

HISTORICAL_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
PROTOCOL_URL = "https://api.llama.fi/protocol/{protocol_slug}"
DEX_OVERVIEW_URL = "https://api.llama.fi/overview/dexs/{chain}"
FEES_OVERVIEW_URL = "https://api.llama.fi/overview/fees/{chain}"
YIELDS_URL = "https://yields.llama.fi/pools"

DEFAULT_MIN_TVL_USD = 1_000_000.0  # pools con poco TVL son más fáciles de manipular (APY inflado artificialmente)
TOP_N_POOLS = 20


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

    def get_yield_opportunities(
        self,
        chain: str | None = None,
        stablecoin_only: bool = False,
        min_tvl_usd: float = DEFAULT_MIN_TVL_USD,
        limit: int = TOP_N_POOLS,
    ) -> YieldOpportunitiesSnapshot:
        """Cubre lending/staking/LP yield — pendiente hasta ahora porque
        DeFiLlama solo exponía esto por protocolo individual. `yields.llama.fi/pools`
        sí es agregado (>15,000 pools de todos los protocolos/chains en una
        sola consulta, gratis, sin key)."""
        try:
            response = requests.get(YIELDS_URL, timeout=20)
            response.raise_for_status()
            raw_pools = response.json().get("data", [])
        except (requests.RequestException, ValueError, KeyError):
            return YieldOpportunitiesSnapshot(chain=chain, stablecoin_only=stablecoin_only, min_tvl_usd=min_tvl_usd)

        filtered = []
        for p in raw_pools:
            if p.get("outlier"):
                continue  # DeFiLlama ya lo marca como estadísticamente atípico (probable error/manipulación)
            if (p.get("tvlUsd") or 0) < min_tvl_usd:
                continue
            if chain and (p.get("chain") or "").lower() != chain.lower():
                continue
            if stablecoin_only and not p.get("stablecoin"):
                continue
            filtered.append(p)

        filtered.sort(key=lambda p: p.get("apy") or 0, reverse=True)
        filtered = filtered[:limit]

        pools = [
            YieldPoolSnapshot(
                pool_id=p["pool"],
                project=p["project"],
                chain=p["chain"],
                symbol=p["symbol"],
                apy=p.get("apy"),
                apy_base=p.get("apyBase"),
                apy_reward=p.get("apyReward"),
                tvl_usd=p.get("tvlUsd"),
                is_stablecoin=bool(p.get("stablecoin")),
                prediction=(p.get("predictions") or {}).get("predictedClass"),
            )
            for p in filtered
        ]

        return YieldOpportunitiesSnapshot(
            chain=chain, stablecoin_only=stablecoin_only, min_tvl_usd=min_tvl_usd, pools=pools
        )
