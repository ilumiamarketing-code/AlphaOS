import time
from datetime import datetime, timedelta, timezone

import requests

from alpha_os.analysis.sentiment import score_text
from alpha_os.config import settings
from alpha_os.core.enums import EvidenceType, SourceTier
from alpha_os.core.models import Evidence, RedditSubredditSnapshot

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE_URL = "https://oauth.reddit.com"
USER_AGENT = "AlphaOS/0.1 research alphaos-dev@example.com"

_token_cache: dict[str, float | str] = {"token": "", "expires_at": 0.0}


def _get_access_token() -> str | None:
    """OAuth client_credentials — app tipo 'script' registrada en
    reddit.com/prefs/apps (gratis). Cachea el token en memoria hasta que
    expira, para no re-autenticar en cada consulta."""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]  # type: ignore[return-value]

    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return None

    try:
        response = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        return token
    except (requests.RequestException, KeyError, ValueError):
        return None


class RedditAdapter:
    """Reddit OAuth API, gratis, requiere app tipo 'script' (client_id +
    client_secret). Sin credenciales configuradas se comporta como el
    resto: vacío, no falla. El subreddit lo declara quien consulta."""

    def get_subreddit_snapshot(self, subreddit: str, lookback_days: int = 7) -> RedditSubredditSnapshot:
        token = _get_access_token()
        if not token:
            return RedditSubredditSnapshot(subreddit=subreddit, post_count=0, lookback_days=lookback_days)

        try:
            response = requests.get(
                f"{API_BASE_URL}/r/{subreddit}/new",
                params={"limit": 100},
                headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
                timeout=15,
            )
            response.raise_for_status()
            children = response.json()["data"]["children"]
        except (requests.RequestException, KeyError, ValueError):
            return RedditSubredditSnapshot(subreddit=subreddit, post_count=0, lookback_days=lookback_days)

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        posts: list[Evidence] = []
        scores: list[float] = []
        for child in children:
            post = child.get("data", {})
            created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
            if created < cutoff:
                continue
            title = post.get("title")
            if not title:
                continue
            posts.append(
                Evidence(
                    claim=title,
                    source_name=f"r/{subreddit}",
                    source_tier=SourceTier.C,
                    evidence_type=EvidenceType.RUMOR,
                    url=f"https://reddit.com{post.get('permalink', '')}" if post.get("permalink") else None,
                    observed_at=created,
                )
            )
            scores.append(post.get("score", 0))

        if not posts:
            return RedditSubredditSnapshot(subreddit=subreddit, post_count=0, lookback_days=lookback_days)

        average_sentiment = sum(score_text(p.claim) for p in posts) / len(posts)
        average_score = sum(scores) / len(scores) if scores else None
        return RedditSubredditSnapshot(
            subreddit=subreddit,
            post_count=len(posts),
            average_score=average_score,
            average_sentiment=average_sentiment,
            posts=posts,
            lookback_days=lookback_days,
        )
