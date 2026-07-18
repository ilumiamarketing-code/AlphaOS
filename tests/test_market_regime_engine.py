import numpy as np
import pandas as pd

from alpha_os.core.enums import LiquidityRegime, RiskRegime, TrendRegime
from alpha_os.core.models import MacroSnapshot
from alpha_os.engine.market_regime_engine import MarketRegimeEngine

REFERENCE = "^GSPC"
VIX = "^VIX"


class _FakeMarketData:
    def __init__(self, close_by_ticker: dict[str, pd.Series]):
        self._close_by_ticker = close_by_ticker

    def get_ohlcv(self, ticker, interval="1d", lookback="1y"):
        close = self._close_by_ticker.get(ticker)
        if close is None:
            raise ValueError(f"no fake data for {ticker}")
        return pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1_000}
        )

    def get_quote(self, ticker):
        raise NotImplementedError


class _FakeMacroData:
    def __init__(self, snapshot: MacroSnapshot):
        self._snapshot = snapshot

    def get_snapshot(self) -> MacroSnapshot:
        return self._snapshot


_EMPTY_MACRO = MacroSnapshot()


def _bull_close(n=260) -> pd.Series:
    return pd.Series(np.linspace(100, 200, n))


def _capitulation_close(n=260) -> pd.Series:
    rng = np.random.default_rng(7)
    rising = np.linspace(100, 200, 200)
    crash = np.linspace(200, 90, 60) * (1 + rng.normal(0, 0.04, 60))
    return pd.Series(np.concatenate([rising, crash]))


def _sideways_close(n=260) -> pd.Series:
    rng = np.random.default_rng(3)
    return pd.Series(100 + rng.normal(0, 0.3, n))


def _flat_vix(level: float, n=25) -> pd.Series:
    return pd.Series([level] * n)


def test_bull_expansion_detected_near_52w_high():
    market_data = _FakeMarketData({REFERENCE: _bull_close(), VIX: _flat_vix(15.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.trend_regime == TrendRegime.BULL_EXPANSION


def test_bear_capitulation_detected_on_deep_drawdown_and_high_vol():
    market_data = _FakeMarketData({REFERENCE: _capitulation_close(), VIX: _flat_vix(35.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.trend_regime == TrendRegime.BEAR_CAPITULATION
    assert assessment.high_volatility_event is True


def test_sideways_detected_on_flat_low_vol_series():
    market_data = _FakeMarketData({REFERENCE: _sideways_close(), VIX: _flat_vix(15.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.trend_regime == TrendRegime.SIDEWAYS


def test_high_vix_produces_risk_off():
    market_data = _FakeMarketData({REFERENCE: _bull_close(), VIX: _flat_vix(28.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.risk_regime == RiskRegime.RISK_OFF


def test_low_vix_produces_risk_on():
    market_data = _FakeMarketData({REFERENCE: _bull_close(), VIX: _flat_vix(14.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.risk_regime == RiskRegime.RISK_ON


def test_liquidity_regime_follows_macro_trend():
    market_data = _FakeMarketData({REFERENCE: _bull_close(), VIX: _flat_vix(15.0)})
    macro = MacroSnapshot(fed_funds_rate=5.0, cpi_yoy=0.03, global_liquidity_trend="contracting")
    engine = MarketRegimeEngine(market_data, _FakeMacroData(macro), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.liquidity_regime == LiquidityRegime.CONTRACTION


def test_missing_macro_data_still_returns_assessment_with_lower_confidence():
    """Sección 15 del spec: el sistema debe seguir funcionando aunque una
    fuente falle, nunca inventar dirección — se devuelve una clasificación
    por defecto conservadora con confianza reducida, no un crash."""
    market_data = _FakeMarketData({REFERENCE: _bull_close(), VIX: _flat_vix(15.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.liquidity_regime == LiquidityRegime.CONTRACTION
    assert assessment.confidence < 1.0


def test_insufficient_trend_history_defaults_sideways():
    short_close = pd.Series(np.linspace(100, 110, 50))
    market_data = _FakeMarketData({REFERENCE: short_close, VIX: _flat_vix(15.0)})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.trend_regime == TrendRegime.SIDEWAYS
    assert assessment.confidence < 1.0


def test_vix_unavailable_falls_back_to_reference_volatility_proxy():
    class _NoVixMarketData(_FakeMarketData):
        def get_ohlcv(self, ticker, interval="1d", lookback="1y"):
            if ticker == VIX:
                raise ValueError("VIX unavailable")
            return super().get_ohlcv(ticker, interval, lookback)

    market_data = _NoVixMarketData({REFERENCE: _bull_close()})
    engine = MarketRegimeEngine(market_data, _FakeMacroData(_EMPTY_MACRO), reference_index=REFERENCE, vix_ticker=VIX)
    assessment = engine.assess()
    assert assessment.risk_regime in (RiskRegime.RISK_ON, RiskRegime.RISK_OFF)
    assert "proxy" in assessment.justification[1]
