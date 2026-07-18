import pandas as pd

from alpha_os.adapters.base import (
    FundamentalDataAdapter,
    MacroDataAdapter,
    MarketDataAdapter,
    NewsAdapter,
    OnChainAdapter,
)
from alpha_os.adapters.onchain.binance_derivatives_adapter import BinanceDerivativesAdapter
from alpha_os.adapters.onchain.coingecko_stablecoin_adapter import CoinGeckoStablecoinAdapter
from alpha_os.analysis import onchain, sentiment, technical
from alpha_os.config import settings
from alpha_os.core.enums import (
    AssetClass,
    InstitutionalClassification,
    InvestorProfile,
    RiskLevel,
    SourceTier,
    TimeHorizon,
)
from alpha_os.core.models import (
    ConvictionFactor,
    DerivativesSnapshot,
    FundamentalSnapshot,
    InstitutionalAssessment,
    MacroSnapshot,
    MarketRegimeAssessment,
    SentimentSnapshot,
    StablecoinSnapshot,
    Signal,
)
from alpha_os.engine.conviction import DEFAULT_FACTOR_WEIGHTS, ConvictionEngine
from alpha_os.engine.institutional_engine import InstitutionalEngine
from alpha_os.engine.market_regime_engine import MarketRegimeEngine

# Mapeo mínimo ticker(yfinance) -> símbolo de Binance perpetuo. Cripto fuera
# de esta lista simplemente no obtiene factores de derivados (no se inventa).
TICKER_TO_BINANCE_SYMBOL = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT",
    "BNB-USD": "BNBUSDT",
}

# Umbrales de funding rate/long-short ratio "señal de alerta de
# apalancamiento excesivo" — órdenes de magnitud típicas de la industria
# (Binance funding se liquida cada 8h), no un descubrimiento propio.
FUNDING_RATE_EXTREME = 0.0005
LONG_SHORT_RATIO_EXTREME_HIGH = 2.0
LONG_SHORT_RATIO_EXTREME_LOW = 0.5

STABLECOIN_SUPPLY_CHANGE_SIGNIFICANT = 0.02  # 2% en 7 días

# Umbrales conservadores: solo se activan con métricas de unidades
# inequívocas (fracciones de yfinance), nunca con debt_to_equity cuya
# convención de escala varía entre tickers.
REVENUE_GROWTH_STRONG = 0.05
REVENUE_GROWTH_DECLINE = -0.02
NET_MARGIN_HEALTHY = 0.10

# El score de sentimiento por léxico es ruidoso con pocas menciones; exigir
# un mínimo de titulares y una magnitud clara antes de tratarlo como factor.
SENTIMENT_MIN_MENTIONS = 2
SENTIMENT_SCORE_THRESHOLD = 0.15

# Riesgo macro: no depende de la dirección de la hipótesis (afecta por igual
# a tesis largas y cortas), así que se pondera simétrico. Zona ambigua
# (3.5%-5%) no genera factor para no sobre-interpretar.
CPI_YOY_CONTROLLED = 0.035
CPI_YOY_ELEVATED = 0.05

# Flujo institucional: score -100..100 se reescala al mismo rango que el
# resto de factores (peso "institutional_buying" ya reservado en la
# plantilla). Distribución/acumulación fuerte que contradiga la hipótesis
# bloquea la señal por completo (spec institucional, sección 6) — no es un
# factor más, es un veto.
INSTITUTIONAL_MAX_WEIGHT = DEFAULT_FACTOR_WEIGHTS["institutional_buying"]
INSTITUTIONAL_VETO_SCORE = -70.0

MIN_BARS_FOR_LONG_TREND = 210
MIN_BARS_FOR_SHORT_TREND = 35
MIN_BARS_REQUIRED = 30

_RISK_THRESHOLDS = [
    (0.20, RiskLevel.LOW),
    (0.40, RiskLevel.MEDIUM),
    (0.70, RiskLevel.HIGH),
]

_INVESTOR_PROFILE_BY_RISK = {
    RiskLevel.LOW: InvestorProfile.CONSERVATIVE,
    RiskLevel.MEDIUM: InvestorProfile.MODERATE,
    RiskLevel.HIGH: InvestorProfile.AGGRESSIVE,
    RiskLevel.EXTREME: InvestorProfile.SPECULATIVE,
}


def _determine_direction(close: pd.Series) -> str | None:
    """Hipótesis direccional de trabajo a partir de medias móviles. Si no
    hay suficiente historia para una lectura confiable, no hay dirección."""
    if len(close) >= MIN_BARS_FOR_LONG_TREND:
        short_ma = technical.sma(close, 50).iloc[-1]
        long_ma = technical.sma(close, 200).iloc[-1]
    elif len(close) >= MIN_BARS_FOR_SHORT_TREND:
        short_ma = technical.sma(close, 10).iloc[-1]
        long_ma = technical.sma(close, 30).iloc[-1]
    else:
        return None
    if pd.isna(short_ma) or pd.isna(long_ma) or short_ma == long_ma:
        return None
    return "long" if short_ma > long_ma else "short"


def _risk_level_from_volatility(annualized_vol: float | None) -> RiskLevel:
    if annualized_vol is None or pd.isna(annualized_vol):
        return RiskLevel.MEDIUM
    for threshold, level in _RISK_THRESHOLDS:
        if annualized_vol < threshold:
            return level
    return RiskLevel.EXTREME


def _factor(label: str, rationale: str) -> ConvictionFactor:
    return ConvictionFactor(label=label, weight_pct=DEFAULT_FACTOR_WEIGHTS[label], rationale=rationale)


def _technical_factors(ohlcv: pd.DataFrame, direction: str) -> list[ConvictionFactor]:
    close, volume = ohlcv["close"], ohlcv["volume"]
    factors = [
        _factor(
            "trend_direction",
            f"Media móvil corta {'por encima' if direction == 'long' else 'por debajo'} "
            "de la media larga — hipótesis de trabajo elegida a partir de esta tendencia.",
        )
    ]

    vol_z = technical.volume_zscore(volume).iloc[-1]
    if not pd.isna(vol_z) and vol_z > 1:
        factors.append(
            _factor("volume_increase", f"Volumen {vol_z:.1f} desviaciones sobre su media de 20 periodos.")
        )

    if len(close) > 5:
        weekly_return = close.iloc[-1] / close.iloc[-6] - 1
        matches_direction = (weekly_return > 0.01 and direction == "long") or (
            weekly_return < -0.01 and direction == "short"
        )
        if matches_direction:
            factors.append(
                _factor(
                    "weekly_momentum",
                    f"Retorno de los últimos 5 periodos: {weekly_return * 100:.1f}%, a favor de la hipótesis.",
                )
            )

    macd_df = technical.macd(close)
    if len(macd_df) > 1 and not macd_df.iloc[-1].isna().any():
        macd_now, signal_now = macd_df["macd"].iloc[-1], macd_df["signal"].iloc[-1]
        hist_now, hist_prev = macd_df["histogram"].iloc[-1], macd_df["histogram"].iloc[-2]
        bullish_cross = macd_now > signal_now and hist_now > hist_prev
        bearish_cross = macd_now < signal_now and hist_now < hist_prev
        if (direction == "long" and bullish_cross) or (direction == "short" and bearish_cross):
            factors.append(
                ConvictionFactor(
                    label="macd_confirmation",
                    weight_pct=DEFAULT_FACTOR_WEIGHTS["macd_confirmation"],
                    rationale="MACD y su histograma confirman la dirección de la hipótesis.",
                )
            )

    rsi_now = technical.rsi(close).iloc[-1]
    if not pd.isna(rsi_now):
        if direction == "long" and rsi_now > 70:
            factors.append(
                _factor("rsi_overextended", f"RSI en {rsi_now:.0f}, zona de sobrecompra — riesgo de reversión.")
            )
        elif direction == "short" and rsi_now < 30:
            factors.append(
                _factor("rsi_overextended", f"RSI en {rsi_now:.0f}, zona de sobreventa — riesgo de rebote.")
            )

    bands = technical.bollinger_bands(close)
    if not bands.iloc[-1].isna().any():
        last_close, upper, lower = close.iloc[-1], bands["upper"].iloc[-1], bands["lower"].iloc[-1]
        if direction == "long" and last_close >= upper * 0.99:
            factors.append(
                _factor("nearby_resistance", "Precio cerca o por encima de la banda superior de Bollinger.")
            )
        elif direction == "short" and last_close <= lower * 1.01:
            factors.append(
                _factor("nearby_resistance", "Precio cerca o por debajo de la banda inferior de Bollinger.")
            )

    return factors


def _fundamental_factors(snapshot: FundamentalSnapshot, direction: str) -> list[ConvictionFactor]:
    factors: list[ConvictionFactor] = []

    growth = snapshot.revenue_growth_yoy
    if growth is not None:
        if direction == "long" and growth > REVENUE_GROWTH_STRONG:
            factors.append(
                _factor(
                    "earnings_expectation",
                    f"Crecimiento de ingresos interanual de {growth * 100:.1f}%, respalda la hipótesis alcista.",
                )
            )
        elif direction == "short" and growth < REVENUE_GROWTH_DECLINE:
            factors.append(
                _factor(
                    "earnings_expectation",
                    f"Ingresos cayendo {abs(growth) * 100:.1f}% interanual, respalda la hipótesis bajista.",
                )
            )

    margin = snapshot.net_margin
    if margin is not None:
        if direction == "long" and margin > NET_MARGIN_HEALTHY:
            factors.append(
                _factor(
                    "fundamental_health",
                    f"Margen neto de {margin * 100:.1f}%, negocio rentable respalda la hipótesis alcista.",
                )
            )
        elif direction == "short" and margin < 0:
            factors.append(
                _factor(
                    "fundamental_health",
                    f"Margen neto negativo ({margin * 100:.1f}%), respalda la hipótesis bajista.",
                )
            )

    return factors


def _sentiment_factors(snapshot: SentimentSnapshot, direction: str) -> list[ConvictionFactor]:
    if snapshot.score is None or (snapshot.volume_mentions or 0) < SENTIMENT_MIN_MENTIONS:
        return []

    directional_score = snapshot.score if direction == "long" else -snapshot.score
    if abs(directional_score) <= SENTIMENT_SCORE_THRESHOLD:
        return []

    headlines = "; ".join(e.claim for e in snapshot.supporting_evidence[:3])
    aligns = directional_score > 0
    return [
        ConvictionFactor(
            label="news_sentiment",
            weight_pct=DEFAULT_FACTOR_WEIGHTS["news_sentiment"] if aligns else -DEFAULT_FACTOR_WEIGHTS["news_sentiment"],
            rationale=(
                f"Sentimiento de {len(snapshot.supporting_evidence)} titulares (score {snapshot.score:.2f}) "
                f"{'a favor de' if aligns else 'en contra de'} la hipótesis: {headlines}"
            ),
            evidence=snapshot.supporting_evidence[:3],
        )
    ]


def _macro_factors(snapshot: MacroSnapshot) -> list[ConvictionFactor]:
    if snapshot.cpi_yoy is None:
        return []

    if snapshot.cpi_yoy <= CPI_YOY_CONTROLLED:
        return [
            ConvictionFactor(
                label="macro_risk_controlled",
                weight_pct=DEFAULT_FACTOR_WEIGHTS["macro_risk_controlled"],
                rationale=f"Inflación interanual (CPI) en {snapshot.cpi_yoy * 100:.1f}%, bajo control.",
            )
        ]
    if snapshot.cpi_yoy >= CPI_YOY_ELEVATED:
        return [
            ConvictionFactor(
                label="macro_risk_controlled",
                weight_pct=-DEFAULT_FACTOR_WEIGHTS["macro_risk_controlled"],
                rationale=f"Inflación interanual (CPI) en {snapshot.cpi_yoy * 100:.1f}%, elevada — riesgo macro no controlado.",
            )
        ]
    return []


def _derivatives_factors(snapshot: DerivativesSnapshot, direction: str) -> list[ConvictionFactor]:
    """Contrarian, no confirmatorio: apalancamiento excesivo en una
    dirección es riesgo de squeeze, no evidencia de que esa dirección vaya
    a seguir — mismo espíritu que rsi_overextended."""
    crowded_long = (snapshot.funding_rate is not None and snapshot.funding_rate > FUNDING_RATE_EXTREME) or (
        snapshot.long_short_ratio is not None and snapshot.long_short_ratio > LONG_SHORT_RATIO_EXTREME_HIGH
    )
    crowded_short = (snapshot.funding_rate is not None and snapshot.funding_rate < -FUNDING_RATE_EXTREME) or (
        snapshot.long_short_ratio is not None and snapshot.long_short_ratio < LONG_SHORT_RATIO_EXTREME_LOW
    )

    if direction == "long" and crowded_long:
        return [
            _factor(
                "derivatives_leverage_risk",
                f"Funding rate ({snapshot.funding_rate}) y/o long/short ratio ({snapshot.long_short_ratio}) "
                "muestran posicionamiento long recargado — riesgo de long squeeze.",
            )
        ]
    if direction == "short" and crowded_short:
        return [
            _factor(
                "derivatives_leverage_risk",
                f"Funding rate ({snapshot.funding_rate}) y/o long/short ratio ({snapshot.long_short_ratio}) "
                "muestran posicionamiento short recargado — riesgo de short squeeze.",
            )
        ]
    return []


def _stablecoin_factors(snapshot: StablecoinSnapshot, direction: str) -> list[ConvictionFactor]:
    """Spec: "no asumir causalidad automática" — se trata como indicio débil
    de liquidez disponible, nunca como confirmación de compra/venta."""
    change = snapshot.supply_change_7d_pct
    if change is None:
        return []

    if direction == "long" and change > STABLECOIN_SUPPLY_CHANGE_SIGNIFICANT:
        return [
            _factor(
                "stablecoin_liquidity",
                f"Supply de {snapshot.symbol} creció {change * 100:.1f}% en 7 días — más liquidez "
                "potencialmente disponible, no implica compra confirmada.",
            )
        ]
    if direction == "short" and change < -STABLECOIN_SUPPLY_CHANGE_SIGNIFICANT:
        return [
            _factor(
                "stablecoin_liquidity",
                f"Supply de {snapshot.symbol} cayó {abs(change) * 100:.1f}% en 7 días — posible salida "
                "de liquidez del ecosistema cripto, no implica venta confirmada.",
            )
        ]
    return []


def _apply_regime_adjustments(
    factors: list[ConvictionFactor], regime: MarketRegimeAssessment
) -> list[ConvictionFactor]:
    """Market Regime Intelligence: capa de contexto que reescala (no
    reemplaza) el peso de cada factor ya calculado, según el régimen
    detectado. No genera factores propios ni señales por sí sola."""
    if not regime.weight_adjustments:
        return factors
    adjusted = []
    for f in factors:
        multiplier = regime.weight_adjustments.get(f.label, 1.0)
        if multiplier == 1.0:
            adjusted.append(f)
            continue
        adjusted.append(
            ConvictionFactor(
                label=f.label,
                weight_pct=f.weight_pct * multiplier,
                rationale=f"{f.rationale} [ajustado x{multiplier:.2f} por régimen de mercado]",
                evidence=f.evidence,
            )
        )
    return adjusted


def _institutional_veto(assessment: InstitutionalAssessment, direction: str) -> bool:
    """Spec institucional, sección 6: bloquear señales fuertes cuando exista
    distribución (o acumulación, si la hipótesis es corta) institucional
    clara que contradiga la tesis — un veto, no un factor más."""
    directional_score = assessment.score if direction == "long" else -assessment.score
    return directional_score <= INSTITUTIONAL_VETO_SCORE


def _institutional_factor(
    assessment: InstitutionalAssessment, direction: str
) -> list[ConvictionFactor]:
    if assessment.classification in (
        InstitutionalClassification.NEUTRAL,
        InstitutionalClassification.INSUFFICIENT_DATA,
    ):
        return []

    directional_score = assessment.score if direction == "long" else -assessment.score
    weight = (directional_score / 100.0) * INSTITUTIONAL_MAX_WEIGHT
    return [
        ConvictionFactor(
            label="institutional_flow",
            weight_pct=weight,
            rationale=(
                f"{assessment.rationale} (confianza {assessment.confidence:.0%}, "
                f"frescura de datos: {assessment.data_freshness})."
            ),
        )
    ]


def _unavailable_dimensions_note(
    asset_class: AssetClass,
    news_evidence: list,
    fundamentals_available: bool,
    sentiment_available: bool,
    macro_available: bool,
    institutional_available: bool,
    derivatives_available: bool = False,
    stablecoin_available: bool = False,
) -> str:
    unavailable = []
    if not fundamentals_available:
        unavailable.append("fundamentales")
    if not sentiment_available:
        unavailable.append("sentimiento")
    if not macro_available:
        unavailable.append("macro")
    if not institutional_available:
        unavailable.append("institucional")

    included_parts = ["técnicos"]
    if fundamentals_available:
        included_parts.append("fundamentales")
    if sentiment_available:
        included_parts.append("sentimiento")
    if macro_available:
        included_parts.append("macro")
    if institutional_available:
        included_parts.append("institucional")

    if asset_class == AssetClass.CRYPTO:
        if not derivatives_available:
            unavailable.append("derivados")
        else:
            included_parts.append("derivados")
        if not stablecoin_available:
            unavailable.append("stablecoins")
        else:
            included_parts.append("stablecoins")
        unavailable.append(
            "on-chain (wallets/exchange flows/holder behavior/narrativa/calendario — requieren "
            "proveedor de pago o infraestructura de series de tiempo propia)"
        )

    included = " y ".join([", ".join(included_parts[:-1]), included_parts[-1]]) if len(
        included_parts
    ) > 1 else included_parts[0]

    if unavailable:
        note = (
            f"Dimensiones sin fuente de datos conectada todavía ({', '.join(unavailable)}); "
            f"score calculado solo con factores {included}."
        )
    else:
        note = f"Todas las dimensiones conectadas contribuyeron: {included}."
    if news_evidence:
        low_tier = [e for e in news_evidence if e.source_tier == SourceTier.C]
        if low_tier:
            note += " Se descartaron menciones de nivel C sin corroboración de niveles superiores."
    return note


class SignalEngine:
    """Orquesta adapters + analysis + ConvictionEngine para producir una
    Signal por activo. Técnico (medias, volumen, momentum, MACD, RSI,
    Bollinger), fundamentales básicos (yfinance), sentimiento de noticias
    (NewsAPI + léxico simple), macro básico (FRED: CPI, fed funds), flujo
    institucional básico (Form 4, 13F, opciones, volumen relativo), régimen
    de mercado (Market Regime Intelligence: reescala pesos, no genera
    factores propios) y — solo para cripto — derivados (Binance: funding
    rate, long/short ratio) y liquidez de stablecoins (CoinGecko) están
    implementados. On-chain "profundo" (wallets etiquetadas, exchange flows
    con serie histórica, MVRV/SOPR/NUPL, narrativa social, calendario de
    eventos) sigue pendiente — requiere proveedor de pago o infraestructura
    de series de tiempo propia; el rationale lo declara en vez de fabricarlo."""

    def __init__(
        self,
        market_data: MarketDataAdapter,
        news: NewsAdapter,
        onchain_adapter: OnChainAdapter,
        fundamental_data: FundamentalDataAdapter,
        macro_data: MacroDataAdapter,
        institutional_engine: InstitutionalEngine,
        market_regime_engine: MarketRegimeEngine,
        derivatives_data: BinanceDerivativesAdapter | None = None,
        stablecoin_data: CoinGeckoStablecoinAdapter | None = None,
    ):
        self.market_data = market_data
        self.news = news
        self.onchain_adapter = onchain_adapter
        self.fundamental_data = fundamental_data
        self.macro_data = macro_data
        self.institutional_engine = institutional_engine
        self.market_regime_engine = market_regime_engine
        self.derivatives_data = derivatives_data or BinanceDerivativesAdapter()
        self.stablecoin_data = stablecoin_data or CoinGeckoStablecoinAdapter()

    def gather_inputs(self, ticker: str, asset_class: AssetClass) -> dict:
        ohlcv = self.market_data.get_ohlcv(ticker)
        news_evidence = self.news.get_recent_news(ticker)
        inputs = {
            "ohlcv": ohlcv,
            "news": news_evidence,
            "fundamentals": self.fundamental_data.get_snapshot(ticker),
            "macro": self.macro_data.get_snapshot(),
            "sentiment": sentiment.build_sentiment_snapshot(ticker, news_evidence),
            "regime": self.market_regime_engine.assess(),
        }
        # Form 4 / opciones / volumen relativo solo aplican a emisores en SEC
        # EDGAR con cadena de opciones — no tiene sentido para cripto/FX.
        if asset_class in (AssetClass.EQUITY, AssetClass.ETF):
            inputs["institutional"] = self.institutional_engine.assess(ticker)
        if asset_class == AssetClass.CRYPTO:
            inputs["onchain"] = onchain.get_onchain_snapshot(ticker)
            binance_symbol = TICKER_TO_BINANCE_SYMBOL.get(ticker.upper())
            if binance_symbol:
                inputs["derivatives"] = self.derivatives_data.get_snapshot(binance_symbol)
            inputs["stablecoin"] = self.stablecoin_data.get_snapshot("USDT")
        return inputs

    def generate_signal(
        self,
        ticker: str,
        asset_class: AssetClass = AssetClass.EQUITY,
        time_horizon: TimeHorizon = TimeHorizon.SWING,
    ) -> Signal | None:
        inputs = self.gather_inputs(ticker, asset_class)
        ohlcv: pd.DataFrame = inputs["ohlcv"]
        if len(ohlcv) < MIN_BARS_REQUIRED:
            return None

        close = ohlcv["close"]
        direction = _determine_direction(close)
        if direction is None:
            return None

        fundamentals: FundamentalSnapshot = inputs["fundamentals"]
        sentiment_snapshot: SentimentSnapshot = inputs["sentiment"]
        macro_snapshot: MacroSnapshot = inputs["macro"]
        regime: MarketRegimeAssessment = inputs["regime"]
        institutional_assessment: InstitutionalAssessment | None = inputs.get("institutional")
        derivatives_snapshot: DerivativesSnapshot | None = inputs.get("derivatives")
        stablecoin_snapshot: StablecoinSnapshot | None = inputs.get("stablecoin")

        if institutional_assessment is not None and _institutional_veto(
            institutional_assessment, direction
        ):
            return None  # distribución/acumulación institucional fuerte contradice la hipótesis

        factors = (
            _technical_factors(ohlcv, direction)
            + _fundamental_factors(fundamentals, direction)
            + _sentiment_factors(sentiment_snapshot, direction)
            + _macro_factors(macro_snapshot)
        )
        if institutional_assessment is not None:
            factors += _institutional_factor(institutional_assessment, direction)
        if derivatives_snapshot is not None:
            factors += _derivatives_factors(derivatives_snapshot, direction)
        if stablecoin_snapshot is not None:
            factors += _stablecoin_factors(stablecoin_snapshot, direction)

        factors = _apply_regime_adjustments(factors, regime)

        score = ConvictionEngine.score(factors)
        contradictions = ConvictionEngine.has_contradictions(factors)
        if contradictions or score < settings.signal_confidence_threshold:
            return None

        annualized_vol = technical.realized_volatility(close).iloc[-1]
        risk_level = _risk_level_from_volatility(annualized_vol)
        atr_value = technical.atr(ohlcv).iloc[-1]
        last_price = float(close.iloc[-1])

        if pd.isna(atr_value) or atr_value <= 0:
            return None

        if direction == "long":
            stop_loss = last_price - 1.5 * atr_value
            risk = last_price - stop_loss
            targets = [last_price + risk * 1.5, last_price + risk * 3]
        else:
            stop_loss = last_price + 1.5 * atr_value
            risk = stop_loss - last_price
            targets = [last_price - risk * 1.5, last_price - risk * 3]

        if risk <= 0:
            return None

        institutional_available = (
            institutional_assessment is not None
            and institutional_assessment.classification != InstitutionalClassification.INSUFFICIENT_DATA
        )
        rationale = (
            f"Hipótesis {direction} con convicción {score:.0f}/100 a partir de "
            f"{len(factors)} factores convergentes. "
            + _unavailable_dimensions_note(
                asset_class,
                inputs["news"],
                fundamentals.has_data(),
                sentiment_snapshot.score is not None,
                macro_snapshot.has_data(),
                institutional_available,
                derivatives_snapshot is not None and derivatives_snapshot.has_data(),
                stablecoin_snapshot is not None and stablecoin_snapshot.has_data(),
            )
            + (
                f" Régimen de mercado: {regime.trend_regime.value}/{regime.risk_regime.value}/"
                f"{regime.liquidity_regime.value}{' (alta volatilidad)' if regime.high_volatility_event else ''} "
                f"(confianza {regime.confidence:.0%}) — pesos de factores ya reescalados según este contexto."
            )
        )

        return Signal(
            ticker=ticker,
            asset_class=asset_class,
            direction=direction,
            price=last_price,
            conviction_score=score,
            factors=factors,
            confidence_level=score,
            time_horizon=time_horizon,
            risk_level=risk_level,
            recommended_investor_profile=_INVESTOR_PROFILE_BY_RISK[risk_level],
            suggested_entry=last_price,
            stop_loss=round(stop_loss, 4),
            take_profit_targets=[round(t, 4) for t in targets],
            risk_reward_ratio=round(abs(targets[0] - last_price) / risk, 2),
            rationale=rationale,
            has_contradictions=contradictions,
        )
