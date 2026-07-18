import pandas as pd

from alpha_os.adapters.base import MacroDataAdapter, MarketDataAdapter
from alpha_os.analysis import technical
from alpha_os.core.enums import LiquidityRegime, RiskRegime, TrendRegime
from alpha_os.core.models import MarketRegimeAssessment

# Umbrales de clasificación de tendencia. Volatilidad anualizada, no precio.
SIDEWAYS_SMA_GAP = 0.015  # SMA50 vs SMA200 a menos de 1.5% de distancia
SIDEWAYS_VOL_CEILING = 0.12
BULL_DRAWDOWN_CEILING = -0.05  # más allá de -5% desde el máximo de 52 semanas ya es "agotamiento"
CAPITULATION_DRAWDOWN = -0.30
CAPITULATION_VOL_FLOOR = 0.35

# VIX: umbrales estándar de la industria (no un descubrimiento propio).
VIX_RISK_OFF = 22.0
VIX_HIGH_VOLATILITY = 30.0
# Proxy cuando VIX no está disponible: volatilidad anualizada del propio índice.
PROXY_RISK_OFF_VOL = 0.20
PROXY_HIGH_VOL = 0.30

# Tasa "neutral" de referencia para desempatar cuando la tendencia de tasas
# es "stable" — no hay una fuente única y objetiva para esto, es una
# aproximación histórica ampliamente citada (no ~2%, no ~3%), documentada
# como tal.
NEUTRAL_FED_FUNDS_RATE = 2.5

_TREND_ADJUSTMENTS: dict[TrendRegime, dict[str, float]] = {
    TrendRegime.BULL_EXPANSION: {
        "trend_direction": 1.3, "weekly_momentum": 1.3, "macd_confirmation": 1.2,
    },
    TrendRegime.BULL_EXHAUSTION: {
        "trend_direction": 0.85, "rsi_overextended": 1.3, "nearby_resistance": 1.3,
    },
    TrendRegime.SIDEWAYS: {
        "trend_direction": 0.6, "weekly_momentum": 0.6, "macd_confirmation": 0.7,
    },
    TrendRegime.BEAR_DISTRIBUTION: {
        "trend_direction": 1.1, "macro_risk_controlled": 1.2,
    },
    TrendRegime.BEAR_CAPITULATION: {
        "institutional_flow": 1.3, "macro_risk_controlled": 1.4, "trend_direction": 0.8,
    },
}

_RISK_ADJUSTMENTS: dict[RiskRegime, dict[str, float]] = {
    RiskRegime.RISK_ON: {"news_sentiment": 1.1},
    RiskRegime.RISK_OFF: {"macro_risk_controlled": 1.3, "news_sentiment": 0.7},
}

_LIQUIDITY_ADJUSTMENTS: dict[LiquidityRegime, dict[str, float]] = {
    LiquidityRegime.EXPANSION: {"trend_direction": 1.1, "earnings_expectation": 1.1},
    LiquidityRegime.CONTRACTION: {"macro_risk_controlled": 1.2, "fundamental_health": 1.1},
}

_HIGH_VOLATILITY_ADJUSTMENT: dict[str, float] = {
    "institutional_flow": 1.3, "macro_risk_controlled": 1.3,
    "news_sentiment": 0.6, "weekly_momentum": 0.7,
}


def _merge_adjustments(*adjustment_dicts: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for adjustments in adjustment_dicts:
        for label, multiplier in adjustments.items():
            merged[label] = merged.get(label, 1.0) * multiplier
    return merged


class MarketRegimeEngine:
    """Capa de contexto (spec: Market Regime Intelligence). No emite
    señales de compra/venta — clasifica el régimen actual a partir de un
    índice de referencia + VIX + tendencia de tasas (ya calculada por
    FREDMacroAdapter), y traduce esa clasificación en multiplicadores de
    peso para los factores del motor de señales."""

    def __init__(
        self,
        market_data: MarketDataAdapter,
        macro_data: MacroDataAdapter,
        reference_index: str = "^GSPC",
        vix_ticker: str = "^VIX",
    ):
        self.market_data = market_data
        self.macro_data = macro_data
        self.reference_index = reference_index
        self.vix_ticker = vix_ticker

    def assess(self) -> MarketRegimeAssessment:
        justification: list[str] = []
        data_quality_hits = 0

        try:
            close = self.market_data.get_ohlcv(self.reference_index, lookback="1y")["close"]
        except Exception:
            close = pd.Series(dtype=float)

        trend_regime, trend_note, trend_had_data = self._classify_trend(close)
        justification.append(trend_note)
        data_quality_hits += int(trend_had_data)

        vix_level = self._get_vix_level()
        risk_regime, risk_note, high_volatility, risk_had_data = self._classify_risk(vix_level, close)
        justification.append(risk_note)
        data_quality_hits += int(risk_had_data)

        macro = self.macro_data.get_snapshot()
        liquidity_regime, liquidity_note, liquidity_had_data = self._classify_liquidity(macro)
        justification.append(liquidity_note)
        data_quality_hits += int(liquidity_had_data)

        weight_adjustments = _merge_adjustments(
            _TREND_ADJUSTMENTS[trend_regime],
            _RISK_ADJUSTMENTS[risk_regime],
            _LIQUIDITY_ADJUSTMENTS[liquidity_regime],
            _HIGH_VOLATILITY_ADJUSTMENT if high_volatility else {},
        )

        confidence = 0.4 + 0.2 * data_quality_hits  # 0.4 base, hasta 1.0 con las 3 fuentes reales

        return MarketRegimeAssessment(
            trend_regime=trend_regime,
            risk_regime=risk_regime,
            liquidity_regime=liquidity_regime,
            high_volatility_event=high_volatility,
            confidence=round(min(confidence, 1.0), 2),
            justification=justification,
            weight_adjustments=weight_adjustments,
            reference_index=self.reference_index,
        )

    def _classify_trend(self, close: pd.Series) -> tuple[TrendRegime, str, bool]:
        if len(close) < 200:
            return (
                TrendRegime.SIDEWAYS,
                "Historial insuficiente (<200 periodos) para clasificar tendencia; sideways por defecto.",
                False,
            )

        sma50 = technical.sma(close, 50).iloc[-1]
        sma200 = technical.sma(close, 200).iloc[-1]
        last = close.iloc[-1]
        high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
        drawdown = (last - high_52w) / high_52w
        vol = technical.realized_volatility(close).iloc[-1]
        vol = None if pd.isna(vol) else float(vol)

        sma_gap = abs(sma50 - sma200) / sma200

        if sma_gap < SIDEWAYS_SMA_GAP and (vol is None or vol < SIDEWAYS_VOL_CEILING):
            return (
                TrendRegime.SIDEWAYS,
                f"SMA50/SMA200 a {sma_gap * 100:.1f}% de distancia y volatilidad baja — rango lateral.",
                True,
            )

        if sma50 > sma200:
            if drawdown > BULL_DRAWDOWN_CEILING:
                return (
                    TrendRegime.BULL_EXPANSION,
                    f"SMA50>SMA200, precio a {drawdown * 100:.1f}% de su máximo de 52 semanas.",
                    True,
                )
            return (
                TrendRegime.BULL_EXHAUSTION,
                f"SMA50>SMA200 pero retroceso de {abs(drawdown) * 100:.1f}% desde el máximo de 52 semanas.",
                True,
            )

        if drawdown < CAPITULATION_DRAWDOWN and vol is not None and vol > CAPITULATION_VOL_FLOOR:
            return (
                TrendRegime.BEAR_CAPITULATION,
                f"SMA50<SMA200, drawdown {abs(drawdown) * 100:.1f}%, volatilidad anualizada {vol * 100:.0f}%.",
                True,
            )
        return (
            TrendRegime.BEAR_DISTRIBUTION,
            f"SMA50<SMA200, drawdown {abs(drawdown) * 100:.1f}% desde el máximo de 52 semanas.",
            True,
        )

    def _get_vix_level(self) -> float | None:
        try:
            vix_close = self.market_data.get_ohlcv(self.vix_ticker, lookback="1mo")["close"]
            return float(vix_close.iloc[-1])
        except Exception:
            return None

    def _classify_risk(
        self, vix_level: float | None, reference_close: pd.Series
    ) -> tuple[RiskRegime, str, bool, bool]:
        if vix_level is not None:
            regime = RiskRegime.RISK_OFF if vix_level > VIX_RISK_OFF else RiskRegime.RISK_ON
            high_vol = vix_level > VIX_HIGH_VOLATILITY
            return regime, f"VIX en {vix_level:.1f}.", high_vol, True

        vol = technical.realized_volatility(reference_close).iloc[-1] if len(reference_close) > 20 else None
        if vol is None or pd.isna(vol):
            return (
                RiskRegime.RISK_ON,
                "VIX no disponible y volatilidad del índice de referencia no calculable — risk-on por defecto (dato insuficiente).",
                False,
                False,
            )
        vol = float(vol)
        regime = RiskRegime.RISK_OFF if vol > PROXY_RISK_OFF_VOL else RiskRegime.RISK_ON
        high_vol = vol > PROXY_HIGH_VOL
        return (
            regime,
            f"VIX no disponible; volatilidad anualizada del índice de referencia ({vol * 100:.0f}%) usada como proxy.",
            high_vol,
            False,
        )

    def _classify_liquidity(self, macro) -> tuple[LiquidityRegime, str, bool]:
        trend = macro.global_liquidity_trend
        if trend == "expanding":
            return LiquidityRegime.EXPANSION, "Fed funds rate en tendencia bajista — expansión de liquidez.", True
        if trend == "contracting":
            return LiquidityRegime.CONTRACTION, "Fed funds rate en tendencia alcista — contracción de liquidez.", True

        if trend == "stable" and macro.fed_funds_rate is not None:
            if macro.fed_funds_rate > NEUTRAL_FED_FUNDS_RATE:
                return (
                    LiquidityRegime.CONTRACTION,
                    f"Tendencia de tasas estable pero nivel ({macro.fed_funds_rate:.2f}%) por encima de la "
                    f"tasa neutral estimada (~{NEUTRAL_FED_FUNDS_RATE:.1f}%) — sesgo restrictivo.",
                    True,
                )
            return (
                LiquidityRegime.EXPANSION,
                f"Tendencia de tasas estable pero nivel ({macro.fed_funds_rate:.2f}%) por debajo de la "
                f"tasa neutral estimada (~{NEUTRAL_FED_FUNDS_RATE:.1f}%) — sesgo acomodaticio.",
                True,
            )

        return (
            LiquidityRegime.CONTRACTION,
            "Sin datos macro disponibles — contracción por defecto (conservador), confianza baja.",
            False,
        )
