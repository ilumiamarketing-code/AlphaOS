from datetime import datetime, timedelta, timezone

from alpha_os.adapters.onchain._wallet_flow_common import build_wallet_flow_snapshot
from alpha_os.adapters.onchain.blockchain_info_adapter import BlockchainInfoAdapter
from alpha_os.core.models import WalletTransaction

NOW = datetime.now(timezone.utc)


def _tx(days_ago: int, amount: float, direction: str, hash_suffix: str) -> WalletTransaction:
    return WalletTransaction(
        tx_hash=f"hash-{hash_suffix}",
        timestamp=NOW - timedelta(days=days_ago),
        amount=amount,
        direction=direction,
    )


def test_label_is_never_fabricated_or_overridden():
    """Spec sección 1: nunca asumir automáticamente la identidad de una
    wallet — lo que declara el caller debe pasar intacto."""
    snapshot = build_wallet_flow_snapshot(
        "1abc", "bitcoin",
        "Mi etiqueta de prueba, no verificada",
        "Yo mismo, sin verificación externa",
        0.1, 30, [_tx(1, 1.0, "in", "a")], NOW, "BTC",
    )
    assert snapshot.label == "Mi etiqueta de prueba, no verificada"
    assert snapshot.label_source == "Yo mismo, sin verificación externa"
    assert snapshot.label_confidence == 0.1


def test_no_transactions_returns_insufficient_data():
    snapshot = build_wallet_flow_snapshot("1abc", "bitcoin", "x", "x", 0.5, 30, [], NOW, "BTC")
    assert snapshot.has_data() is False
    assert snapshot.is_anomalous is False


def test_anomalous_net_flow_detected():
    # 6 dias estables con flujo neto pequeño, el ultimo dia un salto grande
    txs = [_tx(days_ago=d, amount=1.0, direction="in", hash_suffix=str(d)) for d in range(6, 0, -1)]
    txs.append(_tx(days_ago=0, amount=50.0, direction="in", hash_suffix="latest"))
    snapshot = build_wallet_flow_snapshot(
        "1abc", "bitcoin", "x", "x", 0.5, 30, txs, NOW, "BTC"
    )
    assert snapshot.is_anomalous is True
    assert "desviaciones estándar" in snapshot.anomaly_description


def test_stable_flow_is_not_anomalous():
    txs = [_tx(days_ago=d, amount=1.0 + (d % 2) * 0.1, direction="in", hash_suffix=str(d)) for d in range(6, -1, -1)]
    snapshot = build_wallet_flow_snapshot(
        "1abc", "bitcoin", "x", "x", 0.5, 30, txs, NOW, "BTC"
    )
    assert snapshot.is_anomalous is False


def test_large_transaction_flagged_by_dynamic_threshold():
    txs = [_tx(days_ago=1, amount=1.0, direction="in", hash_suffix=str(i)) for i in range(6)]
    txs.append(_tx(days_ago=1, amount=100.0, direction="in", hash_suffix="whale"))
    snapshot = build_wallet_flow_snapshot(
        "1abc", "bitcoin", "x", "x", 0.5, 30, txs, NOW, "BTC"
    )
    flagged_hashes = {t.tx_hash for t in snapshot.large_transactions}
    assert "hash-whale" in flagged_hashes
    assert "hash-0" not in flagged_hashes  # las pequeñas no se marcan


def test_small_uniform_sample_flags_no_whales():
    """El umbral es dinámico según el activo/wallet — una muestra sin
    outliers no debe marcar nada como "grande"."""
    txs = [_tx(days_ago=1, amount=1.0, direction="in", hash_suffix=str(i)) for i in range(6)]
    snapshot = build_wallet_flow_snapshot(
        "1abc", "bitcoin", "x", "x", 0.5, 30, txs, NOW, "BTC"
    )
    assert snapshot.large_transactions == []


def test_network_health_missing_source_data_has_no_data():
    adapter = BlockchainInfoAdapter()
    adapter._get_chart = lambda chart: []  # simula fuente caída
    health = adapter.get_network_health()
    assert health.has_data() is False
