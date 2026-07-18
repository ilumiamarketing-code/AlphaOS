import asyncio

from ib_async import IB, LimitOrder, MarketOrder, Stock

from alpha_os.config import settings
from alpha_os.core.models import BrokerAccountSummary, BrokerPosition, PaperOrderRequest, PaperOrderResult

# Convención de IBKR: cuentas de práctica siempre empiezan con "DU", las reales con "U".
PAPER_ACCOUNT_PREFIX = "DU"
ACCOUNT_SUMMARY_TAGS = {"NetLiquidation", "TotalCashValue", "BuyingPower"}
ORDER_STATUS_POLL_SECONDS = 1.0
ORDER_STATUS_MAX_POLLS = 5


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class IBKRAdapter:
    """Conecta con TWS o IB Gateway corriendo localmente en la máquina del
    usuario — nunca en la nube, así funciona la API de IBKR. Requiere que
    el usuario tenga la sesión iniciada y la API habilitada (Configure >
    API > Settings > Enable ActiveX and Socket Clients, agregar 127.0.0.1
    a Trusted IPs). Sin TWS/Gateway corriendo, la conexión simplemente
    falla y los métodos devuelven vacío/rechazado, igual que el resto de
    adapters de este sistema sin su fuente disponible.

    **Solo opera órdenes contra cuentas de práctica** (prefijo "DU"):
    `place_test_order` se niega a enviar la orden si la cuenta conectada
    no lo es — este sistema nunca coloca órdenes en dinero real."""

    def __init__(self):
        self.ib = IB()

    async def _ensure_connected(self) -> bool:
        if self.ib.isConnected():
            return True
        try:
            await self.ib.connectAsync(
                settings.ibkr_host, settings.ibkr_port, clientId=settings.ibkr_client_id, timeout=10
            )
            return True
        except (ConnectionRefusedError, TimeoutError, OSError, asyncio.TimeoutError):
            return False

    async def get_account_summary(self) -> BrokerAccountSummary:
        if not await self._ensure_connected():
            return BrokerAccountSummary(account="", is_paper_account=False)

        accounts = self.ib.managedAccounts()
        if not accounts:
            return BrokerAccountSummary(account="", is_paper_account=False)
        account = accounts[0]

        values = await self.ib.accountSummaryAsync(account)
        by_tag = {v.tag: v.value for v in values if v.tag in ACCOUNT_SUMMARY_TAGS}
        positions = await self._positions_for_account(account)

        return BrokerAccountSummary(
            account=account,
            is_paper_account=account.startswith(PAPER_ACCOUNT_PREFIX),
            net_liquidation=_to_float(by_tag.get("NetLiquidation")),
            total_cash=_to_float(by_tag.get("TotalCashValue")),
            buying_power=_to_float(by_tag.get("BuyingPower")),
            positions=positions,
        )

    async def get_positions(self) -> list[BrokerPosition]:
        if not await self._ensure_connected():
            return []
        return await self._positions_for_account(None)

    async def _positions_for_account(self, account: str | None) -> list[BrokerPosition]:
        raw_positions = await self.ib.reqPositionsAsync()
        return [
            BrokerPosition(account=p.account, ticker=p.contract.symbol, quantity=p.position, avg_cost=p.avgCost)
            for p in raw_positions
            if account is None or p.account == account
        ]

    async def place_test_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        def _rejected(account: str, reason: str) -> PaperOrderResult:
            return PaperOrderResult(
                account=account,
                ticker=request.ticker,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                status="rejected",
                rejected_reason=reason,
            )

        if not await self._ensure_connected():
            return _rejected("", "No se pudo conectar a TWS/IB Gateway — ¿está corriendo y con la API habilitada?")

        accounts = self.ib.managedAccounts()
        paper_accounts = [a for a in accounts if a.startswith(PAPER_ACCOUNT_PREFIX)]
        if not paper_accounts:
            return _rejected(
                accounts[0] if accounts else "",
                "Ninguna cuenta conectada es de práctica (prefijo 'DU') — este sistema nunca coloca "
                "órdenes de prueba en una cuenta real.",
            )
        account = paper_accounts[0]

        if request.order_type == "LMT" and request.limit_price is None:
            return _rejected(account, "order_type='LMT' requiere limit_price.")

        contract = Stock(request.ticker, "SMART", "USD")
        qualified = await self.ib.qualifyContractsAsync(contract)
        if not qualified:
            return _rejected(account, f"No se pudo resolver el contrato para '{request.ticker}' en IBKR.")

        order = (
            LimitOrder(request.side, request.quantity, request.limit_price)
            if request.order_type == "LMT"
            else MarketOrder(request.side, request.quantity)
        )
        order.account = account

        trade = self.ib.placeOrder(qualified[0], order)
        for _ in range(ORDER_STATUS_MAX_POLLS):
            await asyncio.sleep(ORDER_STATUS_POLL_SECONDS)
            if trade.orderStatus.status in trade.orderStatus.DoneStates:
                break

        return PaperOrderResult(
            account=account,
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            status=trade.orderStatus.status,
            order_id=trade.order.orderId,
            filled_quantity=trade.orderStatus.filled,
            avg_fill_price=trade.orderStatus.avgFillPrice or None,
        )
