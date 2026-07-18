from datetime import datetime, timedelta, timezone

import requests

from alpha_os.config import settings
from alpha_os.core.models import GitHubActivitySnapshot

GITHUB_API_URL = "https://api.github.com"
PER_PAGE = 100


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": "AlphaOS research alphaos-dev@example.com",
        "Accept": "application/vnd.github+json",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


class GitHubActivityAdapter:
    """GitHub API pública, gratis. Sin `GITHUB_TOKEN` (opcional) el límite
    es 60 solicitudes/hora por IP — cada consulta usa 3, así que ~20
    consultas/hora sin token. El repo lo declara quien consulta, no se
    preselecciona qué proyecto "representa" una narrativa."""

    def get_repo_activity(self, repo: str, lookback_days: int = 30) -> GitHubActivitySnapshot:
        try:
            repo_response = requests.get(f"{GITHUB_API_URL}/repos/{repo}", headers=_headers(), timeout=15)
            repo_response.raise_for_status()
            repo_data = repo_response.json()
        except (requests.RequestException, ValueError):
            return GitHubActivitySnapshot(repo=repo, lookback_days=lookback_days)

        now = datetime.now(timezone.utc)
        recent_since = now - timedelta(days=lookback_days)
        baseline_since = now - timedelta(days=lookback_days * 2)

        commits_recent = self._count_commits(repo, recent_since, now)
        commits_baseline = self._count_commits(repo, baseline_since, recent_since)

        # Se normaliza a "promedio por ventana de lookback_days" para que el
        # ratio sea comparable, aunque ambas ventanas ya tengan igual tamaño.
        commits_baseline_avg = commits_baseline if commits_baseline is not None else None
        ratio = None
        if commits_recent is not None and commits_baseline_avg is not None and commits_baseline_avg > 0:
            ratio = commits_recent / commits_baseline_avg

        return GitHubActivitySnapshot(
            repo=repo,
            stars=repo_data.get("stargazers_count"),
            open_issues=repo_data.get("open_issues_count"),
            commits_recent=commits_recent,
            commits_baseline_avg=commits_baseline_avg,
            commit_activity_ratio=ratio,
            lookback_days=lookback_days,
        )

    def _count_commits(self, repo: str, since: datetime, until: datetime) -> int | None:
        try:
            response = requests.get(
                f"{GITHUB_API_URL}/repos/{repo}/commits",
                headers=_headers(),
                params={"since": since.isoformat(), "until": until.isoformat(), "per_page": PER_PAGE},
                timeout=15,
            )
            response.raise_for_status()
            return len(response.json())
        except (requests.RequestException, ValueError):
            return None
