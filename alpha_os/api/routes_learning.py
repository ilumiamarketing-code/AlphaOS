from fastapi import APIRouter, Depends

from alpha_os.api.deps import get_learning_engine
from alpha_os.core.models import LearningReport
from alpha_os.engine.learning_engine import LearningEngine

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/factor-performance", response_model=LearningReport)
def get_factor_performance(engine: LearningEngine = Depends(get_learning_engine)):
    """Aprendizaje continuo (spec sección 8): desempeño real de cada factor
    a través de posiciones ya cerradas. Nunca aplica cambios automáticamente
    a los pesos por defecto — solo reporta para revisión humana, y exige
    una muestra mínima por factor antes de sugerir nada."""
    return engine.analyze_factor_performance()
