from datetime import datetime

from alpha_os.core.enums import (
    AssetClass,
    InvestorProfile,
    OperationSide,
    RiskLevel,
    TimeHorizon,
)
from alpha_os.core.models import ConvictionFactor, OperationEntry, RiskParameters, Signal
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


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


def _signal(direction="long", conviction_score=52.0, factors=None) -> Signal:
    return Signal(
        ticker="TEST",
        asset_class=AssetClass.EQUITY,
        direction=direction,
        price=100.0,
        conviction_score=conviction_score,
        factors=factors if factors is not None else [ConvictionFactor(label="trend_direction", weight_pct=18.0, rationale="tendencia alcista")],
        confidence_level=conviction_score,
        time_horizon=TimeHorizon.SWING,
        risk_level=RiskLevel.MEDIUM,
        recommended_investor_profile=InvestorProfile.MODERATE,
        rationale="test",
    )


class _FakeSignalEngine:
    def __init__(self, signal):
        self._signal = signal

    def generate_signal(self, ticker, asset_class):
        return self._signal


def test_reassess_thesis_without_original_signal_is_honest_not_fabricated():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    position = pm.register_operation(_entry(signal=None), RiskParameters(stop_loss=90.0))

    result = pm.reassess_thesis(position.id, _FakeSignalEngine(_signal()))

    assert result.still_valid is False
    assert "sin línea base" in result.what_changed


def test_reassess_thesis_without_fresh_signal_available():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    position = pm.register_operation(_entry(signal=_signal()), RiskParameters(stop_loss=90.0))

    result = pm.reassess_thesis(position.id, _FakeSignalEngine(None))

    assert result.still_valid is False
    assert "datos insuficientes" in result.what_changed


def test_reassess_thesis_still_valid_when_direction_and_factors_unchanged():
    original = _signal(direction="long", conviction_score=52.0)
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    position = pm.register_operation(_entry(signal=original), RiskParameters(stop_loss=90.0))

    fresh = _signal(direction="long", conviction_score=60.0)
    result = pm.reassess_thesis(position.id, _FakeSignalEngine(fresh))

    assert result.still_valid is True
    assert result.success_probability_delta == 8.0
    assert "sin cambios" in result.what_changed


def test_reassess_thesis_invalid_when_direction_flips():
    original = _signal(direction="long")
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    position = pm.register_operation(_entry(signal=original), RiskParameters(stop_loss=90.0))

    fresh = _signal(direction="short")
    result = pm.reassess_thesis(position.id, _FakeSignalEngine(fresh))

    assert result.still_valid is False
    assert "ya no se sostiene" in result.what_changed


def test_reassess_thesis_narrates_disappeared_and_new_factors():
    original = _signal(factors=[ConvictionFactor(label="momentum", weight_pct=15.0, rationale="momentum fuerte")])
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    position = pm.register_operation(_entry(signal=original), RiskParameters(stop_loss=90.0))

    fresh = _signal(factors=[ConvictionFactor(label="institutional_flow", weight_pct=10.0, rationale="flujo institucional entrando")])
    result = pm.reassess_thesis(position.id, _FakeSignalEngine(fresh))

    assert "momentum" in result.what_changed
    assert "institutional_flow" in result.what_changed
