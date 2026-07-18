from alpha_os.adapters.base import NewsAdapter
from alpha_os.core.enums import EvidenceType, SourceTier
from alpha_os.core.models import Evidence


class MockNewsAdapter(NewsAdapter):
    """Placeholder hasta conectar NewsAPI/Reuters/Bloomberg. Devuelve una
    lista vacía por defecto para no fabricar noticias falsas."""

    def get_recent_news(self, ticker: str, limit: int = 10) -> list[Evidence]:
        return []


class ExampleNewsAdapter(NewsAdapter):
    """Solo para tests: demuestra la forma esperada del Evidence de noticias."""

    def get_recent_news(self, ticker: str, limit: int = 10) -> list[Evidence]:
        return [
            Evidence(
                claim=f"Ejemplo de titular de prueba sobre {ticker}",
                source_name="mock-wire",
                source_tier=SourceTier.C,
                evidence_type=EvidenceType.RUMOR,
            )
        ][:limit]
