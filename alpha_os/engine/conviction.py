from alpha_os.core.models import ConvictionFactor

# Plantilla de partida (ver spec, "Motor de Convicción"). Los pesos reales se
# recalibran con el módulo de aprendizaje continuo (positions/journal.py) a
# partir de resultados auditados, no se fijan a mano de forma permanente.
DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "trend_direction": 18.0,
    "volume_increase": 12.0,
    "institutional_buying": 20.0,
    "news_sentiment": 15.0,
    "earnings_expectation": 8.0,
    "weekly_momentum": 10.0,
    "macd_confirmation": 10.0,
    "fundamental_health": 10.0,
    "macro_risk_controlled": 8.0,
    "rsi_overextended": -6.0,
    "nearby_resistance": -4.0,
    # Solo cripto — ver signal_engine.py _derivatives_factors/_stablecoin_factors.
    "derivatives_leverage_risk": -8.0,
    "stablecoin_liquidity": 6.0,
}

# Si los factores en contra pesan >= a esta fracción de los factores a favor,
# no hay convergencia real y no debe emitirse señal (spec sección 4).
CONTRADICTION_RATIO_THRESHOLD = 0.6


class ConvictionEngine:
    """Agrega ConvictionFactor (cada uno ya calculado por analysis/*) en un
    score 0-100. Cada factor ya viene evaluado respecto a una hipótesis
    direccional de trabajo (long/short) elegida por signal_engine.py — un
    weight_pct positivo confirma esa hipótesis, uno negativo la contradice."""

    @staticmethod
    def score(factors: list[ConvictionFactor]) -> float:
        total = sum(f.weight_pct for f in factors)
        return max(0.0, min(100.0, total))

    @staticmethod
    def has_contradictions(factors: list[ConvictionFactor]) -> bool:
        supporting = sum(f.weight_pct for f in factors if f.weight_pct > 0)
        opposing = sum(-f.weight_pct for f in factors if f.weight_pct < 0)
        if supporting <= 0:
            return True
        return opposing >= supporting * CONTRADICTION_RATIO_THRESHOLD
