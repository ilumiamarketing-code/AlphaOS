from datetime import datetime

from alpha_os.adapters.institutional.form4_adapter import Form4Adapter
from alpha_os.adapters.institutional.form13f_adapter import Form13FAdapter
from alpha_os.adapters.institutional.options_flow_adapter import OptionsFlowAdapter
from alpha_os.adapters.institutional.relative_volume_adapter import RelativeVolumeAdapter
from alpha_os.core.enums import InstitutionalClassification, InstitutionalDataStatus
from alpha_os.core.models import Form13FPosition, InstitutionalAssessment, InstitutionalSignal

# Penalización por antigüedad (spec sección 5). 13F-like (is_quarterly) nunca
# se trata como posicionamiento actual, sin importar qué tan reciente sea.
_FRESHNESS_BANDS = [
    (1, 1.0, "real_time"),
    (7, 0.85, "recent"),
    (30, 0.6, "aging"),
]
_STALE_MULTIPLIER = 0.25
_QUARTERLY_MULTIPLIER = 0.15

# Volumen relativo mínimo (en desviaciones estándar) para considerarlo
# "elevado" y digno de mención — nunca genera dirección por sí solo.
RELATIVE_VOLUME_THRESHOLD = 1.5
RELATIVE_VOLUME_CONFIRMATION_IMPACT = 8.0

OPTIONS_UNUSUAL_IMPACT = 18.0
OPTIONS_RELIABILITY = 0.45

# Las ventas de insiders son extremadamente comunes y en su mayoría rutinarias
# (planes 10b5-1, diversificación, obligaciones fiscales) — casi cualquier
# empresa grande tiene insiders vendiendo casi siempre. Tratarlas con el mismo
# peso que las compras generaría un sesgo bajista sistemático en todo el
# universo de tickers, no una señal real. Las compras discrecionales en
# mercado abierto son mucho más raras y por eso más informativas ("insiders
# venden por muchas razones, pero compran solo por una").
FORM4_PURCHASE_IMPACT = 20.0
FORM4_SALE_IMPACT = 8.0
FORM4_PURCHASE_RELIABILITY = 0.75
FORM4_SALE_RELIABILITY = 0.35

# Solo transacciones dentro de este horizonte cuentan como "posicionamiento
# actual" — una venta de hace 6 meses no es una señal de distribución vigente.
FORM4_LOOKBACK_DAYS = 90

# 13F es trimestral y de cobertura limitada (ver TRACKED_MANAGERS) — señal
# fuerte cuando existe (una posición nueva o una salida completa de un
# gestor conocido es información real), pero siempre con el descuento
# _QUARTERLY_MULTIPLIER aplicado por su naturaleza no-tiempo-real.
FORM13F_NEW_POSITION_IMPACT = 15.0
FORM13F_EXIT_IMPACT = 15.0
FORM13F_INCREASE_IMPACT = 10.0
FORM13F_DECREASE_IMPACT = 10.0
FORM13F_CHANGE_THRESHOLD = 0.10  # cambios menores al 10% se tratan como ruido/rebalanceo
FORM13F_NEW_EXIT_RELIABILITY = 0.7
FORM13F_CHANGE_RELIABILITY = 0.6

# Decaimiento por repetición: la primera transacción de un tipo (P o S) pesa
# completo, la segunda 60%, la tercera 36%, etc. Evita que muchas ventas
# rutinarias de distintos insiders se acumulen linealmente hasta un extremo
# artificial — refleja que son la misma clase de evidencia, no N evidencias
# independientes.
FORM4_REPEAT_DECAY = 0.6

# Bandas de clasificación, spec sección 4.
_STRONG_THRESHOLD = 70.0
_MODERATE_THRESHOLD = 25.0


def _freshness(age_days: float, is_quarterly: bool) -> tuple[float, str]:
    if is_quarterly:
        return _QUARTERLY_MULTIPLIER, "stale"
    for max_days, multiplier, label in _FRESHNESS_BANDS:
        if age_days <= max_days:
            return multiplier, label
    return _STALE_MULTIPLIER, "stale"


def _classify(score: float) -> InstitutionalClassification:
    if score >= _STRONG_THRESHOLD:
        return InstitutionalClassification.STRONG_ACCUMULATION
    if score >= _MODERATE_THRESHOLD:
        return InstitutionalClassification.MODERATE_ACCUMULATION
    if score <= -_STRONG_THRESHOLD:
        return InstitutionalClassification.STRONG_DISTRIBUTION
    if score <= -_MODERATE_THRESHOLD:
        return InstitutionalClassification.MODERATE_DISTRIBUTION
    return InstitutionalClassification.NEUTRAL


class InstitutionalEngine:
    """Agrega volumen relativo, flujo de opciones y transacciones Form 4 en
    un InstitutionalAssessment. Principios obligatorios del spec: el
    volumen nunca genera dirección por sí solo (solo confirma otras
    señales); cada observación queda fechada y clasificada por status
    (confirmed/proxy); la antigüedad penaliza el impacto en el score."""

    def __init__(
        self,
        relative_volume: RelativeVolumeAdapter,
        options_flow: OptionsFlowAdapter,
        form4: Form4Adapter,
        form13f: Form13FAdapter,
    ):
        self.relative_volume = relative_volume
        self.options_flow = options_flow
        self.form4 = form4
        self.form13f = form13f

    def assess(self, ticker: str) -> InstitutionalAssessment:
        now = datetime.utcnow()
        signals: list[InstitutionalSignal] = []

        repeat_count = {"P": 0, "S": 0}
        for tx in self.form4.get_recent_transactions(ticker, limit=10):
            age_days = (now.date() - tx.filed_date).days
            if age_days > FORM4_LOOKBACK_DAYS:
                continue  # fuera de ventana: no es posicionamiento vigente

            multiplier, _ = _freshness(age_days, is_quarterly=False)
            is_purchase = tx.transaction_code == "P"
            code = "P" if is_purchase else "S"
            decay = FORM4_REPEAT_DECAY ** repeat_count[code]
            repeat_count[code] += 1

            base_impact = FORM4_PURCHASE_IMPACT if is_purchase else -FORM4_SALE_IMPACT
            reliability = FORM4_PURCHASE_RELIABILITY if is_purchase else FORM4_SALE_RELIABILITY
            action = "compró" if is_purchase else "vendió"
            signals.append(
                InstitutionalSignal(
                    signal="form4_purchase" if is_purchase else "form4_sale",
                    impact=base_impact * multiplier * decay,
                    status=InstitutionalDataStatus.CONFIRMED,
                    source="SEC EDGAR Form 4",
                    data_date=datetime.combine(tx.transaction_date, datetime.min.time()),
                    published_date=datetime.combine(tx.filed_date, datetime.min.time()),
                    retrieved_at=now,
                    reliability=reliability,
                    description=(
                        f"{tx.insider_name} {action} {tx.shares:,.0f} acciones "
                        f"el {tx.transaction_date} (filing {tx.filed_date})."
                    ),
                )
            )

        signals.extend(self._form13f_signals(ticker, now))

        options_obs = self.options_flow.get_observation(ticker)
        if options_obs is not None:
            if options_obs.unusual_call_activity:
                signals.append(
                    InstitutionalSignal(
                        signal="unusual_call_activity",
                        impact=OPTIONS_UNUSUAL_IMPACT,
                        status=InstitutionalDataStatus.PROXY,
                        source="yfinance options chain",
                        data_date=now,
                        published_date=now,
                        retrieved_at=now,
                        reliability=OPTIONS_RELIABILITY,
                        description=(
                            f"Volumen de calls ({options_obs.call_volume:,}) supera la mitad del "
                            f"open interest ({options_obs.call_open_interest:,}) en {options_obs.expiration}."
                        ),
                    )
                )
            if options_obs.unusual_put_activity:
                signals.append(
                    InstitutionalSignal(
                        signal="unusual_put_activity",
                        impact=-OPTIONS_UNUSUAL_IMPACT,
                        status=InstitutionalDataStatus.PROXY,
                        source="yfinance options chain",
                        data_date=now,
                        published_date=now,
                        retrieved_at=now,
                        reliability=OPTIONS_RELIABILITY,
                        description=(
                            f"Volumen de puts ({options_obs.put_volume:,}) supera la mitad del "
                            f"open interest ({options_obs.put_open_interest:,}) en {options_obs.expiration}."
                        ),
                    )
                )

        vol_obs = self.relative_volume.get_observation(ticker)
        if vol_obs is not None and abs(vol_obs.volume_zscore) > RELATIVE_VOLUME_THRESHOLD:
            directional_so_far = sum(s.impact for s in signals)
            if signals and directional_so_far != 0:
                confirm_impact = (
                    RELATIVE_VOLUME_CONFIRMATION_IMPACT
                    if directional_so_far > 0
                    else -RELATIVE_VOLUME_CONFIRMATION_IMPACT
                )
                signals.append(
                    InstitutionalSignal(
                        signal="relative_volume_confirmation",
                        impact=confirm_impact,
                        status=InstitutionalDataStatus.PROXY,
                        source="OHLCV (yfinance)",
                        data_date=now,
                        published_date=now,
                        retrieved_at=now,
                        reliability=0.4,
                        description=(
                            f"Volumen {vol_obs.volume_zscore:.1f} desviaciones sobre su media de 20 "
                            "periodos — refuerza, no origina, la dirección de otras señales."
                        ),
                    )
                )
            else:
                signals.append(
                    InstitutionalSignal(
                        signal="relative_volume_increase",
                        impact=0.0,
                        status=InstitutionalDataStatus.PROXY,
                        source="OHLCV (yfinance)",
                        data_date=now,
                        published_date=now,
                        retrieved_at=now,
                        reliability=0.4,
                        description=(
                            f"Volumen {vol_obs.volume_zscore:.1f} desviaciones sobre su media, pero sin "
                            "otra señal institucional que le dé dirección — no se infiere compra ni "
                            "venta únicamente por volumen."
                        ),
                    )
                )

        return self._build_assessment(ticker, signals)

    def _form13f_signals(self, ticker: str, now: datetime) -> list[InstitutionalSignal]:
        positions = self.form13f.get_positions(ticker, lookback_quarters=2)
        by_manager: dict[str, list[Form13FPosition]] = {}
        for p in positions:
            by_manager.setdefault(p.manager_name, []).append(p)

        signals: list[InstitutionalSignal] = []
        for manager_name, mgr_positions in by_manager.items():
            # Se requieren AMBOS trimestres consultados para comparar — con
            # solo uno no hay forma de distinguir "nueva posición" de
            # "simplemente no consultamos el trimestre anterior" (sección 1:
            # nunca inventar dirección para completar el score).
            if len(mgr_positions) < 2:
                continue
            mgr_positions.sort(key=lambda p: p.report_period_end)
            previous, latest = mgr_positions[-2], mgr_positions[-1]
            age_days = (now.date() - latest.filed_date).days
            multiplier, _ = _freshness(age_days, is_quarterly=True)
            period_desc = f"entre {previous.report_period_end} y {latest.report_period_end}"

            if previous.shares == 0 and latest.shares > 0:
                signals.append(
                    InstitutionalSignal(
                        signal="form13f_new_position",
                        impact=FORM13F_NEW_POSITION_IMPACT * multiplier,
                        status=InstitutionalDataStatus.CONFIRMED,
                        source="SEC EDGAR Form 13F-HR",
                        data_date=datetime.combine(latest.report_period_end, datetime.min.time()),
                        published_date=datetime.combine(latest.filed_date, datetime.min.time()),
                        retrieved_at=now,
                        reliability=FORM13F_NEW_EXIT_RELIABILITY,
                        description=(
                            f"{manager_name} abrió posición nueva: {latest.shares:,.0f} acciones "
                            f"al {latest.report_period_end} (13F, filed {latest.filed_date})."
                        ),
                        is_quarterly=True,
                    )
                )
            elif previous.shares > 0 and latest.shares == 0:
                signals.append(
                    InstitutionalSignal(
                        signal="form13f_exit",
                        impact=-FORM13F_EXIT_IMPACT * multiplier,
                        status=InstitutionalDataStatus.CONFIRMED,
                        source="SEC EDGAR Form 13F-HR",
                        data_date=datetime.combine(latest.report_period_end, datetime.min.time()),
                        published_date=datetime.combine(latest.filed_date, datetime.min.time()),
                        retrieved_at=now,
                        reliability=FORM13F_NEW_EXIT_RELIABILITY,
                        description=(
                            f"{manager_name} salió por completo de la posición {period_desc} "
                            f"(tenía {previous.shares:,.0f} acciones, 13F filed {latest.filed_date})."
                        ),
                        is_quarterly=True,
                    )
                )
            elif previous.shares > 0 and latest.shares > 0:
                pct_change = (latest.shares - previous.shares) / previous.shares
                if pct_change >= FORM13F_CHANGE_THRESHOLD:
                    signals.append(
                        InstitutionalSignal(
                            signal="form13f_position_increase",
                            impact=FORM13F_INCREASE_IMPACT * multiplier,
                            status=InstitutionalDataStatus.CONFIRMED,
                            source="SEC EDGAR Form 13F-HR",
                            data_date=datetime.combine(latest.report_period_end, datetime.min.time()),
                            published_date=datetime.combine(latest.filed_date, datetime.min.time()),
                            retrieved_at=now,
                            reliability=FORM13F_CHANGE_RELIABILITY,
                            description=(
                                f"{manager_name} aumentó su posición {pct_change * 100:.0f}% {period_desc} "
                                f"(13F, filed {latest.filed_date})."
                            ),
                            is_quarterly=True,
                        )
                    )
                elif pct_change <= -FORM13F_CHANGE_THRESHOLD:
                    signals.append(
                        InstitutionalSignal(
                            signal="form13f_position_decrease",
                            impact=-FORM13F_DECREASE_IMPACT * multiplier,
                            status=InstitutionalDataStatus.CONFIRMED,
                            source="SEC EDGAR Form 13F-HR",
                            data_date=datetime.combine(latest.report_period_end, datetime.min.time()),
                            published_date=datetime.combine(latest.filed_date, datetime.min.time()),
                            retrieved_at=now,
                            reliability=FORM13F_CHANGE_RELIABILITY,
                            description=(
                                f"{manager_name} redujo su posición {abs(pct_change) * 100:.0f}% {period_desc} "
                                f"(13F, filed {latest.filed_date})."
                            ),
                            is_quarterly=True,
                        )
                    )
                # cambio dentro del umbral: rebalanceo menor, no se reporta (ruido)
            # ambos en 0: sin posición en ningún trimestre, no informativo

        return signals

    def _build_assessment(
        self, ticker: str, signals: list[InstitutionalSignal]
    ) -> InstitutionalAssessment:
        if not signals:
            return InstitutionalAssessment(
                ticker=ticker,
                score=0.0,
                classification=InstitutionalClassification.INSUFFICIENT_DATA,
                confidence=0.0,
                signals=[],
                data_freshness="none",
                rationale=(
                    "No hay datos institucionales verificables suficientes. "
                    "El factor no modifica la señal general."
                ),
            )

        raw_score = sum(s.impact for s in signals)
        score = max(-100.0, min(100.0, raw_score))
        classification = _classify(score)

        weighted_signals = [s for s in signals if s.impact != 0]
        if weighted_signals:
            supporting = [s for s in weighted_signals if (s.impact > 0) == (score >= 0)]
            opposing = [s for s in weighted_signals if (s.impact > 0) != (score >= 0)]
            supporting_weight = sum(abs(s.impact) for s in supporting)
            opposing_weight = sum(abs(s.impact) for s in opposing)
            total_weight = supporting_weight + opposing_weight
            agreement = supporting_weight / total_weight if total_weight > 0 else 0.0
            avg_reliability = sum(s.reliability * abs(s.impact) for s in weighted_signals) / sum(
                abs(s.impact) for s in weighted_signals
            )
            confidence = max(0.0, min(1.0, avg_reliability * (0.5 + 0.5 * agreement)))
        else:
            supporting, opposing = [], []
            confidence = 0.0

        now = datetime.utcnow()
        freshness_labels = set()
        for s in signals:
            age_days = (now - s.published_date).days if s.published_date else 0
            _, label = _freshness(age_days, s.is_quarterly)
            freshness_labels.add(label)
        data_freshness = freshness_labels.pop() if len(freshness_labels) == 1 else "mixed"

        rationale = self._build_rationale(classification, supporting, opposing)

        return InstitutionalAssessment(
            ticker=ticker,
            score=score,
            classification=classification,
            confidence=confidence,
            signals=signals,
            data_freshness=data_freshness,
            rationale=rationale,
        )

    @staticmethod
    def _build_rationale(
        classification: InstitutionalClassification,
        supporting: list[InstitutionalSignal],
        opposing: list[InstitutionalSignal],
    ) -> str:
        if classification == InstitutionalClassification.NEUTRAL:
            return (
                "Existen señales institucionales pero se contrarrestan entre sí; "
                "no hay convicción clara de acumulación ni distribución."
            )
        direction = "acumulación" if classification in (
            InstitutionalClassification.STRONG_ACCUMULATION,
            InstitutionalClassification.MODERATE_ACCUMULATION,
        ) else "distribución"
        parts = ", ".join(s.signal for s in supporting) or "sin señales de soporte"
        text = f"Indicios de {direction} ({classification.value}) basados en: {parts}."
        if opposing:
            text += f" Contradicciones detectadas: {', '.join(s.signal for s in opposing)}."
        return text
