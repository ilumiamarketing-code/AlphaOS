from unittest.mock import patch

import requests

from alpha_os.adapters.narrative.github_adapter import GitHubActivityAdapter
from alpha_os.adapters.narrative.medium_adapter import MediumTagAdapter
from alpha_os.adapters.narrative.reddit_adapter import RedditAdapter

MEDIUM_RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test feed</title>
<item>
    <title><![CDATA[Bitcoin surges to record high on ETF inflows]]></title>
    <link>https://medium.com/example/a</link>
    <pubDate>Fri, 17 Jul 2026 12:00:00 GMT</pubDate>
</item>
<item>
    <title><![CDATA[Market crashes amid regulatory fears]]></title>
    <link>https://medium.com/example/b</link>
    <pubDate>Fri, 17 Jul 2026 11:00:00 GMT</pubDate>
</item>
</channel>
</rss>
"""


class _FakeResponse:
    def __init__(self, content=b"", json_data=None, status_ok=True):
        self.content = content
        self._json_data = json_data
        self.status_ok = status_ok

    def raise_for_status(self):
        if not self.status_ok:
            raise requests.HTTPError("boom")

    def json(self):
        return self._json_data


def test_medium_adapter_parses_titles_and_computes_sentiment():
    adapter = MediumTagAdapter()
    with patch("alpha_os.adapters.narrative.medium_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(content=MEDIUM_RSS_SAMPLE)
        snapshot = adapter.get_tag_snapshot("bitcoin")

    assert snapshot.article_count == 2
    assert snapshot.articles[0].claim == "Bitcoin surges to record high on ETF inflows"
    # una fuerte, una debil -> promedio entre -1 y 1, no exactamente 0 salvo simetria perfecta
    assert -1.0 <= snapshot.average_sentiment <= 1.0


def test_medium_adapter_network_failure_returns_empty():
    adapter = MediumTagAdapter()
    with patch("alpha_os.adapters.narrative.medium_adapter.requests.get") as mocked_get:
        mocked_get.side_effect = requests.ConnectionError("boom")
        snapshot = adapter.get_tag_snapshot("bitcoin")
    assert snapshot.has_data() is False


def test_github_adapter_computes_activity_ratio():
    adapter = GitHubActivityAdapter()
    repo_response = _FakeResponse(json_data={"stargazers_count": 100, "open_issues_count": 5})
    recent_commits = _FakeResponse(json_data=[{"sha": str(i)} for i in range(20)])
    baseline_commits = _FakeResponse(json_data=[{"sha": str(i)} for i in range(10)])

    with patch("alpha_os.adapters.narrative.github_adapter.requests.get") as mocked_get:
        mocked_get.side_effect = [repo_response, recent_commits, baseline_commits]
        snapshot = adapter.get_repo_activity("owner/repo", lookback_days=30)

    assert snapshot.stars == 100
    assert snapshot.commits_recent == 20
    assert snapshot.commits_baseline_avg == 10
    assert snapshot.commit_activity_ratio == 2.0


def test_github_adapter_repo_not_found_returns_empty():
    adapter = GitHubActivityAdapter()
    with patch("alpha_os.adapters.narrative.github_adapter.requests.get") as mocked_get:
        mocked_get.return_value = _FakeResponse(status_ok=False)
        snapshot = adapter.get_repo_activity("owner/does-not-exist")
    assert snapshot.has_data() is False


def test_reddit_adapter_no_credentials_returns_empty_without_network_call():
    adapter = RedditAdapter()
    with patch("alpha_os.adapters.narrative.reddit_adapter.requests.post") as mocked_post:
        with patch("alpha_os.adapters.narrative.reddit_adapter.requests.get") as mocked_get:
            snapshot = adapter.get_subreddit_snapshot("CryptoCurrency")
    mocked_post.assert_not_called()
    mocked_get.assert_not_called()
    assert snapshot.has_data() is False
