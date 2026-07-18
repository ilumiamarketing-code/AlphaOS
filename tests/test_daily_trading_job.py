from datetime import datetime

from alpha_os.core.enums import (
    AssetClass,
    InvestorProfile,
    OperationSide,
    RiskLevel,
    TimeHorizon,
)
from alpha_os.core.models import OperationEntry, PaperOrderResult, RiskParameters, Signal
from alpha_os.jobs.daily_trading_job import run_daily_trading_job
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


def _signal(ticker="NVDA", direction="long", price=100.0, suggested_entry=None, stop_loss=90.0) -> Signal:
    return Signal(
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        direction=direction,
        price=price,
        conviction_score=70.0,
        confidence_level=70.0,
        time_horizon=TimeHorizon.SWING,
        risk_level=RiskLevel.MEDIUM,
        recommended_investor_profile=InvestorProfile.MODERATE,
        suggested_entry=suggested_entry or price,
        stop_loss=stop_loss,
        take_profit_targets=[120.0],
        rationale="test",
    )


class _FakeSignalEngine:
    def __init__(self, signals_by_ticker: dict):
        self._signals = signals_by_ticker

    def generate_signal(self, ticker, asset_class):
        return self._signals.get(ticker)


class _FakeIBKRAdapter:
    def __init__(self, result_by_ticker=None, default_status="Filled"):
        self._result_by_ticker = result_by_ticker or {}
        self._default_status = default_status
        self.calls = []

    async def place_test_order(self, request):
        self.calls.append(request)
        if request.ticker in self._result_by_ticker:
            return self._result_by_ticker[request.ticker]
        return PaperOrderResult(
            account="DU1234567",
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            status=self._default_status,
            order_id=1,
            filled_quantity=request.quantity,
            avg_fill_price=100.0,
        )


def _register_position(pm: PositionManager, ticker: str) -> None:
    entry = OperationEntry(
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        side=OperationSide.BUY,
        broker="test",
        executed_at=datetime.utcnow(),
        entry_price=100.0,
        quantity=10,
        capital_invested=1000.0,
        expected_horizon=TimeHorizon.SWING,
        assumed_risk=RiskLevel.MEDIUM,
        original_thesis="test",
    )
    pm.register_operation(entry, RiskParameters(stop_loss=90.0))


async def test_skips_ticker_with_existing_active_position(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register_position(pm, "NVDA")

    result = await run_daily_trading_job(_FakeSignalEngine({}), _FakeIBKRAdapter(), pm)

    assert "ya hay una posición activa" in result.actions[0]
    assert len(pm.list_active()) == 1


async def test_skips_ticker_without_signal(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))

    result = await run_daily_trading_job(_FakeSignalEngine({}), _FakeIBKRAdapter(), pm)

    assert "sin señal" in result.actions[0]
    assert len(pm.list_active()) == 0


async def test_skips_and_logs_when_order_rejected(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    rejected = PaperOrderResult(
        account="", ticker="NVDA", side="BUY", quantity=10, order_type="MKT",
        status="rejected", rejected_reason="no TWS running",
    )
    ibkr = _FakeIBKRAdapter(result_by_ticker={"NVDA": rejected})

    result = await run_daily_trading_job(_FakeSignalEngine({"NVDA": _signal()}), ibkr, pm)

    assert "no TWS running" in result.actions[0]
    assert len(pm.list_active()) == 0


async def test_skips_and_does_not_register_when_order_cancelled_unfilled(monkeypatch):
    """Caso real encontrado en vivo: una orden MKT DAY fuera de horario de
    mercado queda 'Cancelled' por IBKR con filled=0 — nunca debe registrarse
    como posición, aunque técnicamente no fue "rechazada" por el adapter."""
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    cancelled = PaperOrderResult(
        account="DU1234567", ticker="NVDA", side="BUY", quantity=10, order_type="MKT",
        status="Cancelled", order_id=9, filled_quantity=0.0, avg_fill_price=0.0,
    )
    ibkr = _FakeIBKRAdapter(result_by_ticker={"NVDA": cancelled})

    result = await run_daily_trading_job(_FakeSignalEngine({"NVDA": _signal()}), ibkr, pm)

    assert "no se llenó" in result.actions[0]
    assert len(pm.list_active()) == 0


async def test_registers_position_with_original_signal_on_accepted_order(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    signal = _signal(ticker="NVDA", price=100.0)

    result = await run_daily_trading_job(_FakeSignalEngine({"NVDA": signal}), _FakeIBKRAdapter(), pm)

    positions = pm.list_active()
    assert len(positions) == 1
    assert positions[0].entry.ticker == "NVDA"
    assert positions[0].entry.original_signal.ticker == "NVDA"
    assert "registrada en AlphaOS" in result.actions[0]


async def test_equity_quantity_is_whole_shares(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("NVDA", AssetClass.EQUITY)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    signal = _signal(ticker="NVDA", price=333.33)
    ibkr = _FakeIBKRAdapter()

    await run_daily_trading_job(_FakeSignalEngine({"NVDA": signal}), ibkr, pm)

    assert ibkr.calls[0].quantity == 3.0  # floor(1000 / 333.33) = 3


async def test_crypto_quantity_can_be_fractional(monkeypatch):
    monkeypatch.setattr("alpha_os.jobs.daily_trading_job.settings.watchlist", [("BTC-USD", AssetClass.CRYPTO)])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    signal = Signal(
        ticker="BTC-USD",
        asset_class=AssetClass.CRYPTO,
        direction="long",
        price=50000.0,
        conviction_score=70.0,
        confidence_level=70.0,
        time_horizon=TimeHorizon.SWING,
        risk_level=RiskLevel.MEDIUM,
        recommended_investor_profile=InvestorProfile.MODERATE,
        suggested_entry=50000.0,
        stop_loss=45000.0,
        rationale="test",
    )
    ibkr = _FakeIBKRAdapter()

    await run_daily_trading_job(_FakeSignalEngine({"BTC-USD": signal}), ibkr, pm)

    assert ibkr.calls[0].quantity == 0.02  # 1000 / 50000
