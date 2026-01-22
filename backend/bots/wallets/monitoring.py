import asyncio
import aiohttp
import time
import random
import logging
import json
from datetime import datetime, timedelta
from aiohttp_socks import ProxyConnector
from .config import (
    MONITORING_URL, PROXIES, USER_AGENTS,
    ALERT_WINDOW_MINUTES, MIN_BUY_SIZE_USDC, MIN_CONCURRENT_WALLETS,
    MONITORING_CYCLE_DELAY, MAX_PRICE_THRESHOLD
)
from .sourcing import fetch_top_traders

# Configure logging
logger = logging.getLogger("wallets_bot")

class WalletsBot:
    def __init__(self, signal_store, ws_manager):
        self.signal_store = signal_store
        self.ws_manager = ws_manager
        self.running = True
        self.active_markets = {}
        self.wallet_checkpoints = {}
        self.trader_info = {}
        self.sessions = []
        self.sent_alerts = {}  # Track sent alerts to prevent duplicates: (market_id, outcomeIndex, category) -> set(wallets)
        
    def get_random_session(self):
        if not self.sessions:
            return None
        return random.choice(self.sessions)

    def get_random_headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate, br"
        }

    async def fetch_wallet_activity(self, wallet):
        """Fetches recent activity for a specific wallet."""
        params = {
            "user": wallet,
            "limit": "10",
            "type": "TRADE"
        }

        max_retries = 2
        for attempt in range(max_retries):
            session = self.get_random_session()
            if not session:
                return []
                
            headers = self.get_random_headers()

            start_time = time.time()
            try:
                # Proxy is already bound to the session
                async with session.get(MONITORING_URL, params=params, headers=headers, timeout=15, ssl=False) as response:
                    elapsed = time.time() - start_time
                    if response.status == 200:
                        data = await response.json()
                        # logger.debug(f"Wallet {wallet}: fetch successful in {elapsed:.3f}s")
                        return data
                    else:
                        # logger.debug(f"Wallet {wallet}: fetch failed in {elapsed:.3f}s (status: {response.status})")
                        pass
            except Exception as e:
                # elapsed = time.time() - start_time
                # logger.debug(f"Wallet {wallet}: fetch error in {elapsed:.3f}s (error: {str(e)})")
                pass
            
            # Wait a bit before retry if needed, but for high concurrency maybe just continue
            # await asyncio.sleep(0.5)
            
        return []

    def process_activity(self, wallet, activities):
        """Filters and processes a list of activities for a wallet."""
        current_time = time.time()
        
        # Get last checkpoint
        last_checkpoint = self.wallet_checkpoints.get(wallet, 0)
        new_checkpoint = last_checkpoint
        
        for activity in activities:
            # 1. Novelty Check
            timestamp = activity.get("timestamp")
            if not timestamp:
                continue
                
            if timestamp <= last_checkpoint:
                continue
                
            # Update max timestamp for next checkpoint
            if timestamp > new_checkpoint:
                new_checkpoint = timestamp
                
            # 2. Type Check
            if activity.get("side") != "BUY":
                continue
                
            # 3. Recency Check
            if timestamp > 1000000000000: # It's ms
                 ts_seconds = timestamp / 1000
            else:
                 ts_seconds = timestamp
                 
            if current_time - ts_seconds > (ALERT_WINDOW_MINUTES * 60):
                continue
                
            # 4. Whale Filter
            usdc_size = float(activity.get("usdcSize", 0))
            if usdc_size < MIN_BUY_SIZE_USDC:
                continue
                
            # Passed all filters
            market_id = activity.get("slug")
            
            if market_id:
                if market_id not in self.active_markets:
                    self.active_markets[market_id] = {}
                
                # Add to active markets
                trade_data = {
                    "timestamp": ts_seconds,
                    "usdcSize": usdc_size,
                    "price": float(activity.get("price", 0)),
                    "outcomeIndex": activity.get("outcomeIndex", 0),
                    "outcome": activity.get("outcome", ""),
                    "title": activity.get("title", market_id),
                    "eventSlug": activity.get("eventSlug", "")
                }
                self.active_markets[market_id][wallet] = trade_data
        
        # Update checkpoint
        self.wallet_checkpoints[wallet] = new_checkpoint

    def cleanup_active_markets(self):
        """Removes entries older than ALERT_WINDOW_MINUTES."""
        current_time = time.time()
        cutoff_time = current_time - (ALERT_WINDOW_MINUTES * 60)

        markets_to_remove = []

        for market_id, wallets in self.active_markets.items():
            # Remove old wallets
            wallets_to_remove = [w for w, data in wallets.items() if data["timestamp"] < cutoff_time]
            for w in wallets_to_remove:
                del wallets[w]

            if not wallets:
                markets_to_remove.append(market_id)

        for m in markets_to_remove:
            del self.active_markets[m]
            
            # Also cleanup sent_alerts for this market
            # We need to find keys that start with this market_id
            keys_to_remove = [k for k in self.sent_alerts.keys() if k[0] == m]
            for k in keys_to_remove:
                del self.sent_alerts[k]

    async def fetch_market_details(self, slug):
        """Fetches market details from Gamma API."""
        url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
        max_retries = 3
        for attempt in range(max_retries):
            session = self.get_random_session()
            if not session:
                return None
            headers = self.get_random_headers()
            
            try:
                async with session.get(url, headers=headers, timeout=30, ssl=False) as response:
                    if response.status == 200:
                        return await response.json()
            except Exception:
                pass
        return None

    async def check_for_alerts(self):
        """Checks active markets for alert conditions."""
        for market_id, wallets in self.active_markets.items():
            if len(wallets) < MIN_CONCURRENT_WALLETS:
                continue

            # Group by (outcomeIndex, category)
            outcome_category_groups = {}
            for wallet, trade_data in wallets.items():
                category = self.trader_info.get(wallet, {}).get("category", "Unknown")
                oi = trade_data["outcomeIndex"]
                group_key = (oi, category)

                if group_key not in outcome_category_groups:
                    outcome_category_groups[group_key] = []
                outcome_category_groups[group_key].append((wallet, trade_data))

            # Check for groups with >= MIN_CONCURRENT_WALLETS
            for (oi, category), group in outcome_category_groups.items():
                if len(group) >= MIN_CONCURRENT_WALLETS:
                    # Deduplication check
                    current_wallets_set = set(w for w, _ in group)
                    alert_key = (market_id, oi, category)
                    
                    if alert_key in self.sent_alerts:
                        previous_wallets_set = self.sent_alerts[alert_key]
                        # If the set of wallets is exactly the same, skip alert
                        if current_wallets_set == previous_wallets_set:
                            continue

                    # Get common outcome text
                    outcome_text = group[0][1]["outcome"]
                    outcome_idx = int(group[0][1]["outcomeIndex"])
                    total_usd = sum(trade["usdcSize"] for _, trade in group)

                    # Fetch market details for price and asset_id
                    market_details = await self.fetch_market_details(market_id)
                    current_price = 0.0
                    asset_id = None

                    if market_details:
                        try:
                            # 1. Parse Prices
                            outcome_prices_raw = market_details.get("outcomePrices", "[]")
                            prices = []
                            if isinstance(outcome_prices_raw, list):
                                prices = outcome_prices_raw
                            elif isinstance(outcome_prices_raw, str):
                                try:
                                    prices = json.loads(outcome_prices_raw)
                                except json.JSONDecodeError:
                                    prices = []

                            if 0 <= outcome_idx < len(prices):
                                current_price = float(prices[outcome_idx])
                                
                            # 2. Parse Token IDs (Asset IDs)
                            clob_ids_raw = market_details.get("clobTokenIds", "[]")
                            clob_ids = []
                            if isinstance(clob_ids_raw, list):
                                clob_ids = clob_ids_raw
                            elif isinstance(clob_ids_raw, str):
                                try:
                                    clob_ids = json.loads(clob_ids_raw)
                                except json.JSONDecodeError:
                                    clob_ids = []
                            
                            if 0 <= outcome_idx < len(clob_ids):
                                asset_id = str(clob_ids[outcome_idx])
                                
                        except Exception as e:
                            logger.error(f"Error parsing details for {market_id}: {e}")
                            pass
                            
                    # Price Filter Check
                    if current_price > MAX_PRICE_THRESHOLD:
                        # logger.info(f"Skipping alert for {market_id} - Price {current_price} > {MAX_PRICE_THRESHOLD}")
                        continue

                    # Update sent alerts with current set (only if we are actually going to alert)
                    self.sent_alerts[alert_key] = current_wallets_set

                    # Construct signal data
                    wallets_list = []
                    for w, trade in group:
                        trader_data = self.trader_info.get(w, {}).get("data", {})
                        wallets_list.append({
                            "address": w,
                            "win_rate": round(trader_data.get("win_rate", 0) * 100, 1),
                            "buy_price": trade.get("price", 0),
                            "size": trade.get("usdcSize", 0)
                        })

                    event_slug = group[0][1].get("eventSlug", "")
                    
                    signal_data = {
                        "market_id": market_id,
                        "question": group[0][1]['title'],
                        "outcome": outcome_text,
                        "price": current_price,
                        "usdc_size": total_usd,
                        "timestamp": time.time(),
                        "wallets": wallets_list,
                        "category": category,
                        "event_slug": event_slug,
                        "asset_id": asset_id,
                        "type": "wallet_signal"
                    }
                    
                    logger.info(f"🚨 WALLET ALERT! {category} - {outcome_text} ({len(wallets_list)} wallets)")
                    
                    # Save to DB
                    if self.signal_store:
                        self.signal_store.add_wallet_signal(signal_data)
                        
                    # Broadcast
                    if self.ws_manager:
                        # Assuming async broadcast
                        try:
                            await self.ws_manager.broadcast(signal_data)
                        except Exception as e:
                            logger.error(f"Broadcast error: {e}")

                    # Clear this group from active markets to avoid repeated alerts?
                    # Or just rely on timestamps moving out of window?
                    # The original code didn't clear, so it might alert repeatedly?
                    # Wait, original code printed alerts every cycle.
                    # We might want to deduplicate alerts.
                    # For now, let's keep it as is, but maybe add a 'last_alerted' check if needed.
                    # But since we use 'active_markets' which is cleaned up, it will alert as long as conditions met.
                    # To avoid spam, we should probably track alerted groups.
                    # But let's stick to original logic for now.

    async def run(self):
        """Main monitoring loop."""
        logger.info("[*] Fetching top traders...")
        traders = await fetch_top_traders()
        if not traders:
            logger.error("[-] Failed to fetch traders. Exiting.")
            return

        self.trader_info = {}
        for trader in traders:
            address = trader["trader"]
            category = trader.get("category", "Unknown")
            self.trader_info[address] = {
                "data": trader,
                "category": category
            }

        wallets = list(self.trader_info.keys())
        logger.info(f"[+] Monitoring {len(wallets)} wallets across categories.")

        # Initialize checkpoints
        start_checkpoint = time.time() - (ALERT_WINDOW_MINUTES * 60)
        for w in wallets:
            if w not in self.wallet_checkpoints:
                self.wallet_checkpoints[w] = start_checkpoint

        # Initialize session pool
        self.sessions = []
        
        # Ensure we have enough user agents
        agents_to_use = []
        while len(agents_to_use) < len(PROXIES):
            agents_to_use.extend(USER_AGENTS)
        agents_to_use = agents_to_use[:len(PROXIES)]

        for proxy_url, ua in zip(PROXIES, agents_to_use):
            connector = None
            if proxy_url:
                if proxy_url.startswith('socks'):
                    connector = ProxyConnector.from_url(proxy_url, limit=10, ssl=False, rdns=False)
                elif proxy_url.startswith('http'):
                    connector = ProxyConnector.from_url(proxy_url, limit=10, ssl=False, rdns=False)
                else:
                    connector = aiohttp.TCPConnector(limit=10, ssl=False)
            else:
                connector = aiohttp.TCPConnector(limit=10, ssl=False)

            session = aiohttp.ClientSession(connector=connector)
            self.sessions.append(session)
            
        if not self.sessions:
             self.sessions.append(aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)))

        try:
            while self.running:
                cycle_start = time.time()
                logger.info(f"[*] Starting cycle at {time.strftime('%H:%M:%S')}")

                # Worker pool pattern
                concurrency_limit = 300
                semaphore = asyncio.Semaphore(concurrency_limit)
                
                async def worker(wallet):
                    async with semaphore:
                        activities = await self.fetch_wallet_activity(wallet)
                        if activities:
                            self.process_activity(wallet, activities)

                # Create tasks for all wallets
                tasks = [worker(w) for w in wallets]
                
                # Run all tasks (semaphore limits concurrency)
                await asyncio.gather(*tasks)

                self.cleanup_active_markets()
                await self.check_for_alerts()
                
                cycle_duration = time.time() - cycle_start
                logger.info(f"[*] Cycle finished in {cycle_duration:.2f}s")
                
                sleep_time = max(0, MONITORING_CYCLE_DELAY - cycle_duration)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        finally:
            for session in self.sessions:
                await session.close()
