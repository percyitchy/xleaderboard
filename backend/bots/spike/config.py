"""Все настройки проекта"""

import logging

# Spike Detection Filters
MIN_PRICE = 0.95
MAX_SIGNAL_PRICE = 0.98
MIN_BUY_USD = 2500
SPIKE_THRESHOLD = 4
TIME_WINDOW = 120 #sec

# Refetch Configuration
REFETCH_INTERVAL = 1200  # 30 min in seconds

LOG_LEVEL = logging.INFO
LOG_FILE = 'spikes.log'

# WebSocket
WS_URL = 'wss://ws-subscriptions-clob.polymarket.com/ws/market'
CHUNK_SIZE = 3000
WS_PING_INTERVAL = 30  # Increased from 15 to reduce server load
WS_PING_TIMEOUT = None   # No timeout for ping responses

# Proxies for distributing connections across different IPs
import os

# Proxies for distributing connections across different IPs
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

# API URLs
API_URLS = 'https://gamma-api.polymarket.com/events'

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

# Telegram
#TELEGRAM_BOT_TOKEN = '8003230323:AAHUqz51kVdKj8wPOoNXJnEh4c-2YBtAnDI'
#TELEGRAM_CHAT_ID = '-5049964340'

#TELEGRAM_BOT_TOKEN = '8369541639:AAFmBkZUQ4ab_yCwtWwPGODczHG2W5c59mk'
#TELEGRAM_CHAT_ID = '-4964172582'
