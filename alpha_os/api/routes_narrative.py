from fastapi import APIRouter, Depends, Query

from alpha_os.adapters.narrative.github_adapter import GitHubActivityAdapter
from alpha_os.adapters.narrative.medium_adapter import MediumTagAdapter
from alpha_os.adapters.narrative.reddit_adapter import RedditAdapter
from alpha_os.api.deps import get_github_activity_adapter, get_medium_tag_adapter, get_reddit_adapter
from alpha_os.core.models import GitHubActivitySnapshot, MediumTagSnapshot, RedditSubredditSnapshot

router = APIRouter(prefix="/narrative", tags=["narrative"])


@router.get("/github-activity", response_model=GitHubActivitySnapshot)
def get_github_activity(
    repo: str = Query(..., description="owner/repo, ej. 'ethereum/go-ethereum' — tú decides qué proyecto consultar"),
    lookback_days: int = Query(30, ge=1, le=90),
    adapter: GitHubActivityAdapter = Depends(get_github_activity_adapter),
):
    """Gratis, sin key (60 req/hora por IP; sube a 5000 con GITHUB_TOKEN
    opcional en .env)."""
    return adapter.get_repo_activity(repo, lookback_days)


@router.get("/medium-tag", response_model=MediumTagSnapshot)
def get_medium_tag(
    tag: str = Query(..., description="tag de Medium, ej. 'artificial-intelligence', 'layer-2', 'defi'"),
    adapter: MediumTagAdapter = Depends(get_medium_tag_adapter),
):
    """Gratis, sin key. Solo los ~10-25 artículos más recientes del tag."""
    return adapter.get_tag_snapshot(tag)


@router.get("/reddit-subreddit", response_model=RedditSubredditSnapshot)
def get_reddit_subreddit(
    subreddit: str = Query(..., description="nombre del subreddit sin 'r/', ej. 'CryptoCurrency'"),
    lookback_days: int = Query(7, ge=1, le=30),
    adapter: RedditAdapter = Depends(get_reddit_adapter),
):
    """Requiere REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET en .env (app
    gratuita tipo 'script' en reddit.com/prefs/apps). Sin credenciales,
    devuelve vacío en vez de fallar."""
    return adapter.get_subreddit_snapshot(subreddit, lookback_days)
