import re

from alpha_os.core.enums import SourceTier
from alpha_os.core.models import Evidence, SentimentSnapshot

# Heurística simple de léxico, no un modelo de NLP. Suficiente para una
# primera aproximación transparente y explicable; reemplazable más adelante
# por un clasificador real sin cambiar la interfaz de build_sentiment_snapshot.
POSITIVE_WORDS = {
    "surge", "surges", "surged", "soar", "soars", "soared", "rally", "rallies",
    "rallied", "beat", "beats", "upgrade", "upgrades", "upgraded", "record",
    "growth", "profit", "profits", "gain", "gains", "bullish", "outperform",
    "strong", "boost", "boosts", "expansion", "upbeat", "raise", "raises",
    "raised", "rebound", "rebounds", "optimism", "optimistic",
}

NEGATIVE_WORDS = {
    "plunge", "plunges", "plunged", "slump", "slumps", "slumped", "miss",
    "misses", "missed", "downgrade", "downgrades", "downgraded", "loss",
    "losses", "lawsuit", "lawsuits", "investigation", "recall", "recalls",
    "bearish", "underperform", "weak", "cut", "cuts", "decline", "declines",
    "declined", "warn", "warns", "warning", "fraud", "scandal", "layoff",
    "layoffs", "bankruptcy", "plummet", "plummets", "plummeted",
}

_WORD_RE = re.compile(r"[a-zA-Z]+")

# Nunca genera señal por sí solo (spec sección 2) — se excluye del promedio.
_EXCLUDED_TIER = SourceTier.C


def score_text(text: str) -> float:
    words = _WORD_RE.findall(text.lower())
    if not words:
        return 0.0
    positive = sum(1 for w in words if w in POSITIVE_WORDS)
    negative = sum(1 for w in words if w in NEGATIVE_WORDS)
    if positive + negative == 0:
        return 0.0
    return (positive - negative) / (positive + negative)


def build_sentiment_snapshot(ticker: str, evidence: list[Evidence]) -> SentimentSnapshot:
    usable = [e for e in evidence if e.source_tier != _EXCLUDED_TIER]
    if not usable:
        return SentimentSnapshot(ticker=ticker, volume_mentions=len(evidence))

    scored = [(e, score_text(e.claim)) for e in usable]
    average_score = sum(s for _, s in scored) / len(scored)
    return SentimentSnapshot(
        ticker=ticker,
        score=average_score,
        volume_mentions=len(evidence),
        supporting_evidence=[e for e, _ in scored],
    )
