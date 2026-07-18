from unittest.mock import patch

import requests

from alpha_os.adapters.calendar.coinmarketcal_adapter import CoinMarketCalAdapter
from alpha_os.adapters.calendar.snapshot_adapter import SnapshotGovernanceAdapter
from alpha_os.analysis.crypto_calendar import next_btc_halving_estimate


class _FakeResponse:
    def __init__(self, json_data, status_ok=True):
        self._json_data = json_data
        self.status_ok = status_ok

    def raise_for_status(self):
        if not self.status_ok:
            raise requests.HTTPError("boom")

    def json(self):
        return self._json_data


def test_snapshot_adapter_parses_proposals():
    payload = {
        "data": {
            "proposals": [
                {
                    "id": "0xabc",
                    "title": "Test proposal",
                    "start": 1700000000,
                    "end": 1700100000,
                    "state": "active",
                    "link": "https://snapshot.box/x",
                }
            ]
        }
    }
    adapter = SnapshotGovernanceAdapter()
    with patch("alpha_os.adapters.calendar.snapshot_adapter.requests.post") as mocked_post:
        mocked_post.return_value = _FakeResponse(payload)
        snapshot = adapter.get_proposals("test.eth")

    assert snapshot.has_data() is True
    assert snapshot.proposals[0].title == "Test proposal"
    assert snapshot.proposals[0].state == "active"


def test_snapshot_adapter_empty_space_has_no_data():
    adapter = SnapshotGovernanceAdapter()
    with patch("alpha_os.adapters.calendar.snapshot_adapter.requests.post") as mocked_post:
        mocked_post.return_value = _FakeResponse({"data": {"proposals": []}})
        snapshot = adapter.get_proposals("nonexistent-space.eth")
    assert snapshot.has_data() is False


def test_snapshot_adapter_network_failure_returns_empty():
    adapter = SnapshotGovernanceAdapter()
    with patch("alpha_os.adapters.calendar.snapshot_adapter.requests.post") as mocked_post:
        mocked_post.side_effect = requests.ConnectionError("boom")
        snapshot = adapter.get_proposals("test.eth")
    assert snapshot.has_data() is False


def test_coinmarketcal_no_key_returns_empty_without_network_call():
    adapter = CoinMarketCalAdapter()
    with patch("alpha_os.config.settings.coinmarketcal_api_key", None):
        with patch("alpha_os.adapters.calendar.coinmarketcal_adapter.requests.get") as mocked_get:
            snapshot = adapter.get_coin_events("bitcoin")
    mocked_get.assert_not_called()
    assert snapshot.has_data() is False


def test_coinmarketcal_parses_events():
    # Formato real de la API v2 (verificado en vivo tras encontrar que la
    # v1 asumida originalmente ya no existe).
    payload = {
        "data": [
            {
                "id": "48291",
                "title": "Ethereum Pectra Upgrade",
                "date": "2026-05-06T12:00:00Z",
                "dateEnd": "",
                "dateType": "date",
                "isEstimated": False,
                "displayedDate": "06 May 2026",
                "categories": ["Release"],
                "coins": [{"slug": "ethereum", "symbol": "ETH", "name": "Ethereum"}],
                "impact": None,
                "sourceUrl": "https://blog.ethereum.org/example",
            }
        ],
        "meta": {"total": 1, "limit": 20, "cursor": None},
    }
    adapter = CoinMarketCalAdapter()
    with patch("alpha_os.config.settings.coinmarketcal_api_key", "fake-key"):
        with patch("alpha_os.adapters.calendar.coinmarketcal_adapter.requests.get") as mocked_get:
            mocked_get.return_value = _FakeResponse(payload)
            snapshot = adapter.get_coin_events("ethereum")

    assert snapshot.has_data() is True
    event = snapshot.events[0]
    assert event.title == "Ethereum Pectra Upgrade"
    assert event.displayed_date == "06 May 2026"
    assert event.category == "Release"
    assert event.coin_symbols == ["ETH"]
    assert event.is_estimated is False


def test_coinmarketcal_estimated_event_keeps_displayed_date_for_display():
    """Regla explícita de la doc: cuando isEstimated=True, `date` es una
    ventana/deadline, no un dato literal — displayed_date es lo que se debe
    mostrar, no se debe derivar nada distinto de `date` directamente."""
    payload = {
        "data": [
            {
                "id": "1",
                "title": "Some token unlock",
                "date": "2026-09-30T23:59:59Z",
                "dateEnd": "",
                "dateType": "month",
                "isEstimated": True,
                "displayedDate": "Q3 2026",
                "categories": [],
                "coins": [{"slug": "example", "symbol": "EX", "name": "Example"}],
                "impact": None,
            }
        ],
        "meta": {"total": 1, "limit": 20, "cursor": None},
    }
    adapter = CoinMarketCalAdapter()
    with patch("alpha_os.config.settings.coinmarketcal_api_key", "fake-key"):
        with patch("alpha_os.adapters.calendar.coinmarketcal_adapter.requests.get") as mocked_get:
            mocked_get.return_value = _FakeResponse(payload)
            snapshot = adapter.get_coin_events("example")

    event = snapshot.events[0]
    assert event.is_estimated is True
    assert event.displayed_date == "Q3 2026"


def test_halving_estimate_is_deterministic():
    estimate = next_btc_halving_estimate(1_049_999)
    assert estimate.next_halving_block == 1_050_000
    assert estimate.blocks_remaining == 1

    estimate_after = next_btc_halving_estimate(1_050_000)
    assert estimate_after.next_halving_block == 1_260_000
