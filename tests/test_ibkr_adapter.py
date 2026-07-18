from unittest.mock import AsyncMock, MagicMock

from ib_async import AccountValue, Contract, OrderStatus, Position, Trade

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.core.models import PaperOrderRequest


def _connected_adapter(managed_accounts=("DU1234567",)) -> IBKRAdapter:
    adapter = IBKRAdapter()
    adapter.ib.isConnected = MagicMock(return_value=True)
    adapter.ib.managedAccounts = MagicMock(return_value=list(managed_accounts))
    return adapter


async def test_connection_failure_returns_empty_account_summary():
    adapter = IBKRAdapter()
    adapter.ib.isConnected = MagicMock(return_value=False)
    adapter.ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("no TWS running"))

    summary = await adapter.get_account_summary()

    assert summary.has_data() is False
    assert summary.account == ""


async def test_account_summary_flags_paper_account_and_parses_values():
    adapter = _connected_adapter(managed_accounts=("DU1234567",))
    adapter.ib.accountSummaryAsync = AsyncMock(
        return_value=[
            AccountValue(account="DU1234567", tag="NetLiquidation", value="100000.50", currency="USD", modelCode=""),
            AccountValue(account="DU1234567", tag="TotalCashValue", value="50000.0", currency="USD", modelCode=""),
            AccountValue(account="DU1234567", tag="BuyingPower", value="200000.0", currency="USD", modelCode=""),
        ]
    )
    adapter.ib.reqPositionsAsync = AsyncMock(return_value=[])

    summary = await adapter.get_account_summary()

    assert summary.account == "DU1234567"
    assert summary.is_paper_account is True
    assert summary.net_liquidation == 100000.50
    assert summary.total_cash == 50000.0
    assert summary.buying_power == 200000.0


async def test_account_summary_flags_real_account_as_not_paper():
    adapter = _connected_adapter(managed_accounts=("U7654321",))
    adapter.ib.accountSummaryAsync = AsyncMock(return_value=[])
    adapter.ib.reqPositionsAsync = AsyncMock(return_value=[])

    summary = await adapter.get_account_summary()

    assert summary.is_paper_account is False


async def test_get_positions_maps_ib_positions_to_model():
    adapter = _connected_adapter()
    contract = Contract(symbol="AAPL")
    adapter.ib.reqPositionsAsync = AsyncMock(
        return_value=[Position(account="DU1234567", contract=contract, position=10.0, avgCost=150.0)]
    )

    positions = await adapter.get_positions()

    assert len(positions) == 1
    assert positions[0].ticker == "AAPL"
    assert positions[0].quantity == 10.0
    assert positions[0].avg_cost == 150.0


async def test_place_test_order_rejected_when_no_paper_account_connected():
    adapter = _connected_adapter(managed_accounts=("U7654321",))  # cuenta real, no de práctica

    result = await adapter.place_test_order(PaperOrderRequest(ticker="AAPL", side="BUY", quantity=1))

    assert result.status == "rejected"
    assert "práctica" in result.rejected_reason


async def test_place_test_order_rejected_when_connection_fails():
    adapter = IBKRAdapter()
    adapter.ib.isConnected = MagicMock(return_value=False)
    adapter.ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("no TWS running"))

    result = await adapter.place_test_order(PaperOrderRequest(ticker="AAPL", side="BUY", quantity=1))

    assert result.status == "rejected"
    assert "conectar" in result.rejected_reason


async def test_place_test_order_rejected_when_limit_order_missing_price():
    adapter = _connected_adapter()

    result = await adapter.place_test_order(PaperOrderRequest(ticker="AAPL", side="BUY", quantity=1, order_type="LMT"))

    assert result.status == "rejected"
    assert "limit_price" in result.rejected_reason


async def test_place_test_order_submits_market_order_on_paper_account():
    adapter = _connected_adapter(managed_accounts=("DU1234567",))
    qualified_contract = Contract(symbol="AAPL", conId=265598)
    adapter.ib.qualifyContractsAsync = AsyncMock(return_value=[qualified_contract])

    trade = Trade()
    trade.order.orderId = 42
    trade.orderStatus.status = OrderStatus.Filled
    trade.orderStatus.filled = 1.0
    trade.orderStatus.avgFillPrice = 150.25
    adapter.ib.placeOrder = MagicMock(return_value=trade)

    result = await adapter.place_test_order(PaperOrderRequest(ticker="AAPL", side="BUY", quantity=1))

    assert result.status == "Filled"
    assert result.order_id == 42
    assert result.filled_quantity == 1.0
    assert result.avg_fill_price == 150.25
    assert result.account == "DU1234567"
    assert result.rejected_reason is None


async def test_place_test_order_rejected_when_contract_not_qualified():
    adapter = _connected_adapter()
    adapter.ib.qualifyContractsAsync = AsyncMock(return_value=[])

    result = await adapter.place_test_order(PaperOrderRequest(ticker="NOTAREALTICKER", side="BUY", quantity=1))

    assert result.status == "rejected"
    assert "NOTAREALTICKER" in result.rejected_reason


async def test_place_test_order_rejected_when_qualified_contract_is_none():
    """Caso real encontrado en vivo: qualifyContractsAsync puede devolver
    una lista no vacía que contiene None (no una lista vacía) cuando IBKR
    no resuelve el contrato — verificado con un ticker cripto armado como
    Stock. Antes de este fix, `qualified[0]` (None) se pasaba a placeOrder
    y tumbaba el proceso con un AttributeError de bajo nivel."""
    adapter = _connected_adapter()
    adapter.ib.qualifyContractsAsync = AsyncMock(return_value=[None])

    result = await adapter.place_test_order(PaperOrderRequest(ticker="BTC-USD", side="BUY", quantity=1))

    assert result.status == "rejected"
    assert "BTC-USD" in result.rejected_reason


async def test_place_test_order_builds_crypto_contract_for_crypto_asset_class():
    from alpha_os.core.enums import AssetClass

    adapter = _connected_adapter()
    qualified_contract = Contract(symbol="BTC", conId=1)
    adapter.ib.qualifyContractsAsync = AsyncMock(return_value=[qualified_contract])

    trade = Trade()
    trade.order.orderId = 1
    trade.orderStatus.status = OrderStatus.Filled
    trade.orderStatus.filled = 0.02
    trade.orderStatus.avgFillPrice = 50000.0
    adapter.ib.placeOrder = MagicMock(return_value=trade)

    await adapter.place_test_order(
        PaperOrderRequest(ticker="BTC-USD", asset_class=AssetClass.CRYPTO, side="BUY", quantity=0.02)
    )

    submitted_contract = adapter.ib.qualifyContractsAsync.call_args[0][0]
    assert submitted_contract.secType == "CRYPTO"
    assert submitted_contract.symbol == "BTC"


async def test_place_test_order_uses_cash_quantity_for_crypto_with_cash_amount():
    """Caso real encontrado en vivo: IBKR rechaza órdenes de cripto
    fraccionarias especificadas en cantidad de moneda con 'Deberá
    configurar la cantidad de efectivo para esta orden' — hay que pedirlas
    en dólares vía order.cashQty, con totalQuantity en 0."""
    from alpha_os.core.enums import AssetClass

    adapter = _connected_adapter()
    qualified_contract = Contract(symbol="BTC", conId=1)
    adapter.ib.qualifyContractsAsync = AsyncMock(return_value=[qualified_contract])

    trade = Trade()
    trade.order.orderId = 1
    trade.orderStatus.status = OrderStatus.Filled
    trade.orderStatus.filled = 0.02
    trade.orderStatus.avgFillPrice = 50000.0
    adapter.ib.placeOrder = MagicMock(return_value=trade)

    await adapter.place_test_order(
        PaperOrderRequest(
            ticker="BTC-USD", asset_class=AssetClass.CRYPTO, side="BUY", quantity=0.02, cash_amount=1000.0
        )
    )

    submitted_order = adapter.ib.placeOrder.call_args[0][1]
    assert submitted_order.totalQuantity == 0
    assert submitted_order.cashQty == 1000.0
    assert submitted_order.tif == "IOC"
