from datetime import datetime

import requests

from alpha_os.config import settings
from alpha_os.core.models import CalendarEvent, CoinCalendarSnapshot

COINMARKETCAL_EVENTS_URL = "https://api.coinmarketcal.com/v2/events"


class CoinMarketCalAdapter:
    """CoinMarketCal API v2, requiere API key gratuita (registro en
    coinmarketcal.com/developer — cuidado, no confundir con
    coinmarketcap.com, son sitios distintos). Sin key configurada se
    comporta como el resto: vacío, no falla. Usa `coins` con el slug del
    proyecto (no el ticker — "tickers colisionan" según su propia doc,
    ej. UNI resuelve a varios proyectos distintos)."""

    def get_coin_events(self, coin_slug: str, limit: int = 20) -> CoinCalendarSnapshot:
        if not settings.coinmarketcal_api_key:
            return CoinCalendarSnapshot(coin_slug=coin_slug)

        try:
            response = requests.get(
                COINMARKETCAL_EVENTS_URL,
                headers={
                    "x-api-key": settings.coinmarketcal_api_key,
                    "Accept": "application/json",
                },
                params={"coins": coin_slug, "limit": limit},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return CoinCalendarSnapshot(coin_slug=coin_slug)

        raw_events = data.get("data") or []
        events = []
        for raw in raw_events:
            title = raw.get("title")
            date_text = raw.get("date")
            displayed_date = raw.get("displayedDate")
            if not title or not date_text or not displayed_date:
                continue
            try:
                event_date = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            except ValueError:
                continue
            categories = raw.get("categories") or []
            coins = raw.get("coins") or []
            events.append(
                CalendarEvent(
                    event_id=str(raw.get("id", "")),
                    title=title,
                    coin_symbols=[c.get("symbol") for c in coins if c.get("symbol")],
                    date=event_date,
                    displayed_date=displayed_date,
                    is_estimated=bool(raw.get("isEstimated", False)),
                    category=categories[0] if categories else None,
                    source_url=raw.get("sourceUrl"),
                    impact=raw.get("impact"),
                )
            )

        return CoinCalendarSnapshot(coin_slug=coin_slug, events=events)
