from functools import lru_cache

from alpha_os.adapters.broker.ibkr_adapter import IBKRAdapter
from alpha_os.adapters.fundamental.yfinance_adapter import YFinanceFundamentalAdapter
from alpha_os.adapters.institutional.form4_adapter import Form4Adapter
from alpha_os.adapters.institutional.form13f_adapter import Form13FAdapter
from alpha_os.adapters.institutional.options_flow_adapter import OptionsFlowAdapter
from alpha_os.adapters.institutional.relative_volume_adapter import RelativeVolumeAdapter
from alpha_os.adapters.calendar.coinmarketcal_adapter import CoinMarketCalAdapter
from alpha_os.adapters.calendar.snapshot_adapter import SnapshotGovernanceAdapter
from alpha_os.adapters.macro.fred_adapter import FREDMacroAdapter
from alpha_os.adapters.market_data.cross_asset_correlation_adapter import (
    CrossAssetCorrelationAdapter,
)
from alpha_os.adapters.market_data.yfinance_adapter import YFinanceAdapter
from alpha_os.adapters.news.newsapi_adapter import NewsAPIAdapter
from alpha_os.adapters.onchain.binance_derivatives_adapter import BinanceDerivativesAdapter
from alpha_os.adapters.onchain.blockchain_info_adapter import BlockchainInfoAdapter
from alpha_os.adapters.onchain.coingecko_stablecoin_adapter import CoinGeckoStablecoinAdapter
from alpha_os.adapters.onchain.defillama_adapter import DeFiLlamaAdapter
from alpha_os.adapters.onchain.etherscan_adapter import EtherscanAdapter
from alpha_os.adapters.onchain.mock_adapter import MockOnChainAdapter
from alpha_os.adapters.narrative.github_adapter import GitHubActivityAdapter
from alpha_os.adapters.narrative.medium_adapter import MediumTagAdapter
from alpha_os.adapters.narrative.reddit_adapter import RedditAdapter
from alpha_os.engine.institutional_engine import InstitutionalEngine
from alpha_os.engine.learning_engine import LearningEngine
from alpha_os.engine.market_regime_engine import MarketRegimeEngine
from alpha_os.engine.signal_engine import SignalEngine
from alpha_os.positions.journal import JournalManager
from alpha_os.positions.portfolio_manager import PortfolioManager
from alpha_os.positions.position_manager import PositionManager
from alpha_os.positions.storage import SQLiteJSONStore


@lru_cache
def get_market_data_adapter() -> YFinanceAdapter:
    return YFinanceAdapter()


@lru_cache
def get_news_adapter() -> NewsAPIAdapter:
    return NewsAPIAdapter()


@lru_cache
def get_onchain_adapter() -> MockOnChainAdapter:
    return MockOnChainAdapter()


@lru_cache
def get_fundamental_data_adapter() -> YFinanceFundamentalAdapter:
    return YFinanceFundamentalAdapter()


@lru_cache
def get_macro_data_adapter() -> FREDMacroAdapter:
    return FREDMacroAdapter()


@lru_cache
def get_relative_volume_adapter() -> RelativeVolumeAdapter:
    return RelativeVolumeAdapter(get_market_data_adapter())


@lru_cache
def get_options_flow_adapter() -> OptionsFlowAdapter:
    return OptionsFlowAdapter()


@lru_cache
def get_form4_adapter() -> Form4Adapter:
    return Form4Adapter()


@lru_cache
def get_form13f_adapter() -> Form13FAdapter:
    return Form13FAdapter()


@lru_cache
def get_institutional_engine() -> InstitutionalEngine:
    return InstitutionalEngine(
        relative_volume=get_relative_volume_adapter(),
        options_flow=get_options_flow_adapter(),
        form4=get_form4_adapter(),
        form13f=get_form13f_adapter(),
    )


@lru_cache
def get_derivatives_data_adapter() -> BinanceDerivativesAdapter:
    return BinanceDerivativesAdapter()


@lru_cache
def get_stablecoin_data_adapter() -> CoinGeckoStablecoinAdapter:
    return CoinGeckoStablecoinAdapter()


@lru_cache
def get_cross_asset_correlation_adapter() -> CrossAssetCorrelationAdapter:
    return CrossAssetCorrelationAdapter(get_market_data_adapter())


@lru_cache
def get_blockchain_info_adapter() -> BlockchainInfoAdapter:
    return BlockchainInfoAdapter()


@lru_cache
def get_defillama_adapter() -> DeFiLlamaAdapter:
    return DeFiLlamaAdapter()


@lru_cache
def get_etherscan_adapter() -> EtherscanAdapter:
    return EtherscanAdapter()


@lru_cache
def get_github_activity_adapter() -> GitHubActivityAdapter:
    return GitHubActivityAdapter()


@lru_cache
def get_medium_tag_adapter() -> MediumTagAdapter:
    return MediumTagAdapter()


@lru_cache
def get_reddit_adapter() -> RedditAdapter:
    return RedditAdapter()


@lru_cache
def get_snapshot_governance_adapter() -> SnapshotGovernanceAdapter:
    return SnapshotGovernanceAdapter()


@lru_cache
def get_coinmarketcal_adapter() -> CoinMarketCalAdapter:
    return CoinMarketCalAdapter()


@lru_cache
def get_market_regime_engine() -> MarketRegimeEngine:
    return MarketRegimeEngine(
        market_data=get_market_data_adapter(), macro_data=get_macro_data_adapter()
    )


@lru_cache
def get_signal_engine() -> SignalEngine:
    return SignalEngine(
        market_data=get_market_data_adapter(),
        news=get_news_adapter(),
        onchain_adapter=get_onchain_adapter(),
        fundamental_data=get_fundamental_data_adapter(),
        macro_data=get_macro_data_adapter(),
        institutional_engine=get_institutional_engine(),
        market_regime_engine=get_market_regime_engine(),
        derivatives_data=get_derivatives_data_adapter(),
        stablecoin_data=get_stablecoin_data_adapter(),
    )


@lru_cache
def get_positions_store() -> SQLiteJSONStore:
    return SQLiteJSONStore()


@lru_cache
def get_position_manager() -> PositionManager:
    return PositionManager(store=get_positions_store())


@lru_cache
def get_portfolio_manager() -> PortfolioManager:
    return PortfolioManager(
        position_manager=get_position_manager(),
        correlation_adapter=get_cross_asset_correlation_adapter(),
        market_regime_engine=get_market_regime_engine(),
    )


@lru_cache
def get_journal_manager() -> JournalManager:
    return JournalManager(position_manager=get_position_manager(), store=get_positions_store())


@lru_cache
def get_learning_engine() -> LearningEngine:
    return LearningEngine(
        position_manager=get_position_manager(), journal_manager=get_journal_manager()
    )


@lru_cache
def get_ibkr_adapter() -> IBKRAdapter:
    return IBKRAdapter()
