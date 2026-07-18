from datetime import datetime

from alpha_os.core.enums import (
    AssetClass,
    LiquidityRegime,
    OperationSide,
    RiskLevel,
    RiskRegime,
    TimeHorizon,
    TrendRegime,
)
from alpha_os.core.models import MarketRegimeAssessment, OperationEntry, RiskParameters
from alpha_os.positions.portfolio_manager import PortfolioManager
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


class _FakeCorrelationAdapter:
    def __init__(self, correlations=None):
        self._correlations = correlations or []

    def get_correlations(self, tickers, lookback="3mo"):
        return self._correlations


class _FakeRegimeEngine:
    def __init__(self, assessment):
        self._assessment = assessment

    def assess(self):
        return self._assessment


def _neutral_regime(**overrides) -> MarketRegimeAssessment:
    defaults = dict(
        trend_regime=TrendRegime.SIDEWAYS,
        risk_regime=RiskRegime.RISK_ON,
        liquidity_regime=LiquidityRegime.EXPANSION,
        high_volatility_event=False,
        confidence=0.9,
        justification=["test"],
        weight_adjustments={},
        reference_index="^GSPC",
    )
    defaults.update(overrides)
    return MarketRegimeAssessment(**defaults)


def _register(pm, ticker, asset_class, capital=1000.0, sector=None, side=OperationSide.BUY):
    entry = OperationEntry(
        ticker=ticker, asset_class=asset_class, side=side, broker="test",
        executed_at=datetime.utcnow(), entry_price=100.0, quantity=10, capital_invested=capital,
        expected_horizon=TimeHorizon.SWING, assumed_risk=RiskLevel.MEDIUM, original_thesis="test", sector=sector,
    )
    return pm.register_operation(entry, RiskParameters(stop_loss=90.0))


def test_exposure_aggregates_by_asset_class():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "AAPL", AssetClass.EQUITY, capital=2000.0)
    _register(pm, "BTC-USD", AssetClass.CRYPTO, capital=1000.0)

    portfolio = PortfolioManager(pm, _FakeCorrelationAdapter(), _FakeRegimeEngine(_neutral_regime()))
    exposure = portfolio.compute_exposure()

    assert exposure.by_asset_class == {"equity": 2000.0, "crypto": 1000.0}


def test_asset_class_concentration_flagged():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "BTC-USD", AssetClass.CRYPTO, capital=7000.0)
    _register(pm, "AAPL", AssetClass.EQUITY, capital=3000.0)

    portfolio = PortfolioManager(pm, _FakeCorrelationAdapter(), _FakeRegimeEngine(_neutral_regime()))
    report = portfolio.generate_risk_report()

    assert any("crypto" in flag for flag in report.overexposure_flags)


def test_high_correlation_pairs_filters_by_threshold():
    from alpha_os.core.models import CrossAssetCorrelation

    correlations = [
        CrossAssetCorrelation(asset_a="BTC-USD", asset_b="ETH-USD", correlation=0.9, window_days=90),
        CrossAssetCorrelation(asset_a="AAPL", asset_b="BTC-USD", correlation=0.3, window_days=90),
    ]
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "BTC-USD", AssetClass.CRYPTO)
    _register(pm, "ETH-USD", AssetClass.CRYPTO)
    _register(pm, "AAPL", AssetClass.EQUITY)

    portfolio = PortfolioManager(
        pm, _FakeCorrelationAdapter(correlations), _FakeRegimeEngine(_neutral_regime())
    )
    report = portfolio.generate_risk_report()

    assert ("BTC-USD", "ETH-USD", 0.9) in report.high_correlation_pairs
    assert not any(pair[:2] == ("AAPL", "BTC-USD") for pair in report.high_correlation_pairs)


def test_systemic_risk_flags_crypto_during_high_volatility():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "BTC-USD", AssetClass.CRYPTO, capital=7000.0)
    _register(pm, "AAPL", AssetClass.EQUITY, capital=3000.0)

    regime = _neutral_regime(trend_regime=TrendRegime.BEAR_CAPITULATION, high_volatility_event=True)
    portfolio = PortfolioManager(pm, _FakeCorrelationAdapter(), _FakeRegimeEngine(regime))
    report = portfolio.generate_risk_report()

    assert any("alta volatilidad" in note for note in report.systemic_risk_notes)


def test_systemic_risk_flags_long_equity_during_bear_market():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "AAPL", AssetClass.EQUITY, capital=8000.0, side=OperationSide.BUY)
    _register(pm, "BTC-USD", AssetClass.CRYPTO, capital=2000.0)

    regime = _neutral_regime(trend_regime=TrendRegime.BEAR_DISTRIBUTION)
    portfolio = PortfolioManager(pm, _FakeCorrelationAdapter(), _FakeRegimeEngine(regime))
    report = portfolio.generate_risk_report()

    assert any("bear_market_distribution" in note for note in report.systemic_risk_notes)


def test_no_flags_reported_when_regime_neutral_and_no_concentration():
    pm = PositionManager(store=SQLiteJSONStore(":memory:"))
    _register(pm, "AAPL", AssetClass.EQUITY, capital=1000.0)
    _register(pm, "BTC-USD", AssetClass.CRYPTO, capital=1000.0)

    portfolio = PortfolioManager(pm, _FakeCorrelationAdapter(), _FakeRegimeEngine(_neutral_regime()))
    report = portfolio.generate_risk_report()

    assert "Sin banderas de riesgo sistémico" in report.systemic_risk_notes[0]
