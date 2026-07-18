from datetime import datetime

from pydantic import BaseModel


class MacroEvent(BaseModel):
    name: str
    scheduled_at: datetime
    importance: str  # "low" | "medium" | "high"


def get_upcoming_macro_events(days_ahead: int = 7) -> list[MacroEvent]:
    """Pendiente de un adapter de calendario macro (ej. Trading Economics,
    FRED release calendar). El snapshot de nivel/tendencia (fed funds, CPI)
    ya se obtiene vía MacroDataAdapter — esto es solo el calendario de
    próximos eventos, que sigue sin fuente conectada."""
    return []
