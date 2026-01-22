# config.py

# Proxies list
import os

# Proxies list
PROXIES = []
try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    proxy_file = os.path.join(base_dir, '../../proxies.txt')
    if os.path.exists(proxy_file):
        with open(proxy_file, 'r') as f:
            PROXIES = [line.strip() for line in f if line.strip()]
    
    if not PROXIES:
        PROXIES = [None]
except Exception as e:
    print(f"Error loading proxies: {e}")
    PROXIES = [None]

# User Agents for requests
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Android 14; Mobile; rv:109.0) Gecko/121.0 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Android 14; Mobile; rv:109.0) Gecko/121.0 Firefox/121.0',
    'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36'
]

# Alerting Parameters
ALERT_WINDOW_MINUTES = 50
MIN_BUY_SIZE_USDC = 500.0
MIN_CONCURRENT_WALLETS = 3
MAX_PRICE_THRESHOLD = 0.95

# Sourcing Parameters
SOURCING_CATEGORIES = ["Overall", "Sports", "Crypto", "Politics", "Up or Down"]
WALLETS_PER_CATEGORY = 499
SOURCING_URL = "https://polymarketanalytics.com/api/traders-tag-performance"
SOURCING_CRITERIA_BASE = {
    "sortColumn": "trader_name",
    "sortDirection": "ASC",
    "minPnL": 0,
    "maxPnL": 3200000,
    "minActivePositions": 0,
    "maxActivePositions": 50,
    "minWinAmount": 10000,
    "maxWinAmount": 14000000,
    "minLossAmount": -17000000,
    "maxLossAmount": 0,
    "minWinRate": 75,
    "maxWinRate": 100,
    "minCurrentValue": 0,
    "maxCurrentValue": 1000000000000,
    "minTotalPositions": 1,
    "maxTotalPositions": 500
}

# Monitoring Parameters
MONITORING_URL = "https://data-api.polymarket.com/activity"
MONITORING_CYCLE_DELAY = 40  # seconds (adjusted for load)
