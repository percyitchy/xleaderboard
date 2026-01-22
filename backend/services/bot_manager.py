import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from backend.bots.fetcher.main import run_fetcher
from backend.bots.spike.main import SpikeBot
from backend.bots.wallets.monitoring import WalletsBot
from backend.services.signal_store import SignalStore
from backend.services.websocket_mgr import WebSocketManager

logger = logging.getLogger("bot_manager")

class BotManager:
    def __init__(self, signal_store: SignalStore, ws_manager: WebSocketManager):
        self.signal_store = signal_store
        self.ws_manager = ws_manager
        self.spike_bot = None
        self.wallets_bot = None
        self.fetcher_task = None
        self.spike_task = None
        self.wallets_task = None
        self.running = False

    async def start_bots(self):
        """Starts all bots in background tasks based on env vars."""
        self.running = True
        logger.info("Starting bots...")

        # 1. Start Spike Bot
        if os.getenv("ENABLE_SPIKE", "true").lower() == "true":
            self.spike_bot = SpikeBot(self.signal_store, self.ws_manager)
            self.spike_task = asyncio.create_task(self.spike_bot.run())
            logger.info("Spike Bot started.")
        else:
            logger.info("Spike Bot disabled via env var.")

        # 2. Start Wallets Bot
        if os.getenv("ENABLE_WALLETS", "true").lower() == "true":
            self.wallets_bot = WalletsBot(self.signal_store, self.ws_manager)
            self.wallets_task = asyncio.create_task(self.wallets_bot.run())
            logger.info("Wallets Bot started.")
        else:
            logger.info("Wallets Bot disabled via env var.")

        # 3. Start Fetcher (Periodic)
        if os.getenv("ENABLE_FETCHER", "true").lower() == "true":
            self.fetcher_task = asyncio.create_task(self.run_fetcher_loop())
            logger.info("Fetcher loop started.")
        else:
            logger.info("Fetcher loop disabled via env var.")

    async def run_fetcher_loop(self):
        """Runs the fetcher periodically, respecting 12h interval across restarts."""
        while self.running:
            # Check last run time from DB
            last_result = self.signal_store.get_latest_fetcher_result()
            last_run_time = None
            
            if last_result and "created_at" in last_result:
                try:
                    # Parse timestamp (SQLite stores as string usually)
                    # Format: "YYYY-MM-DD HH:MM:SS" (UTC from CURRENT_TIMESTAMP)
                    last_run_str = last_result["created_at"]
                    # Ensure we handle potential timezone info or lack thereof
                    last_run_time = datetime.fromisoformat(last_run_str)
                    if last_run_time.tzinfo is None:
                        last_run_time = last_run_time.replace(tzinfo=timezone.utc)
                except Exception as e:
                    logger.error(f"Error parsing last run time: {e}")

            should_run = True
            if last_run_time:
                now = datetime.now(timezone.utc)
                elapsed = now - last_run_time
                interval = timedelta(hours=3)
                
                if elapsed < interval:
                    remaining = interval - elapsed
                    wait_seconds = remaining.total_seconds()
                    if wait_seconds > 0:
                        logger.info(f"Fetcher ran recently ({elapsed} ago). Sleeping for {remaining} until next run.")
                        should_run = False
                        # Wait for the remainder of the interval
                        try:
                            await asyncio.sleep(wait_seconds)
                        except asyncio.CancelledError:
                            break
                        # After waking up, we can run (or loop back and check again, but running is fine)
                        should_run = True

            if should_run and self.running:
                logger.info("Running Fetcher...")
                try:
                    await run_fetcher()
                    logger.info("Fetcher run complete.")
                except Exception as e:
                    logger.error(f"Fetcher error: {e}")
            
            # Wait for 3 hours before next run
            if self.running:
                logger.info("Sleeping for 3 hours...")
                await asyncio.sleep(3 * 60 * 60)

    async def stop_bots(self):
        """Stops all bots."""
        self.running = False
        logger.info("Stopping bots...")

        if self.spike_bot:
            self.spike_bot.running = False
        if self.wallets_bot:
            self.wallets_bot.running = False
        
        # Cancel tasks
        if self.spike_task:
            self.spike_task.cancel()
        if self.wallets_task:
            self.wallets_task.cancel()
        if self.fetcher_task:
            self.fetcher_task.cancel()
            
        logger.info("Bots stopped.")
