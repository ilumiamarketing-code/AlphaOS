import re
import xml.etree.ElementTree as ET
from datetime import date
from functools import lru_cache

import requests

from alpha_os.adapters.institutional._sec_common import SEC_HEADERS, load_ticker_map
from alpha_os.core.models import Form13FPosition

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Cobertura deliberadamente limitada a un puñado de gestores activos y
# discrecionales conocidos por su posicionamiento informativo — no un índice
# completo de los ~5000 filers 13F trimestrales (eso requeriría agregar
# miles de filings por trimestre, fuera de alcance para "13F básico").
# Se excluyen indexadores (Vanguard, BlackRock, etc.) porque replican el
# mercado casi 1:1 y no reflejan convicción discrecional.
TRACKED_MANAGERS: dict[str, str] = {
    "0001067983": "Berkshire Hathaway Inc",
    "0001037389": "Renaissance Technologies LLC",
    "0001350694": "Bridgewater Associates LP",
    "0001167483": "Tiger Global Management LLC",
}

_SUFFIX_WORDS = {
    "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LLC", "PLC", "THE",
    "CLASS", "COM", "COMMON", "STOCK", "HOLDINGS", "HOLDING", "GROUP", "SHARES",
}


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[A-Z0-9]+", name.upper())
    return {w for w in words if w not in _SUFFIX_WORDS and len(w) > 1}


def _names_match(company_title: str, issuer_name: str) -> bool:
    """13F reporta por CUSIP, no por ticker — el match es por nombre de
    emisor normalizado. Puede haber falsos negativos en nombres poco
    comunes o con abreviaturas distintas a las de SEC."""
    company_tokens = _tokens(company_title)
    if not company_tokens:
        return False
    return company_tokens.issubset(_tokens(issuer_name))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: ET.Element, name: str) -> str | None:
    for child in elem.iter():
        if _local_name(child.tag) == name:
            return child.text
    return None


@lru_cache(maxsize=512)
def _fetch_holdings_table(
    cik_nodash: str, accession_nodash: str
) -> tuple[tuple[str, str, float, float], ...]:
    """(nameOfIssuer, cusip, shares, value_usd) por fila. Cacheado porque un
    13F ya presentado nunca cambia (una enmienda tiene su propio accession
    number distinto, no muta esta misma)."""
    idx_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{accession_nodash}/index.json"
    )
    try:
        response = requests.get(idx_url, headers=SEC_HEADERS, timeout=10)
        response.raise_for_status()
        items = response.json()["directory"]["item"]
    except (requests.RequestException, KeyError, ValueError):
        return ()

    xml_name = next(
        (item["name"] for item in items if item["name"].endswith(".xml") and item["name"] != "primary_doc.xml"),
        None,
    )
    if not xml_name:
        return ()

    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{accession_nodash}/{xml_name}"
    try:
        response = requests.get(xml_url, headers=SEC_HEADERS, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError):
        return ()

    rows = []
    for elem in root.iter():
        if _local_name(elem.tag) != "infoTable":
            continue
        issuer = _child_text(elem, "nameOfIssuer")
        shares_text = _child_text(elem, "sshPrnamt")
        if not issuer or not shares_text:
            continue
        cusip = _child_text(elem, "cusip") or ""
        value_text = _child_text(elem, "value")
        rows.append((issuer, cusip, float(shares_text), float(value_text or 0)))
    return tuple(rows)


class Form13FAdapter:
    """SEC EDGAR, gratis y público, sin API key. Devuelve la posición (en
    shares/valor) de cada gestor rastreado en los `lookback_quarters` 13F-HR
    más recientes — incluyendo entradas con shares=0 cuando el gestor
    presentó ese trimestre pero no tenía holding en el emisor, para poder
    distinguir "salió de la posición" de simplemente "no consultamos ese
    trimestre". Nunca trata estos datos como posicionamiento en tiempo real:
    eso lo aplica InstitutionalEngine vía is_quarterly."""

    def get_positions(self, ticker: str, lookback_quarters: int = 2) -> list[Form13FPosition]:
        ticker_info = load_ticker_map().get(ticker.upper())
        if not ticker_info:
            return []
        company_title = ticker_info["title"]

        positions: list[Form13FPosition] = []
        for cik, manager_name in TRACKED_MANAGERS.items():
            positions.extend(
                self._manager_positions(cik, manager_name, ticker, company_title, lookback_quarters)
            )
        return positions

    def _manager_positions(
        self,
        cik: str,
        manager_name: str,
        ticker: str,
        company_title: str,
        lookback_quarters: int,
    ) -> list[Form13FPosition]:
        try:
            response = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=15)
            response.raise_for_status()
            filings = response.json()["filings"]["recent"]
        except (requests.RequestException, KeyError, ValueError):
            return []

        indices = [i for i, form in enumerate(filings.get("form", [])) if form == "13F-HR"]
        indices.sort(key=lambda i: filings["filingDate"][i], reverse=True)

        seen_periods: set[str] = set()
        selected: list[tuple[str, str, str]] = []
        for i in indices:
            report_date = filings["reportDate"][i]
            if report_date in seen_periods:
                continue
            seen_periods.add(report_date)
            selected.append((filings["accessionNumber"][i], filings["filingDate"][i], report_date))
            if len(selected) >= lookback_quarters:
                break

        cik_nodash = cik.lstrip("0") or "0"
        results = []
        for accession, filed_date, report_date in selected:
            rows = _fetch_holdings_table(cik_nodash, accession.replace("-", ""))
            total_shares = total_value = 0.0
            for issuer, _cusip, shares, value in rows:
                if _names_match(company_title, issuer):
                    total_shares += shares
                    total_value += value
            results.append(
                Form13FPosition(
                    manager_name=manager_name,
                    manager_cik=cik,
                    ticker=ticker,
                    shares=total_shares,
                    value_usd=total_value,
                    report_period_end=date.fromisoformat(report_date),
                    filed_date=date.fromisoformat(filed_date),
                )
            )
        return results
