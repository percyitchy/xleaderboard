"""WebSocket воркеры"""
import websocket
import json
import time
import logging
import ssl
import itertools
import requests
from urllib.parse import urlparse
from .config import WS_URL, WS_PING_INTERVAL, WS_PING_TIMEOUT, USER_AGENTS, PROXIES

# Cycle through user agents for WebSocket connections
ws_user_agent_cycle = itertools.cycle(USER_AGENTS)

# Cycle through proxies for WebSocket connections
ws_proxy_cycle = itertools.cycle(PROXIES) if PROXIES else None


def test_proxy(proxy_url, timeout=5):
    """Test if proxy is working by making a quick HTTP request"""
    try:
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname
        proxy_port = parsed.port
        proxy_auth = parsed.netloc.split('@')[0]
        proxy_user, proxy_pass = proxy_auth.split(':', 1)

        proxies = {
            'http': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}',
            'https': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}'
        }

        # Test with a simple HTTP request to httpbin.org
        response = requests.get('http://httpbin.org/ip', proxies=proxies, timeout=timeout)
        return response.status_code == 200
    except Exception as e:
        logging.warning(f"Proxy test failed for {proxy_url}: {e}")
        return False


class WebSocketWorker:
    def __init__(self, chunk, event_queue, worker_id, use_proxy=True):
        self.chunk = chunk
        self.queue = event_queue
        self.worker_id = worker_id
        self.use_proxy = use_proxy
        self.ws = None
        self.running = True
        self.reconnect_attempts = 0
        self.connection_start_time = None
        
    def on_open(self, ws):
        self.connection_start_time = time.time()
        subscribe_msg = {
            "assets_ids": self.chunk,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))
        self.reconnect_attempts = 0
        logging.info(f"Worker {self.worker_id}: Connected and subscribed to {len(self.chunk)} assets")
        
    def on_message(self, ws, message):
        # Ignore non-JSON messages (PONG frames, empty messages, etc.)
        if not message.strip() or not (message.startswith('{') or message.startswith('[')):
            return

        try:
            data = json.loads(message)

            # Validate required fields and positive values
            if 'asset_id' not in data or 'size' not in data or 'price' not in data or 'side' not in data:
                return

            size_val = data.get('size', 0)
            price_val = data.get('price', 0)
            try:
                size_f = float(size_val)
                price_f = float(price_val)
                if size_f <= 0 or price_f <= 0:
                    usd = size_f * price_f
                    logging.warning(f"Worker {self.worker_id} skipped invalid event: invalid size/price ({size_f} x {price_f} = ${usd:.2f})")
                    return
                data['size'] = size_f
                data['price'] = price_f
            except (ValueError, TypeError):
                logging.warning(f"Worker {self.worker_id} skipped invalid event: invalid size/price (non-numeric: {size_val}, {price_val})")
                return

            logging.debug(f"Worker {self.worker_id} received message: {data}")  # Debug log
            if data.get('event_type') == 'last_trade_price':
                data['_worker_id'] = self.worker_id
                data['_timestamp'] = time.time()
                self.queue.put(data)
            else:
                logging.debug(f"Worker {self.worker_id} ignored message without 'last_trade_price' event_type: {list(data.keys())}")  # Debug ignored
        except Exception as e:
            logging.error(f"Worker {self.worker_id} parse error: {e} - message: {message[:100]}...")
            
    def on_error(self, ws, error):
        error_type = "connection" if "connection" in str(error).lower() else "protocol"
        logging.error(f"Worker {self.worker_id} {error_type} error: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        duration = time.time() - self.connection_start_time if self.connection_start_time else 0
        logging.info(f"Worker {self.worker_id} closed after {duration:.1f}s (code: {close_status_code}, msg: {close_msg})")

    def subscribe_additional_assets(self, new_asset_ids):
        """Subscribe to additional asset_ids without reconnecting"""
        if not self.ws or not new_asset_ids:
            return

        try:
            # Add new assets to our chunk
            self.chunk.extend(new_asset_ids)

            # Send subscription message for new assets
            subscribe_msg = {
                "assets_ids": new_asset_ids,
                "type": "market"
            }
            self.ws.send(json.dumps(subscribe_msg))
            logging.info(f"Worker {self.worker_id}: Subscribed to {len(new_asset_ids)} additional assets")
        except Exception as e:
            logging.error(f"Worker {self.worker_id}: Failed to subscribe additional assets: {e}")
        
    def run(self):
        while self.running:
            try:
                headers = {'User-Agent': next(ws_user_agent_cycle)}
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    header=headers
                )
                run_forever_kwargs = {
                    "sslopt": {"cert_reqs": ssl.CERT_NONE},
                    "ping_interval": WS_PING_INTERVAL
                }
                if WS_PING_TIMEOUT is not None:
                    run_forever_kwargs["ping_timeout"] = WS_PING_TIMEOUT

                # Add proxy settings if proxies are available and use_proxy is enabled
                use_actual_proxy = False
                if self.use_proxy and ws_proxy_cycle:
                    proxy_url = next(ws_proxy_cycle)
                    if test_proxy(proxy_url):
                        parsed = urlparse(proxy_url)
                        proxy_host = parsed.hostname
                        proxy_port = parsed.port
                        proxy_auth = parsed.netloc.split('@')[0]  # user:pass
                        proxy_user, proxy_pass = proxy_auth.split(':', 1)

                        run_forever_kwargs.update({
                            "proxy_type": "http",
                            "http_proxy_host": proxy_host,
                            "http_proxy_port": proxy_port,
                            "http_proxy_auth": (proxy_user, proxy_pass)
                        })
                        use_actual_proxy = True
                        logging.debug(f"Worker {self.worker_id} using proxy {proxy_url}")
                    else:
                        logging.warning(f"Worker {self.worker_id} proxy {proxy_url} failed test, connecting without proxy")

                if not use_actual_proxy:
                    logging.debug(f"Worker {self.worker_id} connecting without proxy")

                self.ws.run_forever(**run_forever_kwargs)
            except Exception as e:
                self.reconnect_attempts += 1
                sleep_time = 5 * (2 ** min(self.reconnect_attempts, 5))
                logging.warning(f"Worker {self.worker_id} reconnecting in {sleep_time}s (attempt {self.reconnect_attempts}): {e}")
                time.sleep(sleep_time)
