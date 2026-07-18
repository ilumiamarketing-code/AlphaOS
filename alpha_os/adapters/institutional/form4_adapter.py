import xml.etree.ElementTree as ET
from datetime import date

import requests

from alpha_os.adapters.institutional._sec_common import SEC_HEADERS, load_ticker_map
from alpha_os.core.models import Form4Transaction

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Solo transacciones discrecionales de mercado abierto reflejan convicción
# del insider. Ejercicios de opciones (M), retención fiscal (F),
# otorgamientos/grants (A), regalos (G) y conversiones (C) son mecánicos o
# rutinarios — spec sección 8: "Form 4 diferencie compra, venta y ejercicio".
OPEN_MARKET_CODES = {"P", "S"}


class Form4Adapter:
    """SEC EDGAR, gratis y público, sin API key. Recorre los Form 4 más
    recientes del emisor y parsea cada uno para extraer solo transacciones
    P/S; el resto de códigos se descarta por no reflejar convicción
    discrecional. Cualquier fallo de red devuelve lista vacía, nunca
    propaga la excepción hacia el motor de señales."""

    def get_recent_transactions(self, ticker: str, limit: int = 10) -> list[Form4Transaction]:
        ticker_info = load_ticker_map().get(ticker.upper())
        if not ticker_info:
            return []
        cik = ticker_info["cik"]

        try:
            response = requests.get(
                SUBMISSIONS_URL.format(cik=cik), headers=SEC_HEADERS, timeout=15
            )
            response.raise_for_status()
            filings = response.json()["filings"]["recent"]
        except (requests.RequestException, KeyError, ValueError):
            return []

        cik_nodash = cik.lstrip("0") or "0"
        transactions: list[Form4Transaction] = []
        for i, form in enumerate(filings.get("form", [])):
            if form != "4" or len(transactions) >= limit:
                continue
            accession_nodash = filings["accessionNumber"][i].replace("-", "")
            filed_date = filings["filingDate"][i]
            xml_url = self._find_xml_url(cik_nodash, accession_nodash)
            if xml_url:
                transactions.extend(self._parse_form4(xml_url, ticker, filed_date))
        return transactions[:limit]

    def _find_xml_url(self, cik_nodash: str, accession_nodash: str) -> str | None:
        idx_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{accession_nodash}/index.json"
        )
        try:
            response = requests.get(idx_url, headers=SEC_HEADERS, timeout=10)
            response.raise_for_status()
            items = response.json()["directory"]["item"]
        except (requests.RequestException, KeyError, ValueError):
            return None
        for item in items:
            name = item["name"]
            if name.endswith(".xml") and "index" not in name.lower():
                return f"https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{accession_nodash}/{name}"
        return None

    def _parse_form4(self, xml_url: str, ticker: str, filed_date: str) -> list[Form4Transaction]:
        try:
            response = requests.get(xml_url, headers=SEC_HEADERS, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return []
        return parse_form4_xml(response.content, ticker, filed_date)


def parse_form4_xml(xml_content: bytes, ticker: str, filed_date: str) -> list[Form4Transaction]:
    """Parseo puro, sin red — separado para poder probarse con fixtures.
    Solo sobreviven códigos P/S; M (ejercicio), F (retención fiscal), A
    (grant), G (regalo), C (conversión) se descartan por no ser
    discrecionales de mercado abierto."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    insider_name = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "desconocido"
    is_officer = (root.findtext(".//reportingOwnerRelationship/isOfficer") or "false").lower() == "true"
    is_director = (root.findtext(".//reportingOwnerRelationship/isDirector") or "false").lower() == "true"

    transactions = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        code = tx.findtext(".//transactionCoding/transactionCode")
        if code not in OPEN_MARKET_CODES:
            continue
        shares_text = tx.findtext(".//transactionAmounts/transactionShares/value")
        price_text = tx.findtext(".//transactionAmounts/transactionPricePerShare/value")
        acquired_disposed = tx.findtext(".//transactionAmounts/transactionAcquiredDisposedCode/value")
        tx_date_text = tx.findtext(".//transactionDate/value")
        if not shares_text or not tx_date_text:
            continue
        transactions.append(
            Form4Transaction(
                ticker=ticker,
                insider_name=insider_name,
                is_officer=is_officer,
                is_director=is_director,
                transaction_code=code,
                acquired_disposed=acquired_disposed or "",
                shares=float(shares_text),
                price_per_share=float(price_text) if price_text else None,
                transaction_date=date.fromisoformat(tx_date_text),
                filed_date=date.fromisoformat(filed_date),
            )
        )
    return transactions
