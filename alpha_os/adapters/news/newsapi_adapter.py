import requests

from alpha_os.adapters.base import NewsAdapter
from alpha_os.config import settings
from alpha_os.core.enums import EvidenceType, SourceTier
from alpha_os.core.models import Evidence

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"

# Dominios explícitos del spec (niveles S/A). NewsAPI agrega prensa
# mainstream vetted por su curaduría, así que cualquier dominio no listado
# aquí se trata como nivel B (no como C — NewsAPI no incluye redes sociales
# ni foros, que son el verdadero nivel C).
_SOURCE_TIER_BY_DOMAIN: dict[str, SourceTier] = {
    "reuters.com": SourceTier.S,
    "bloomberg.com": SourceTier.S,
    "nasdaq.com": SourceTier.S,
    "sec.gov": SourceTier.S,
    "ft.com": SourceTier.A,
    "wsj.com": SourceTier.A,
    "barrons.com": SourceTier.A,
    "cnbc.com": SourceTier.A,
}


def _tier_for_domain(url: str) -> SourceTier:
    for domain, tier in _SOURCE_TIER_BY_DOMAIN.items():
        if domain in url:
            return tier
    return SourceTier.B


# Despachos de abogados publican el mismo boilerplate de "class action" para
# casi cualquier ticker que haya bajado de precio, todos los días — no es
# noticia real sobre la empresa y contaminaría el sentimiento. Se descarta
# por completo, no solo se excluye del score.
_SPAM_PATTERNS = (
    "securities fraud",
    "class action",
    "shareholder alert",
    "shareholder rights",
    "law offices",
    "law firm",
    "investors have opportunity",
    "deadline alert",
    "reminds investors",
    "encourages investors",
    "investor alert",
    "investor loss alert",
    "may have been misled",
    "lost money",
    "law if you",
)


def _is_spam(title: str) -> bool:
    lower = title.lower()
    return any(pattern in lower for pattern in _SPAM_PATTERNS)


class NewsAPIAdapter(NewsAdapter):
    """Fuente gratuita (newsapi.org, plan Developer). Sin API key configurada
    se comporta como el mock: devuelve una lista vacía en vez de fallar."""

    def get_recent_news(self, ticker: str, limit: int = 10) -> list[Evidence]:
        if not settings.newsapi_api_key:
            return []

        try:
            response = requests.get(
                NEWSAPI_ENDPOINT,
                params={
                    "qInTitle": ticker,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": limit,
                    "apiKey": settings.newsapi_api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        articles = response.json().get("articles", [])
        evidence = []
        for article in articles:
            url = article.get("url") or ""
            title = article.get("title") or ""
            if not title or _is_spam(title):
                continue
            evidence.append(
                Evidence(
                    claim=title,
                    source_name=article.get("source", {}).get("name", "desconocido"),
                    source_tier=_tier_for_domain(url),
                    evidence_type=EvidenceType.FACT,
                    url=url or None,
                )
            )
        return evidence
