# ==================== КОНСТАНТЫ (НАСТРОЙКИ) ====================

# Фильтры для маркетов
MIN_VOLUME = 30000
MAX_OUTCOME_PRICE = 0.98
MIN_OUTCOME_PRICE = 0.001
MIN_HOLDER_BALANCE = 400  # Lowered from 1500 to catch high-value positions at low prices
MIN_USD_VALUE = 500      # New filter: Position value must be > $500
MIN_HOLDERS_COUNT = 5

# Whitelist маркетов (загружаются независимо от фильтров)
MARKET_WHITELIST = []
WHITELIST_ONLY = False  # True = только whitelist маркеты, False = все + whitelist

# Фильтры для холдеров
MAX_TRADES = 100
MIN_TRADES = 5
MAX_VOL = 1200000
MIN_WALLET_AGE_DAYS = 30

# Настройки API
API_BASE_URL = "https://gamma-api.polymarket.com/markets"
DATA_API_BASE = "https://data-api.polymarket.com"
LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"
GRAPHQL_URL = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/positions-subgraph/0.0.7/gn"
API_LIMIT = 500
REQUEST_TIMEOUT = 60  # Increased for slow proxies

# Настройки кэширования
CACHE_FILE = None  # Set to file path for persistence

# Настройки вывода
OUTPUT_FILE = "polymarket_markets_with_filtered_holders.json"

# Настройки прокси и ротации
import os

# Настройки прокси и ротации
PROXIES = []
try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    proxy_file = os.path.join(base_dir, '../proxies.txt')  # backend/proxies.txt
    if os.path.exists(proxy_file):
        with open(proxy_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Check if already formatted (starts with http or socks)
                if line.startswith('http') or line.startswith('socks'):
                    PROXIES.append(line)
                    continue

                # Parse host:port:user:pass format
                parts = line.split(':')
                if len(parts) == 4:
                    host, port, user, password = parts
                    formatted_proxy = f"http://{user}:{password}@{host}:{port}"
                    PROXIES.append(formatted_proxy)
                else:
                    # Assume already formatted or invalid
                    PROXIES.append(line)
    
    if not PROXIES:
        PROXIES = [None]
except Exception as e:
    print(f"Error loading proxies: {e}")
    PROXIES = [None]

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36',
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

PROXY_TIMEOUT = 10
MAX_REQUESTS_PER_PROXY = 100

# Настройки задержек (adjusted for proxies)
DELAY_BETWEEN_REQUESTS = 0.05
DELAY_AFTER_429 = 0.55
DELAY_BETWEEN_BATCHES = 0.1
ADAPTIVE_BACKOFF_MULTIPLIER = 2.0

# Настройки конкурентности (increased with proxies)
# Настройки конкурентности (moderate for proxies)
# Настройки конкурентности (moderate for proxies)
# Настройки конкурентности (high for large proxy pool)
# Настройки конкурентности (adjusted for Data API limits)
MAX_CONCURRENT_WALLETS = 15
MAX_CONCURRENT_STATS = 15
MAX_CONCURRENT_INITIAL = 15  # Matched to proxy count (15)
MAX_CONCURRENT_DETAILED = 15
MAX_CONCURRENT_CLOSED_POSITIONS = 5

# ===============================================================


