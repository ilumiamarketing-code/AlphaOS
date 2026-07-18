from datetime import date, datetime, timedelta
from typing import Literal

from alpha_os.core.models import WalletFlowSnapshot, WalletTransaction

# Convención estadística estándar, no un descubrimiento propio.
ANOMALY_STDDEV_THRESHOLD = 2.0
WHALE_STDDEV_THRESHOLD = 3.0
MIN_SAMPLE_FOR_STATS = 5


def empty_snapshot(
    address: str,
    chain: Literal["bitcoin", "ethereum"],
    label: str,
    label_source: str,
    label_confidence: float,
    lookback_days: int,
) -> WalletFlowSnapshot:
    return WalletFlowSnapshot(
        address=address,
        chain=chain,
        label=label,
        label_source=label_source,
        label_confidence=label_confidence,
        lookback_days=lookback_days,
        effective_lookback_days=0,
        total_inflow=0.0,
        total_outflow=0.0,
        net_flow=0.0,
    )


def build_wallet_flow_snapshot(
    address: str,
    chain: Literal["bitcoin", "ethereum"],
    label: str,
    label_source: str,
    label_confidence: float,
    lookback_days: int,
    transactions: list[WalletTransaction],
    now: datetime,
    unit_label: str,
) -> WalletFlowSnapshot:
    """Lógica compartida entre BlockchainInfoAdapter (BTC) y EtherscanAdapter
    (ETH) — misma detección de anomalías/transacciones grandes sobre
    cualquier lista de WalletTransaction, sin importar la chain de origen."""
    if not transactions:
        return empty_snapshot(address, chain, label, label_source, label_confidence, lookback_days)

    total_inflow = sum(t.amount for t in transactions if t.direction == "in")
    total_outflow = sum(t.amount for t in transactions if t.direction == "out")

    oldest_tx_date = min(t.timestamp for t in transactions).date()
    effective_days = min((now.date() - oldest_tx_date).days + 1, lookback_days)

    daily_flows: dict[date, float] = {
        (now.date() - timedelta(days=i)): 0.0 for i in range(effective_days)
    }
    for t in transactions:
        day = t.timestamp.date()
        signed = t.amount if t.direction == "in" else -t.amount
        if day in daily_flows:
            daily_flows[day] += signed

    ordered_days = sorted(daily_flows.keys())
    daily_series = [daily_flows[d] for d in ordered_days]

    is_anomalous = False
    anomaly_description = None
    average_flow = stddev_flow = latest_flow = None
    if len(daily_series) >= MIN_SAMPLE_FOR_STATS:
        baseline = daily_series[:-1]
        latest_flow = daily_series[-1]
        average_flow = sum(baseline) / len(baseline)
        variance = sum((x - average_flow) ** 2 for x in baseline) / len(baseline)
        stddev_flow = variance ** 0.5
        deviation = abs(latest_flow - average_flow)
        # Baseline perfectamente plano (stddev=0): cualquier desviación real
        # ya es anómala por definición — un stddev de 0 no debe bloquear la
        # detección, es el caso más claro de ruptura de patrón posible.
        if stddev_flow > 0:
            triggered = deviation > ANOMALY_STDDEV_THRESHOLD * stddev_flow
        else:
            triggered = deviation > max(0.01, abs(average_flow) * 0.05)
        if triggered:
            is_anomalous = True
            direction_word = "entrada" if latest_flow > average_flow else "salida"
            anomaly_description = (
                f"Flujo neto del último día ({latest_flow:.4f} {unit_label}) se desvía "
                f">{ANOMALY_STDDEV_THRESHOLD:.0f} desviaciones estándar del promedio "
                f"({average_flow:.4f} {unit_label}) — {direction_word} anómala, sin interpretar causa."
            )

    large_transactions = []
    if len(transactions) >= MIN_SAMPLE_FOR_STATS:
        # Mediana + desviación absoluta mediana (MAD): robusta a outliers, a
        # diferencia de media+std, que el propio outlier infla hasta
        # esconderse a sí mismo del umbral.
        amounts = sorted(t.amount for t in transactions)
        median_amount = amounts[len(amounts) // 2]
        abs_deviations = sorted(abs(a - median_amount) for a in amounts)
        mad = abs_deviations[len(abs_deviations) // 2]
        threshold = median_amount + WHALE_STDDEV_THRESHOLD * 1.4826 * mad if mad > 0 else median_amount
        large_transactions = [t for t in transactions if t.amount > threshold and t.amount > median_amount]

    return WalletFlowSnapshot(
        address=address,
        chain=chain,
        label=label,
        label_source=label_source,
        label_confidence=label_confidence,
        lookback_days=lookback_days,
        effective_lookback_days=effective_days,
        total_inflow=total_inflow,
        total_outflow=total_outflow,
        net_flow=total_inflow - total_outflow,
        daily_net_flows=daily_series,
        average_daily_net_flow=average_flow,
        stddev_daily_net_flow=stddev_flow,
        latest_day_net_flow=latest_flow,
        is_anomalous=is_anomalous,
        anomaly_description=anomaly_description,
        large_transactions=large_transactions,
    )
