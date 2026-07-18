import time
from unittest.mock import patch

import requests

from alpha_os.adapters.onchain.etherscan_adapter import EtherscanAdapter


def test_no_api_key_returns_empty_snapshot_without_network_call():
    """Sin ETHERSCAN_API_KEY configurada, debe comportarse igual que el
    resto de adapters: vacío, sin fallar ni intentar la llamada de red.
    Se fuerza el estado explícitamente — el entorno real puede o no tener
    una key configurada según lo que el usuario haya guardado en .env."""
    adapter = EtherscanAdapter()
    with patch("alpha_os.config.settings.etherscan_api_key", None):
        with patch("alpha_os.adapters.onchain.etherscan_adapter.requests.get") as mocked_get:
            snapshot = adapter.get_wallet_flow(
                "0x0000000000000000000000000000000000dEaD", "test", "test", 0.5, 30
            )
    mocked_get.assert_not_called()
    assert snapshot.has_data() is False
    assert snapshot.chain == "ethereum"


def _fake_response(payload: dict):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    return _Resp()


def test_parses_wei_to_eth_and_direction_correctly():
    address = "0xAAAA000000000000000000000000000000AAAA"
    now_ts = int(time.time())
    payload = {
        "status": "1",
        "message": "OK",
        "result": [
            {
                "hash": "0xin",
                "timeStamp": str(now_ts),
                "value": str(2 * 10**18),  # 2 ETH
                "to": address.lower(),
                "from": "0xbbbb000000000000000000000000000000bbbb",
            },
            {
                "hash": "0xout",
                "timeStamp": str(now_ts),
                "value": str(1 * 10**18),  # 1 ETH
                "to": "0xcccc000000000000000000000000000000cccc",
                "from": address.lower(),
            },
            {
                "hash": "0xcontract",
                "timeStamp": str(now_ts),
                "value": "0",  # interacción de contrato, sin transferencia nativa
                "to": address.lower(),
                "from": "0xdddd000000000000000000000000000000dddd",
            },
        ],
    }

    adapter = EtherscanAdapter()
    with patch("alpha_os.config.settings.etherscan_api_key", "fake-key"):
        with patch("alpha_os.adapters.onchain.etherscan_adapter.requests.get") as mocked_get:
            mocked_get.side_effect = [
                _fake_response(payload),
                _fake_response({"status": "0", "message": "No transactions found", "result": []}),
            ]
            snapshot = adapter.get_wallet_flow(address, "test", "test", 0.5, lookback_days=30)

    assert snapshot.total_inflow == 2.0
    assert snapshot.total_outflow == 1.0
    assert snapshot.net_flow == 1.0


def test_api_failure_returns_empty_snapshot_not_crash():
    adapter = EtherscanAdapter()
    with patch("alpha_os.config.settings.etherscan_api_key", "fake-key"):
        with patch("alpha_os.adapters.onchain.etherscan_adapter.requests.get") as mocked_get:
            mocked_get.side_effect = requests.ConnectionError("boom")
            snapshot = adapter.get_wallet_flow("0xabc", "test", "test", 0.5, 30)
    assert snapshot.has_data() is False
