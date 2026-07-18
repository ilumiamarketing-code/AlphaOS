from alpha_os.adapters.base import FundamentalDataAdapter
from alpha_os.core.models import FundamentalSnapshot


class MockFundamentalAdapter(FundamentalDataAdapter):
    def get_snapshot(self, ticker: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(ticker=ticker)
