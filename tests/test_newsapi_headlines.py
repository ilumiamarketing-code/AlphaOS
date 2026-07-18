from unittest.mock import patch

import requests

from alpha_os.adapters.news.newsapi_adapter import NewsAPIAdapter


class _FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


def test_no_api_key_returns_empty_without_network_call():
    adapter = NewsAPIAdapter()
    with patch("alpha_os.config.settings.newsapi_api_key", None):
        with patch("alpha_os.adapters.news.newsapi_adapter.requests.get") as mocked_get:
            headlines = adapter.get_market_headlines()
    mocked_get.assert_not_called()
    assert headlines == []


def test_parses_headlines_and_assigns_tier():
    payload = {
        "articles": [
            {"title": "Nvidia rompe máximos históricos", "url": "https://reuters.com/x", "source": {"name": "Reuters"}},
            {"title": "La Fed mantiene tasas", "url": "https://random-blog.com/y", "source": {"name": "Random Blog"}},
        ]
    }
    adapter = NewsAPIAdapter()
    with patch("alpha_os.config.settings.newsapi_api_key", "fake-key"):
        with patch("alpha_os.adapters.news.newsapi_adapter.requests.get") as mocked_get:
            mocked_get.return_value = _FakeResponse(payload)
            headlines = adapter.get_market_headlines(limit=5)

    assert len(headlines) == 2
    assert headlines[0].claim == "Nvidia rompe máximos históricos"
    assert headlines[0].source_tier.value == "S"


def test_filters_spam_titles():
    payload = {
        "articles": [
            {"title": "Shareholder Alert: law offices investigate", "url": "https://spam.com", "source": {"name": "Spam"}},
            {"title": "Tesla sube por expectativas de entregas", "url": "https://cnbc.com/x", "source": {"name": "CNBC"}},
        ]
    }
    adapter = NewsAPIAdapter()
    with patch("alpha_os.config.settings.newsapi_api_key", "fake-key"):
        with patch("alpha_os.adapters.news.newsapi_adapter.requests.get") as mocked_get:
            mocked_get.return_value = _FakeResponse(payload)
            headlines = adapter.get_market_headlines()

    assert len(headlines) == 1
    assert "Tesla" in headlines[0].claim


def test_network_failure_returns_empty_not_crash():
    adapter = NewsAPIAdapter()
    with patch("alpha_os.config.settings.newsapi_api_key", "fake-key"):
        with patch("alpha_os.adapters.news.newsapi_adapter.requests.get") as mocked_get:
            mocked_get.side_effect = requests.ConnectionError("boom")
            headlines = adapter.get_market_headlines()
    assert headlines == []
