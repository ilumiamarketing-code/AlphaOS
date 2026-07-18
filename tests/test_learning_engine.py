from datetime import datetime

from alpha_os.core.enums import (
    AssetClass,
    InvestorProfile,
    OperationSide,
    RiskLevel,
    TimeHorizon,
)
from alpha_os.core.models import ConvictionFactor, OperationEntry, RiskParameters, Signal
from alpha_os.engine.learning_engine import MIN_SAMPLE_SIZE, LearningEngine
from alpha_os.positions.journal import JournalManager
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


def _open_and_close(pm, jm, exit_price, factor_label="trend_direction", factor_weight=18.0):
    signal = Signal(
        ticker="TEST", asset_class=AssetClass.EQUITY, direction="long", price=100.0,
        conviction_score=52.0,
        factors=[ConvictionFactor(label=factor_label, weight_pct=factor_weight, rationale="x")],
        confidence_level=52.0, time_horizon=TimeHorizon.SWING, risk_level=RiskLevel.MEDIUM,
        recommended_investor_profile=InvestorProfile.MODERATE, rationale="test",
    )
    entry = OperationEntry(
        ticker="TEST", asset_class=AssetClass.EQUITY, side=OperationSide.BUY, broker="test",
        executed_at=datetime.utcnow(), entry_price=100.0, quantity=10, capital_invested=1000.0,
        expected_horizon=TimeHorizon.SWING, assumed_risk=RiskLevel.MEDIUM, original_thesis="test",
        original_signal=signal,
    )
    position = pm.register_operation(entry, RiskParameters(stop_loss=90.0))
    jm.open_entry(position.id)
    pm.close(position.id, exit_price=exit_price)
    jm.close_out(position.id)


def test_no_closed_positions_has_no_data():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    engine = LearningEngine(pm, jm)

    report = engine.analyze_factor_performance()
    assert report.has_data() is False
    assert report.factor_performance == []


def test_below_min_sample_marks_insufficient():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    engine = LearningEngine(pm, jm)

    for _ in range(MIN_SAMPLE_SIZE - 1):
        _open_and_close(pm, jm, exit_price=110.0)

    report = engine.analyze_factor_performance()
    assert report.factor_performance[0].has_sufficient_sample is False


def test_at_min_sample_marks_sufficient_and_computes_stats():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    engine = LearningEngine(pm, jm)

    for i in range(MIN_SAMPLE_SIZE):
        profitable = i % 2 == 0
        _open_and_close(pm, jm, exit_price=110.0 if profitable else 95.0)

    report = engine.analyze_factor_performance()
    perf = report.factor_performance[0]
    assert perf.has_sufficient_sample is True
    assert perf.occurrences_supporting == MIN_SAMPLE_SIZE
    assert perf.win_rate_when_supporting == 0.5


def test_contradicting_factor_tracked_separately():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    engine = LearningEngine(pm, jm)

    _open_and_close(pm, jm, exit_price=95.0, factor_label="rsi_overextended", factor_weight=-6.0)

    report = engine.analyze_factor_performance()
    perf = report.factor_performance[0]
    assert perf.occurrences_contradicting == 1
    assert perf.occurrences_supporting == 0
    assert perf.avg_profitability_when_supporting is None
