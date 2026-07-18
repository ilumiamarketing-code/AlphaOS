import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    alpha_vantage_api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY") or None
    polygon_api_key: str | None = os.getenv("POLYGON_API_KEY") or None
    newsapi_api_key: str | None = os.getenv("NEWSAPI_API_KEY") or None
    fred_api_key: str | None = os.getenv("FRED_API_KEY") or None
    etherscan_api_key: str | None = os.getenv("ETHERSCAN_API_KEY") or None
    # Opcional: sin esto, GitHub limita a 60 req/hora por IP en vez de 5000.
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    reddit_client_id: str | None = os.getenv("REDDIT_CLIENT_ID") or None
    reddit_client_secret: str | None = os.getenv("REDDIT_CLIENT_SECRET") or None
    coinmarketcal_api_key: str | None = os.getenv("COINMARKETCAL_API_KEY") or None
    # TWS/IB Gateway corren localmente en la máquina del usuario, nunca en
    # la nube — así funciona la API de IBKR. Puertos por defecto de TWS:
    # 7497 paper, 7496 real. IB Gateway: 4002 paper, 4001 real.
    ibkr_host: str = os.getenv("IBKR_HOST", "127.0.0.1")
    ibkr_port: int = int(os.getenv("IBKR_PORT", "7497"))
    ibkr_client_id: int = int(os.getenv("IBKR_CLIENT_ID", "1"))
    # 45 = punto intermedio. Con técnico + fundamentales + sentimiento
    # conectados (máximo teórico ~73), exige varios factores de confirmación
    # convergentes (ej. tendencia + momentum + fundamentales sanos) pero no
    # una alineación casi perfecta como el 70 original del spec. Subir hacia
    # 70 cuando macro/institucional se conecten y el máximo teórico crezca.
    signal_confidence_threshold: int = int(os.getenv("SIGNAL_CONFIDENCE_THRESHOLD", "45"))


settings = Settings()
