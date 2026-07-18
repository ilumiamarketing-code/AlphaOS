from functools import lru_cache

import requests

# SEC exige un User-Agent identificable (no requiere API key). Ver
# https://www.sec.gov/os/webmaster-faq#developers
SEC_HEADERS = {"User-Agent": "AlphaOS research alphaos-dev@example.com"}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


@lru_cache(maxsize=1)
def load_ticker_map() -> dict[str, dict]:
    """ticker -> {"cik": 10 dígitos con ceros a la izquierda, "title": nombre
    de la empresa}. Compartido entre adapters de Form 4 y Form 13F."""
    try:
        response = requests.get(TICKER_MAP_URL, headers=SEC_HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return {}
    return {
        entry["ticker"].upper(): {"cik": str(entry["cik_str"]).zfill(10), "title": entry["title"]}
        for entry in data.values()
    }
