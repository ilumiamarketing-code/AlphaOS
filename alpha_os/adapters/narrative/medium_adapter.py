import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from alpha_os.analysis.sentiment import score_text
from alpha_os.core.enums import EvidenceType, SourceTier
from alpha_os.core.models import Evidence, MediumTagSnapshot

MEDIUM_TAG_RSS_URL = "https://medium.com/feed/tag/{tag}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: ET.Element, name: str) -> str | None:
    for child in elem:
        if _local_name(child.tag) == name:
            return child.text
    return None


class MediumTagAdapter:
    """RSS público de Medium por tag, gratis y sin key. Solo expone los
    ~10-25 artículos más recientes — no hay control de ventana temporal ni
    paginación. El tag lo declara quien consulta."""

    def get_tag_snapshot(self, tag: str) -> MediumTagSnapshot:
        try:
            response = requests.get(
                MEDIUM_TAG_RSS_URL.format(tag=tag),
                headers={"User-Agent": "AlphaOS research alphaos-dev@example.com"},
                timeout=15,
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError):
            return MediumTagSnapshot(tag=tag, article_count=0)

        items = [elem for elem in root.iter() if _local_name(elem.tag) == "item"]
        articles: list[Evidence] = []
        for item in items:
            title = _child_text(item, "title")
            link = _child_text(item, "link")
            pub_date_text = _child_text(item, "pubDate")
            if not title:
                continue
            try:
                observed_at = parsedate_to_datetime(pub_date_text) if pub_date_text else datetime.now(timezone.utc)
            except (TypeError, ValueError):
                observed_at = datetime.now(timezone.utc)
            articles.append(
                Evidence(
                    claim=title,
                    source_name=f"Medium (tag: {tag})",
                    source_tier=SourceTier.B,
                    evidence_type=EvidenceType.FACT,
                    url=link,
                    observed_at=observed_at,
                )
            )

        if not articles:
            return MediumTagSnapshot(tag=tag, article_count=0)

        average_sentiment = sum(score_text(a.claim) for a in articles) / len(articles)
        return MediumTagSnapshot(
            tag=tag, article_count=len(articles), average_sentiment=average_sentiment, articles=articles
        )
