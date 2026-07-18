from unittest.mock import patch

import requests

from alpha_os.adapters.onchain.defillama_adapter import DeFiLlamaAdapter


class _FakeResponse:
    def __init__(self, json_data, status_ok=True):
        self._json_data = json_data
        self.status_ok = status_ok

    def raise_for_status(self):
        if not self.status_ok:
            raise requests.HTTPError("boom")

    def json(self):
        return self._json_data


def test_protocol_tvl_parses_latest_point():
    payload = {
        "name": "Aave V3",
        "category": "Lending",
        "tvl": [
            {"date": 1, "totalLiquidityUSD": 100},
            {"date": 2, "totalLiquidityUSD": 200},
        ],
    }
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(payload)
        snapshot = adapter.get_protocol_tvl("aave-v3")

    assert snapshot.name == "Aave V3"
    assert snapshot.category == "Lending"
    assert snapshot.tvl_usd == 200


def test_protocol_tvl_unknown_slug_returns_empty():
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse({}, status_ok=False)
        snapshot = adapter.get_protocol_tvl("does-not-exist")
    assert snapshot.has_data() is False


def test_dex_volume_parses_totals():
    payload = {"total24h": 1000.0, "total7d": 7000.0, "change_1d": -5.5}
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(payload)
        snapshot = adapter.get_dex_volume("ethereum")

    assert snapshot.volume_24h_usd == 1000.0
    assert snapshot.volume_7d_usd == 7000.0
    assert snapshot.change_24h_pct == -5.5


def test_fees_revenue_network_failure_returns_empty():
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.side_effect = requests.ConnectionError("boom")
        snapshot = adapter.get_fees_revenue("ethereum")
    assert snapshot.has_data() is False


def _yield_pool(
    pool_id, project, chain, symbol, apy, tvl_usd, stablecoin=False, outlier=False
):
    return {
        "pool": pool_id,
        "project": project,
        "chain": chain,
        "symbol": symbol,
        "apy": apy,
        "apyBase": apy,
        "apyReward": None,
        "tvlUsd": tvl_usd,
        "stablecoin": stablecoin,
        "outlier": outlier,
        "predictions": {"predictedClass": "Stable/Up"},
    }


def test_yield_opportunities_filters_by_min_tvl_and_sorts_by_apy():
    payload = {
        "data": [
            _yield_pool("p1", "lido", "Ethereum", "STETH", apy=3.0, tvl_usd=5_000_000),
            _yield_pool("p2", "aave-v3", "Ethereum", "USDC", apy=8.0, tvl_usd=2_000_000, stablecoin=True),
            _yield_pool("p3", "sketchy-farm", "Ethereum", "SCAM", apy=9000.0, tvl_usd=500),
        ]
    }
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(payload)
        snapshot = adapter.get_yield_opportunities(min_tvl_usd=1_000_000.0)

    pool_ids = [p.pool_id for p in snapshot.pools]
    assert "p3" not in pool_ids  # TVL bajo, filtrado
    assert pool_ids == ["p2", "p1"]  # ordenado por APY descendente


def test_yield_opportunities_excludes_outliers_and_filters_stablecoin_only():
    payload = {
        "data": [
            _yield_pool("p1", "lido", "Ethereum", "STETH", apy=3.0, tvl_usd=5_000_000, stablecoin=False),
            _yield_pool("p2", "aave-v3", "Ethereum", "USDC", apy=200.0, tvl_usd=5_000_000, stablecoin=True, outlier=True),
            _yield_pool("p3", "curve", "Ethereum", "DAI", apy=5.0, tvl_usd=5_000_000, stablecoin=True),
        ]
    }
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(payload)
        snapshot = adapter.get_yield_opportunities(stablecoin_only=True, min_tvl_usd=1_000_000.0)

    pool_ids = [p.pool_id for p in snapshot.pools]
    assert pool_ids == ["p3"]  # p1 no es stablecoin, p2 es outlier


def test_yield_opportunities_filters_by_chain():
    payload = {
        "data": [
            _yield_pool("p1", "lido", "Ethereum", "STETH", apy=3.0, tvl_usd=5_000_000),
            _yield_pool("p2", "marinade", "Solana", "MSOL", apy=6.0, tvl_usd=5_000_000),
        ]
    }
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(payload)
        snapshot = adapter.get_yield_opportunities(chain="Solana", min_tvl_usd=1_000_000.0)

    assert [p.pool_id for p in snapshot.pools] == ["p2"]


def test_yield_opportunities_network_failure_returns_empty():
    adapter = DeFiLlamaAdapter()
    with patch("alpha_os.adapters.onchain.defillama_adapter.requests.get") as mocked_get:
        mocked_get.side_effect = requests.ConnectionError("boom")
        snapshot = adapter.get_yield_opportunities()
    assert snapshot.has_data() is False
