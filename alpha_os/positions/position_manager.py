from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from alpha_os.core.enums import OperationSide, PositionStatus
from alpha_os.core.models import (
    OperationEntry,
    Position,
    PositionAlert,
    RiskParameters,
    ThesisReassessment,
)
from alpha_os.positions.storage import SQLiteJSONStore

if TYPE_CHECKING:
    from alpha_os.engine.signal_engine import SignalEngine


class PositionNotFoundError(KeyError):
    pass


class PositionManager:
    """Ciclo de vida post-compra de una posición (Módulo 10, secciones 1-2, 5).

    El registro, actualización de precio, alertas y stops es bookkeeping
    funcional, persistido en SQLite (sobrevive reinicios del servidor —
    condición necesaria para que el módulo de aprendizaje continuo tenga
    historial real de qué aprender). `reassess_thesis` (sección 3) recibe el
    SignalEngine como parámetro en vez de como dependencia del constructor —
    evita acoplar el ciclo de vida de posiciones al motor de señales para
    todo lo demás (registro, marcado de precio, alertas), que no lo
    necesitan."""

    def __init__(self, store: SQLiteJSONStore | None = None):
        self._store = store or SQLiteJSONStore()

    def register_operation(
        self, entry: OperationEntry, risk_parameters: RiskParameters
    ) -> Position:
        position_id = str(uuid4())
        position = Position(
            id=position_id,
            entry=entry,
            risk_parameters=risk_parameters,
            current_price=entry.entry_price,
            max_favorable_excursion=0.0,
            max_adverse_excursion=0.0,
        )
        self._store.put("positions", position_id, position)
        return position

    def get(self, position_id: str) -> Position:
        position = self._store.get("positions", position_id, Position)
        if position is None:
            raise PositionNotFoundError(position_id)
        return position

    def list_active(self) -> list[Position]:
        return [p for p in self._store.get_all("positions", Position) if p.status == PositionStatus.ACTIVE]

    def list_all(self) -> list[Position]:
        return self._store.get_all("positions", Position)

    def update_mark_price(self, position_id: str, price: float) -> Position:
        position = self.get(position_id)
        position.current_price = price
        direction = 1 if position.entry.side == OperationSide.BUY else -1
        floating_pnl_pct = (
            direction * (price - position.entry.entry_price) / position.entry.entry_price * 100
        )
        position.max_favorable_excursion = max(
            position.max_favorable_excursion or 0.0, floating_pnl_pct
        )
        position.max_adverse_excursion = min(
            position.max_adverse_excursion or 0.0, floating_pnl_pct
        )
        self._store.put("positions", position_id, position)
        return position

    def reassess_thesis(self, position_id: str, signal_engine: "SignalEngine") -> ThesisReassessment:
        """Sección 3: ¿la tesis original sigue siendo válida? Regenera una
        señal fresca con el mismo SignalEngine que generó la original y
        compara: dirección (¿sigue apoyando el lado de la posición?),
        conviction_score (delta), y factores por label (cuáles
        desaparecieron/aparecieron/cambiaron de signo). Sin una señal
        original guardada no hay línea base — se dice explícitamente en vez
        de inventar una comparación."""
        position = self.get(position_id)
        original_signal = position.entry.original_signal
        if original_signal is None:
            return ThesisReassessment(
                still_valid=False,
                success_probability_delta=0.0,
                what_changed=(
                    "Esta posición no tiene una señal original registrada — sin línea base "
                    "no se puede reevaluar la tesis."
                ),
            )

        fresh_signal = signal_engine.generate_signal(position.entry.ticker, position.entry.asset_class)
        if fresh_signal is None:
            return ThesisReassessment(
                still_valid=False,
                success_probability_delta=0.0,
                what_changed=(
                    "No se pudo generar una señal nueva para este ticker en este momento "
                    "(datos insuficientes) — no se puede reevaluar la tesis."
                ),
            )

        position_direction = "long" if position.entry.side == OperationSide.BUY else "short"
        still_valid = fresh_signal.direction == position_direction
        success_probability_delta = fresh_signal.conviction_score - original_signal.conviction_score

        original_factors = {f.label: f for f in original_signal.factors}
        fresh_factors = {f.label: f for f in fresh_signal.factors}

        appeared = [fresh_factors[label] for label in fresh_factors if label not in original_factors]
        disappeared = [original_factors[label] for label in original_factors if label not in fresh_factors]
        flipped = [
            fresh_factors[label]
            for label in fresh_factors
            if label in original_factors
            and (fresh_factors[label].weight_pct > 0) != (original_factors[label].weight_pct > 0)
        ]

        changes: list[str] = []
        if not still_valid:
            changes.append(
                f'La dirección de la señal cambió de "{position_direction}" a '
                f'"{fresh_signal.direction}" — la tesis original ya no se sostiene.'
            )
        for f in disappeared:
            changes.append(f'Ya no aparece el factor "{f.label}" ({f.rationale}).')
        for f in appeared:
            changes.append(f'Apareció un factor nuevo: "{f.label}" ({f.rationale}).')
        for f in flipped:
            changes.append(f'El factor "{f.label}" cambió de sentido: {f.rationale}')
        if not changes:
            changes.append("Los factores que sostienen la tesis se mantienen sin cambios.")

        return ThesisReassessment(
            still_valid=still_valid,
            success_probability_delta=success_probability_delta,
            what_changed=" ".join(changes),
        )

    def record_thesis_reassessment(
        self, position_id: str, reassessment: ThesisReassessment
    ) -> Position:
        position = self.get(position_id)
        position.thesis_history.append(reassessment)
        self._store.put("positions", position_id, position)
        return position

    def issue_alert(self, position_id: str, alert: PositionAlert) -> Position:
        position = self.get(position_id)
        position.alerts.append(alert)
        self._store.put("positions", position_id, position)
        return position

    def update_risk_parameters(
        self, position_id: str, risk_parameters: RiskParameters
    ) -> Position:
        position = self.get(position_id)
        position.risk_parameters = risk_parameters
        self._store.put("positions", position_id, position)
        return position

    def close(
        self, position_id: str, exit_price: float, closed_at: datetime | None = None
    ) -> Position:
        position = self.get(position_id)
        position.status = PositionStatus.CLOSED
        position.exit_price = exit_price
        position.closed_at = closed_at or datetime.utcnow()
        self._store.put("positions", position_id, position)
        return position
