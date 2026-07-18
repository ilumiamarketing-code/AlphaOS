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
