from alpha_os.core.enums import LiquidityRegime, RiskRegime, TrendRegime
from alpha_os.core.models import ConvictionFactor, DerivativesSnapshot, MarketRegimeAssessment, StablecoinSnapshot
from alpha_os.engine.signal_engine import (
    _apply_regime_adjustments,
    _derivatives_factors,
    _stablecoin_factors,
)


def test_crowded_long_derivatives_produces_risk_factor_for_long_hypothesis():
    snapshot = DerivativesSnapshot(
        symbol="BTCUSDT", funding_rate=0.001, open_interest=100, long_short_ratio=2.5
    )
    factors = _derivatives_factors(snapshot, "long")
    assert len(factors) == 1
    assert factors[0].label == "derivatives_leverage_risk"
    assert factors[0].weight_pct < 0  # contrarian: nunca confirma, solo advierte


def test_crowded_short_derivatives_produces_risk_factor_for_short_hypothesis():
    snapshot = DerivativesSnapshot(
        symbol="BTCUSDT", funding_rate=-0.001, open_interest=100, long_short_ratio=0.3
    )
    factors = _derivatives_factors(snapshot, "short")
    assert len(factors) == 1
    assert factors[0].weight_pct < 0


def test_normal_derivatives_produces_no_factor():
    snapshot = DerivativesSnapshot(
        symbol="BTCUSDT", funding_rate=0.00001, open_interest=100, long_short_ratio=1.05
    )
    assert _derivatives_factors(snapshot, "long") == []
    assert _derivatives_factors(snapshot, "short") == []


def test_stablecoin_supply_growth_supports_long_not_short():
    snapshot = StablecoinSnapshot(symbol="USDT", supply_change_7d_pct=0.05)
    long_factors = _stablecoin_factors(snapshot, "long")
    short_factors = _stablecoin_factors(snapshot, "short")
    assert len(long_factors) == 1
    assert long_factors[0].weight_pct > 0
    assert short_factors == []


def test_stablecoin_missing_data_produces_no_factor():
    snapshot = StablecoinSnapshot(symbol="USDT")
    assert _stablecoin_factors(snapshot, "long") == []


def _regime(weight_adjustments: dict[str, float]) -> MarketRegimeAssessment:
    return MarketRegimeAssessment(
        trend_regime=TrendRegime.BULL_EXPANSION,
        risk_regime=RiskRegime.RISK_ON,
        liquidity_regime=LiquidityRegime.EXPANSION,
        high_volatility_event=False,
        confidence=0.9,
        justification=["test"],
        weight_adjustments=weight_adjustments,
        reference_index="^GSPC",
    )


def test_regime_adjustment_rescales_matching_factor():
    factors = [ConvictionFactor(label="trend_direction", weight_pct=18.0, rationale="x")]
    adjusted = _apply_regime_adjustments(factors, _regime({"trend_direction": 1.3}))
    assert adjusted[0].weight_pct == 18.0 * 1.3


def test_regime_adjustment_leaves_unlisted_factor_unchanged():
    factors = [ConvictionFactor(label="fundamental_health", weight_pct=10.0, rationale="x")]
    adjusted = _apply_regime_adjustments(factors, _regime({"trend_direction": 1.3}))
    assert adjusted[0].weight_pct == 10.0
    assert adjusted[0] is factors[0]  # sin ajuste, no se reconstruye el factor
