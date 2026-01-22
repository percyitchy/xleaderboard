import queue
import random
import threading
import time
import sys
import logging
import asyncio
from .api_client import fetch_all_markets
from .config import CHUNK_SIZE, MIN_PRICE, LOG_LEVEL, LOG_FILE, PROXIES, REFETCH_INTERVAL
from .processors import EventProcessor
from .websocket_worker import WebSocketWorker

def filter_markets(markets):
    filtered = []
    # Words to exclude from market titles
    excluded_words = ["Up or Down", "Ethereum", "Bitcoin", "Solana", "BTC", "ETH", "XRP", "SOL", "vs.", "LoL", "Spread", "Total"]

    for market in markets:
        prices = market.get('prices', [])
        question = market.get('question', '')

        # Check if exactly 2 outcomes and both prices < 0.95
        # Also exclude markets containing excluded words in the title
        exclude_market = any(word in question for word in excluded_words)

        if (len(prices) == 2 and max(prices) < MIN_PRICE and not exclude_market):
            filtered.append(market)

    logging.info(f"Filtered to {len(filtered)} markets (both prices < {MIN_PRICE}, excluding crypto/directional markets)")
    return filtered

def build_asset_to_market_map(filtered_markets):
    asset_map = {}
    
    for market in filtered_markets:
        for i, asset_id in enumerate(market['asset_ids']):
            asset_map[asset_id] = {
                'market_id': market['conditionId'],
                'question': market['question'],
                'slug': market['slug'],
                'event_slug': market['event_slug'],  # Add event slug
                'outcomes': market['outcomes'],
                'prices': market['prices'],
                'outcome_index': i
            }
    
    return asset_map

def split_chunks(asset_ids, chunk_size=CHUNK_SIZE):
    """Split asset_ids into chunks of chunk_size"""
    chunks = []
    for i in range(0, len(asset_ids), chunk_size):
        chunks.append(asset_ids[i:i + chunk_size])
    return chunks

def setup_infrastructure(filtered_markets):
    # Extract unique asset IDs
    asset_ids = []
    for market in filtered_markets:
        asset_ids.extend(market['asset_ids'])
    asset_ids = list(set(asset_ids))  # Deduplicate
    
    logging.info(f"Total unique asset IDs: {len(asset_ids)}")
    
    # Split into chunks
    chunks = split_chunks(asset_ids)
    logging.info(f"Split into {len(chunks)} chunks (max {CHUNK_SIZE} per chunk)")
    
    # Create thread-safe queue
    event_queue = queue.Queue(maxsize=10000)
    
    return chunks, event_queue, asset_ids


class PerformanceMonitor:
    def __init__(self):
        self.events_processed = 0
        self.start_time = time.time()
        
    def log_stats(self):
        elapsed = time.time() - self.start_time
        rate = self.events_processed / elapsed if elapsed > 0 else 0
        logging.info(f"Events/sec: {rate:.2f}, Total: {self.events_processed}")


class SpikeBot:
    def __init__(self, signal_store, ws_manager):
        self.running = True
        self.workers = []
        self.processor = None
        self.logger = logging.getLogger('spike_bot')
        self.monitor = PerformanceMonitor()
        # Track current state for refetching
        self.filtered_markets = []
        self.current_asset_ids = set()
        self.last_refetch_time = 0
        self.signal_store = signal_store
        self.ws_manager = ws_manager
        
    async def refetch_and_update(self):
        """Refetch markets and update subscriptions for new asset_ids"""
        if not self.logger:
            return
        try:
            self.logger.info("Refetching markets...")
            markets = await fetch_all_markets()

            self.logger.info("Filtering new markets...")
            new_filtered = filter_markets(markets)

            # Find new markets (by conditionId)
            existing_market_ids = {m['conditionId'] for m in self.filtered_markets}
            new_markets = [m for m in new_filtered if m['conditionId'] not in existing_market_ids]

            if not new_markets:
                self.logger.info("No new markets found")
                return

            self.logger.info(f"Found {len(new_markets)} new markets")

            # Extract new asset_ids
            new_asset_ids = []
            for market in new_markets:
                new_asset_ids.extend(market['asset_ids'])
            new_asset_ids = list(set(new_asset_ids) - self.current_asset_ids)

            if not new_asset_ids:
                self.logger.info("No new asset_ids to subscribe")
                return

            self.logger.info(f"Subscribing to {len(new_asset_ids)} new asset_ids")

            # Update filtered_markets and current_asset_ids
            self.filtered_markets.extend(new_markets)
            self.current_asset_ids.update(new_asset_ids)

            # Update processor's asset_map
            new_asset_map = build_asset_to_market_map(new_markets)
            if self.processor:
                self.processor.asset_map.update(new_asset_map)

            # Subscribe new asset_ids to WebSocket workers
            self.subscribe_new_assets(new_asset_ids)

            self.last_refetch_time = time.time()
            self.logger.info(f"Successfully added {len(new_markets)} markets with {len(new_asset_ids)} asset_ids")

        except Exception as e:
            self.logger.error(f"Error during refetch: {e}")

    def subscribe_new_assets(self, new_asset_ids):
        """Distribute new asset_ids to existing WebSocket workers in batches, create new workers if needed"""
        if not self.workers or not self.logger:
            return

        # Find workers with capacity (less than CHUNK_SIZE assets)
        available_workers = []
        for worker in self.workers:
            current_count = len(worker.chunk)
            if current_count < CHUNK_SIZE:
                available_capacity = CHUNK_SIZE - current_count
                available_workers.append((worker, available_capacity))

        # Sort by available capacity (most available first)
        available_workers.sort(key=lambda x: x[1], reverse=True)

        # Group assets by worker based on capacity
        worker_assets = {worker: [] for worker, _ in available_workers}
        unassigned_assets = []

        # Distribute assets to workers
        current_worker_idx = 0
        for asset_id in new_asset_ids:
            if current_worker_idx >= len(available_workers):
                unassigned_assets.append(asset_id)
                continue

            worker, capacity = available_workers[current_worker_idx]
            worker_assets[worker].append(asset_id)

            # Check if this worker is now full
            if len(worker_assets[worker]) >= capacity:
                current_worker_idx += 1

        # Send batched subscriptions to each worker
        for worker, assets in worker_assets.items():
            if assets:
                worker.subscribe_additional_assets(assets)

        # Create new workers for unassigned assets
        if unassigned_assets:
            self.logger.info(f"Creating new workers for {len(unassigned_assets)} unassigned assets")
            new_chunks = split_chunks(unassigned_assets, CHUNK_SIZE)
            next_worker_id = len(self.workers)

            for chunk in new_chunks:
                worker = WebSocketWorker(chunk, self.workers[0].queue, next_worker_id, use_proxy=False)
                worker_thread = threading.Thread(
                    target=worker.run,
                    daemon=True
                )
                worker_thread.start()
                self.workers.append(worker)
                next_worker_id += 1
                time.sleep(0.5)  # Stagger connections

            self.logger.info(f"Created {len(new_chunks)} new workers without proxy")

    async def run(self):
        # Step 1: Fetch markets
        self.logger.info("Fetching markets...")
        markets = await fetch_all_markets()

        # Step 2: Filter markets
        self.logger.info("Filtering markets...")
        filtered = filter_markets(markets)
        self.filtered_markets = filtered  # Store for refetching
        self.last_refetch_time = time.time()

        # Step 3: Setup infrastructure
        chunks, event_queue, asset_ids = setup_infrastructure(filtered)
        self.current_asset_ids = set(asset_ids)  # Store for refetching
        asset_map = build_asset_to_market_map(filtered)

        # Step 4: Start event processor
        self.logger.info("Starting event processor...")
        self.processor = EventProcessor(event_queue, asset_map, self.monitor, self.signal_store, self.ws_manager)
        
        # Run processor as an async task
        processor_task = asyncio.create_task(self.processor.run_async())

        # Step 5: Start WebSocket workers
        self.logger.info(f"Starting {len(chunks)} WebSocket workers...")
        for i, chunk in enumerate(chunks):
            worker = WebSocketWorker(chunk, event_queue, i, use_proxy=False)
            worker_thread = threading.Thread(
                target=worker.run,
                daemon=True
            )
            worker_thread.start()
            self.workers.append(worker)
            time.sleep(0.5)  # Stagger connections

        self.logger.info("✅ Spike Bot running.")

        # Status monitoring loop
        while self.running:
            await asyncio.sleep(30)

            # Check if it's time to refetch markets
            current_time = time.time()
            if current_time - self.last_refetch_time >= REFETCH_INTERVAL:
                await self.refetch_and_update()

            self.logger.info(f"[Status] Queue size: {event_queue.qsize()}, "
                             f"Active markets: {len(self.processor.asset_counters)}")
            self.monitor.log_stats()
            
        # Cancel processor task on exit
        processor_task.cancel()

