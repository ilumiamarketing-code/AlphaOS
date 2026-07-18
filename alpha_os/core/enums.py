from enum import Enum


class SourceTier(str, Enum):
    """Nivel de confiabilidad de una fuente, spec sección 2."""

    S = "S"  # Reguladores, datos oficiales, Reuters, Bloomberg, Nasdaq
    A = "A"  # FT, WSJ, Barron's, CNBC
    B = "B"  # TradingView, Finviz, Stocktwits, subreddits especializados
    C = "C"  # X, Reddit, Telegram — nunca genera señal por sí sola


class EvidenceType(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"
    RUMOR = "rumor"


class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    COMMODITY = "commodity"
    ETF = "etf"
    BOND = "bond"


class TimeHorizon(str, Enum):
    SCALP = "scalp"  # minutos-horas
    INTRADAY = "intraday"
    SWING = "swing"  # dias-semanas
    POSITION = "position"  # semanas-meses
    LONG_TERM = "long_term"  # meses-años


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class InvestorProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    SPECULATIVE = "speculative"


class AlertLevel(str, Enum):
    """Módulo 10, sección 4 — alertas post-compra."""

    HOLD = "hold"  # 🟢 Mantener posición
    ADD = "add"  # 🟢 Agregar posición
    WATCH = "watch"  # 🟡 Vigilar
    REDUCE = "reduce"  # 🟠 Reducir exposición
    EXIT = "exit"  # 🔴 Salir inmediatamente


class PositionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class OperationSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class InstitutionalDataStatus(str, Enum):
    """Módulo institucional, sección 1 — nunca tratar un proxy como dato
    confirmado ni un rumor como inferencia."""

    CONFIRMED = "confirmed"
    PROXY = "proxy"
    INFERENCE = "inference"
    RUMOR = "rumor"


class InstitutionalClassification(str, Enum):
    STRONG_ACCUMULATION = "strong_accumulation"
    MODERATE_ACCUMULATION = "moderate_accumulation"
    NEUTRAL = "neutral"
    MODERATE_DISTRIBUTION = "moderate_distribution"
    STRONG_DISTRIBUTION = "strong_distribution"
    INSUFFICIENT_DATA = "insufficient_data"


class TrendRegime(str, Enum):
    """Dónde está el ciclo de un índice de referencia (spec: Market Regime
    Intelligence). Eje independiente de RiskRegime/LiquidityRegime."""

    BULL_EXPANSION = "bull_market_expansion"
    BULL_EXHAUSTION = "bull_market_exhaustion"
    SIDEWAYS = "sideways_range"
    BEAR_DISTRIBUTION = "bear_market_distribution"
    BEAR_CAPITULATION = "bear_market_capitulation"


class RiskRegime(str, Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"


class LiquidityRegime(str, Enum):
    EXPANSION = "liquidity_expansion"
    CONTRACTION = "liquidity_contraction"
