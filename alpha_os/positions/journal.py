from alpha_os.core.enums import OperationSide, PositionStatus
from alpha_os.core.models import JournalEntry, PositionAlert, PostMortem
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


class JournalManager:
    """Diario automático (sección 7) + gancho de aprendizaje continuo
    (sección 8), persistido en SQLite junto con las posiciones. El
    post-mortem se deriva únicamente de los factores realmente registrados
    en `original_signal` y el resultado real de la operación — nunca
    inventa qué "anticipó" un movimiento sin esa evidencia."""

    def __init__(self, position_manager: PositionManager, store: SQLiteJSONStore | None = None):
        self.position_manager = position_manager
        self._store = store or SQLiteJSONStore()

    def open_entry(self, position_id: str) -> JournalEntry:
        position = self.position_manager.get(position_id)
        entry = JournalEntry(
            position_id=position_id,
            entry_reason=position.entry.original_thesis,
            actions_taken=[f"Apertura: {position.entry.side.value} {position.entry.ticker}"],
        )
        self._store.put("journal_entries", position_id, entry)
        return entry

    def get(self, position_id: str) -> JournalEntry:
        entry = self._store.get("journal_entries", position_id, JournalEntry)
        if entry is None:
            raise KeyError(position_id)
        return entry

    def list_all(self) -> list[JournalEntry]:
        return self._store.get_all("journal_entries", JournalEntry)

    def record_change(self, position_id: str, description: str) -> JournalEntry:
        entry = self.get(position_id)
        entry.changes_during_operation.append(description)
        self._store.put("journal_entries", position_id, entry)
        return entry

    def record_alert(self, position_id: str, alert: PositionAlert) -> JournalEntry:
        entry = self.get(position_id)
        entry.alerts_issued.append(alert)
        self._store.put("journal_entries", position_id, entry)
        return entry

    def record_action(self, position_id: str, action: str) -> JournalEntry:
        entry = self.get(position_id)
        entry.actions_taken.append(action)
        self._store.put("journal_entries", position_id, entry)
        return entry

    def close_out(self, position_id: str) -> JournalEntry:
        position = self.position_manager.get(position_id)
        entry = self.get(position_id)
        if position.exit_price is not None:
            direction = 1 if position.entry.side == OperationSide.BUY else -1
            entry.profitability_pct = (
                direction
                * (position.exit_price - position.entry.entry_price)
                / position.entry.entry_price
                * 100
            )
        entry.max_gain_reached = position.max_favorable_excursion
        entry.max_floating_loss = position.max_adverse_excursion
        if position.closed_at:
            entry.time_in_market = str(position.closed_at - position.entry.executed_at)
        entry.final_result = "closed"
        self._store.put("journal_entries", position_id, entry)
        return entry

    def generate_post_mortem(self, position_id: str) -> PostMortem:
        """Sección 8. Se deriva únicamente de lo que realmente se registró:
        los factores de `original_signal` (si la posición se abrió a partir
        de una Signal generada por el motor) y el resultado real
        (`profitability_pct`). Sin `original_signal`, no hay con qué
        construir un post-mortem honesto — se levanta un error explícito en
        vez de inventar uno."""
        position = self.position_manager.get(position_id)
        entry = self.get(position_id)

        if position.status != PositionStatus.CLOSED:
            raise ValueError("La posición sigue activa — no hay resultado final para un post-mortem.")
        if position.entry.original_signal is None:
            raise NotImplementedError(
                "Esta posición no se abrió a partir de una Signal del motor "
                "(original_signal vacío) — no hay factores registrados de los "
                "que derivar qué funcionó y qué no."
            )
        if entry.profitability_pct is None:
            raise NotImplementedError("Falta profitability_pct — corre close_out() primero.")

        signal = position.entry.original_signal
        profitable = entry.profitability_pct > 0
        supporting_factors = [f.label for f in signal.factors if f.weight_pct > 0]
        contradicting_factors = [f.label for f in signal.factors if f.weight_pct < 0]

        if profitable:
            what_went_well = (
                f"La hipótesis {signal.direction} se cumplió (+{entry.profitability_pct:.1f}%). "
                f"Factores de confirmación presentes: {', '.join(supporting_factors) or 'ninguno registrado'}."
            )
            what_went_wrong = (
                f"Contradicciones que no impidieron el resultado: {', '.join(contradicting_factors)}."
                if contradicting_factors
                else "Sin contradicciones registradas en la señal original."
            )
        else:
            what_went_well = (
                "Sin aspectos positivos claros del resultado — la operación cerró en pérdida."
                if not supporting_factors
                else f"Factores que sí confirmaban la hipótesis pero no bastaron: {', '.join(supporting_factors)}."
            )
            what_went_wrong = (
                f"La hipótesis {signal.direction} no se cumplió ({entry.profitability_pct:.1f}%). "
                f"Contradicciones ya presentes en la señal original: {', '.join(contradicting_factors) or 'ninguna registrada — el score alcanzó el umbral igual'}."
            )

        return PostMortem(
            what_went_well=what_went_well,
            what_went_wrong=what_went_wrong,
            decisive_information=signal.rationale,
            signals_that_anticipated_move=supporting_factors if profitable else [],
            irrelevant_indicators=[],
            lessons_learned=(
                f"Convicción original {signal.conviction_score:.0f}/100 → resultado real "
                f"{entry.profitability_pct:+.1f}%. Usar junto con más operaciones cerradas "
                "para recalibrar pesos vía engine/learning_engine.py — un solo caso no es "
                "muestra suficiente para ajustar nada."
            ),
        )
