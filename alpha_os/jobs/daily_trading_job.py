from datetime import datetime

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.config import settings
from alpha_os.core.enums import AssetClass, OperationSide
from alpha_os.core.models import DailyTradingRunResult, OperationEntry, PaperOrderRequest, RiskParameters
from alpha_os.engine.signal_engine import SignalEngine
from alpha_os.positions.position_manager import PositionManager

DOLLARS_PER_TRADE = 1000.0

_last_run: DailyTradingRunResult | None = None


def get_last_run() -> DailyTradingRunResult | None:
    return _last_run


async def run_daily_trading_job(
    signal_engine: SignalEngine,
    ibkr: IBKRAdapter,
    position_manager: PositionManager,
) -> DailyTradingRunResult:
    """Escanea `settings.watchlist` una vez: para cada ticker sin posición
    activa ya abierta, pide una señal fresca (ya filtrada por
    confianza/contradicciones dentro de `SignalEngine.generate_signal` —
    cualquier señal no-`None` ya superó el umbral) y, si hay señal, coloca
    una orden real de ~$1,000 en la cuenta paper de IBKR. **Solo se registra
    una posición en AlphaOS si la orden realmente se llenó** (`status ==
    "Filled"`) — verificado en vivo que una orden de mercado DAY fuera de
    horario de mercado queda `Cancelled` por IBKR con `filled=0`; si se
    registrara igual, quedaría una posición fantasma en AlphaOS sin
    contraparte real en el broker. Nunca duplica una posición sobre el
    mismo ticker mientras siga abierta."""
    global _last_run
    actions: list[str] = []
    active_tickers = {p.entry.ticker for p in position_manager.list_active()}

    for ticker, asset_class in settings.watchlist:
        if ticker in active_tickers:
            actions.append(f"{ticker}: ya hay una posición activa — se omite.")
            continue

        signal = signal_engine.generate_signal(ticker, asset_class)
        if signal is None:
            actions.append(f"{ticker}: sin señal (no superó el umbral de confianza).")
            continue

        price = signal.suggested_entry or signal.price
        quantity = DOLLARS_PER_TRADE / price
        if asset_class == AssetClass.EQUITY:
            quantity = float(int(quantity))
            if quantity < 1:
                actions.append(
                    f"{ticker}: ${DOLLARS_PER_TRADE:.0f} no alcanza para 1 acción a ${price:.2f} — se omite."
                )
                continue

        side = "BUY" if signal.direction == "long" else "SELL"
        order_result = await ibkr.place_test_order(
            PaperOrderRequest(
                ticker=ticker,
                asset_class=asset_class,
                side=side,
                quantity=quantity,
                order_type="MKT",
                # Cripto fraccionaria va por cantidad de efectivo — verificado
                # en vivo que IBKR rechaza cantidad de moneda fraccionaria.
                cash_amount=DOLLARS_PER_TRADE if asset_class == AssetClass.CRYPTO else None,
            )
        )

        if order_result.status != "Filled" or not order_result.filled_quantity:
            reason = order_result.rejected_reason or (
                f"orden no se llenó (status={order_result.status}) — probablemente fuera de horario de mercado."
            )
            actions.append(f"{ticker}: {reason}")
            continue

        filled_quantity = order_result.filled_quantity
        fill_price = order_result.avg_fill_price or price
        entry = OperationEntry(
            ticker=ticker,
            asset_class=asset_class,
            side=OperationSide.BUY if side == "BUY" else OperationSide.SELL,
            broker="ibkr_paper",
            executed_at=datetime.utcnow(),
            entry_price=fill_price,
            quantity=filled_quantity,
            capital_invested=filled_quantity * fill_price,
            expected_horizon=signal.time_horizon,
            assumed_risk=signal.risk_level,
            original_thesis=signal.rationale,
            original_signal=signal,
        )
        risk_params = RiskParameters(
            stop_loss=signal.stop_loss or fill_price * 0.95,
            take_profit=signal.take_profit_targets[0] if signal.take_profit_targets else None,
            risk_reward_ratio=signal.risk_reward_ratio,
        )
        position = position_manager.register_operation(entry, risk_params)
        active_tickers.add(ticker)
        actions.append(
            f"{ticker}: orden {side} de {filled_quantity:g} llenada a ${fill_price:.2f} "
            f"(order_id={order_result.order_id}) — posición {position.id} registrada en AlphaOS."
        )

    _last_run = DailyTradingRunResult(actions=actions)
    return _last_run
