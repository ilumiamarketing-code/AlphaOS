import pytest

from alpha_os.core.enums import (
    AssetClass,
    InvestorProfile,
    OperationSide,
    RiskLevel,
    TimeHorizon,
)
from alpha_os.core.models import ConvictionFactor, OperationEntry, RiskParameters, Signal
from alpha_os.positions.journal import JournalManager
from alpha_os.positions.position_manager import PositionManager, PositionNotFoundError
from alpha_os.positions.storage import SQLiteJSONStore
from datetime import datetime


def _entry(signal=None) -> OperationEntry:
    return OperationEntry(
        ticker="TEST",
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
        original_signal=signal,
    )


def _signal(factors=None) -> Signal:
    return Signal(
        ticker="TEST",
        asset_class=AssetClass.EQUITY,
        direction="long",
        price=100.0,
        conviction_score=52.0,
        factors=factors or [ConvictionFactor(label="trend_direction", weight_pct=18.0, rationale="x")],
        confidence_level=52.0,
        time_horizon=TimeHorizon.SWING,
        risk_level=RiskLevel.MEDIUM,
        recommended_investor_profile=InvestorProfile.MODERATE,
        rationale="test",
    )


def test_position_survives_across_separate_store_instances(tmp_path):
    """Simula un reinicio del servidor: dos SQLiteJSONStore distintos
    apuntando al mismo archivo deben ver los mismos datos."""
    db_path = tmp_path / "test.db"

    store_a = SQLiteJSONStore(db_path)
    pm_a = PositionManager(store=store_a)
    position = pm_a.register_operation(_entry(), RiskParameters(stop_loss=90.0))

    store_b = SQLiteJSONStore(db_path)
    pm_b = PositionManager(store=store_b)
    recovered = pm_b.get(position.id)

    assert recovered.id == position.id
    assert recovered.entry.ticker == "TEST"


def test_get_missing_position_raises():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    with pytest.raises(PositionNotFoundError):
        pm.get("does-not-exist")


def test_close_out_computes_profitability():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)

    position = pm.register_operation(_entry(), RiskParameters(stop_loss=90.0))
    jm.open_entry(position.id)
    pm.close(position.id, exit_price=110.0)
    entry = jm.close_out(position.id)

    assert entry.profitability_pct == pytest.approx(10.0)


def test_post_mortem_requires_closed_position():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    position = pm.register_operation(_entry(signal=_signal()), RiskParameters(stop_loss=90.0))
    jm.open_entry(position.id)

    with pytest.raises(ValueError):
        jm.generate_post_mortem(position.id)


def test_post_mortem_requires_original_signal():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    position = pm.register_operation(_entry(signal=None), RiskParameters(stop_loss=90.0))
    jm.open_entry(position.id)
    pm.close(position.id, exit_price=110.0)
    jm.close_out(position.id)

    with pytest.raises(NotImplementedError):
        jm.generate_post_mortem(position.id)


def test_post_mortem_profitable_lists_supporting_factors():
    store = SQLiteJSONStore(":memory:")
    pm = PositionManager(store=store)
    jm = JournalManager(position_manager=pm, store=store)
    factors = [
        ConvictionFactor(label="trend_direction", weight_pct=18.0, rationale="x"),
        ConvictionFactor(label="rsi_overextended", weight_pct=-6.0, rationale="y"),
    ]
    position = pm.register_operation(_entry(signal=_signal(factors)), RiskParameters(stop_loss=90.0))
    jm.open_entry(position.id)
    pm.close(position.id, exit_price=110.0)
    jm.close_out(position.id)

    post_mortem = jm.generate_post_mortem(position.id)
    assert "trend_direction" in post_mortem.signals_that_anticipated_move
    assert "rsi_overextended" not in post_mortem.signals_that_anticipated_move
