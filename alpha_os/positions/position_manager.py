from datetime import datetime
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


class PositionNotFoundError(KeyError):
    pass


class PositionManager:
    """Ciclo de vida post-compra de una posición (Módulo 10, secciones 1-2, 5).

    El registro, actualización de precio, alertas y stops es bookkeeping
    funcional, persistido en SQLite (sobrevive reinicios del servidor —
    condición necesaria para que el módulo de aprendizaje continuo tenga
    historial real de qué aprender). La *decisión* de qué alerta emitir o
    cómo recalcular la tesis (secciones 3-4) depende del motor de señales/
    análisis y queda marcada como pendiente."""

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

    def reassess_thesis(self, position_id: str) -> ThesisReassessment:
        """Sección 3: ¿la tesis original sigue siendo válida? Requiere
        integrar analysis/(technical|fundamental|macro|sentiment|onchain) y
        comparar contra `position.entry.original_thesis`. Pendiente de
        implementar junto con el motor de señales."""
        raise NotImplementedError(
            "Recalculo de tesis pendiente — depende del motor de análisis."
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
