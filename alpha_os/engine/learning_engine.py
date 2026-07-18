from alpha_os.core.enums import PositionStatus
from alpha_os.core.models import FactorPerformance, LearningReport
from alpha_os.positions.journal import JournalManager
from alpha_os.positions.position_manager import PositionManager

# Antes de esta cantidad de ocurrencias, cualquier promedio es ruido — no se
# reporta como base para ajustar nada (spec: "nunca sobreoptimizar").
MIN_SAMPLE_SIZE = 10


class LearningEngine:
    """Aprendizaje continuo (spec sección 8): mide el desempeño real de cada
    factor a través de posiciones ya cerradas — nunca usa información
    futura (solo posiciones con resultado final conocido) y nunca aplica
    cambios automáticamente a `DEFAULT_FACTOR_WEIGHTS`. Devuelve un reporte
    para revisión humana; recalibrar pesos a mano sigue siendo una decisión
    del operador del sistema, no de este motor."""

    def __init__(self, position_manager: PositionManager, journal_manager: JournalManager):
        self.position_manager = position_manager
        self.journal_manager = journal_manager

    def analyze_factor_performance(self) -> LearningReport:
        closed_positions = [
            p for p in self.position_manager.list_all() if p.status == PositionStatus.CLOSED
        ]

        by_factor: dict[str, list[tuple[bool, float]]] = {}
        positions_with_signal_data = 0
        for position in closed_positions:
            if position.entry.original_signal is None:
                continue
            try:
                journal_entry = self.journal_manager.get(position.id)
            except KeyError:
                continue
            if journal_entry.profitability_pct is None:
                continue

            positions_with_signal_data += 1
            for factor in position.entry.original_signal.factors:
                by_factor.setdefault(factor.label, []).append(
                    (factor.weight_pct > 0, journal_entry.profitability_pct)
                )

        performances = []
        for label, occurrences in sorted(by_factor.items()):
            supporting = [p for is_supporting, p in occurrences if is_supporting]
            contradicting = [p for is_supporting, p in occurrences if not is_supporting]
            performances.append(
                FactorPerformance(
                    factor_label=label,
                    occurrences_supporting=len(supporting),
                    occurrences_contradicting=len(contradicting),
                    avg_profitability_when_supporting=(
                        sum(supporting) / len(supporting) if supporting else None
                    ),
                    win_rate_when_supporting=(
                        sum(1 for p in supporting if p > 0) / len(supporting) if supporting else None
                    ),
                    has_sufficient_sample=len(supporting) >= MIN_SAMPLE_SIZE,
                )
            )

        rationale = self._build_rationale(positions_with_signal_data, performances)

        return LearningReport(
            total_closed_positions=len(closed_positions),
            positions_with_signal_data=positions_with_signal_data,
            factor_performance=performances,
            rationale=rationale,
        )

    @staticmethod
    def _build_rationale(positions_with_signal_data: int, performances: list[FactorPerformance]) -> str:
        if positions_with_signal_data == 0:
            return (
                "No hay posiciones cerradas con Signal original registrada — "
                "sin datos reales todavía para recalibrar nada."
            )
        sufficient = [p for p in performances if p.has_sufficient_sample]
        if not sufficient:
            return (
                f"{positions_with_signal_data} posiciones cerradas con datos, pero ningún "
                f"factor alcanza la muestra mínima ({MIN_SAMPLE_SIZE} ocurrencias) para sugerir "
                "un ajuste responsable — se necesitan más operaciones cerradas."
            )
        return (
            f"{positions_with_signal_data} posiciones cerradas analizadas. "
            f"{len(sufficient)} factor(es) con muestra suficiente para revisión humana — "
            "esto nunca se aplica automáticamente a los pesos por defecto."
        )
