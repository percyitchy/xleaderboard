"""
Telegram notification service for Polymarket Eye signals.
Sends spike and wallet signals to Telegram channel with inline buttons.
"""
import os
import asyncio
import aiohttp
import logging
import time
from collections import defaultdict
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("telegram_service")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Signal counter TTL (1 hour)
COUNTER_TTL_SECONDS = 3600


class TelegramService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelegramService, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # Track signal counts: {(market_id, outcome): {"count": N, "last_seen": timestamp}}
        self.signal_counters = defaultdict(lambda: {"count": 0, "last_seen": 0})
        self.enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        if not self.enabled:
            logger.warning("Telegram notifications disabled: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        else:
            logger.info(f"Telegram service initialized for chat {TELEGRAM_CHAT_ID}")

    def _get_signal_count(self, market_id: str, outcome: str) -> int:
        """Get and increment signal counter, with TTL cleanup."""
        key = (market_id, outcome)
        now = time.time()
        entry = self.signal_counters[key]

        # Reset if TTL expired
        if now - entry["last_seen"] > COUNTER_TTL_SECONDS:
            entry["count"] = 0

        entry["count"] += 1
        entry["last_seen"] = now
        return entry["count"]

    def _get_alert_strength(self, amount_usd: float) -> str:
        """Return alert emoji based on USD amount."""
        if amount_usd >= 30000:
            return "🚨🚨🚨"
        elif amount_usd >= 20000:
            return "🚨🚨"
        elif amount_usd >= 10000:
            return "🚨"
        return "📈"

    def _build_polymarket_link(self, event_slug: str) -> str:
        """Build Polymarket event link."""
        return f"https://polymarket.com/event/{event_slug}?via=finance" if event_slug else ""

    def _build_trade_url(self, asset_id: str) -> str:
        """Build Polymarket Eye trade URL."""
        return f"https://www.polymarketeye.com/trade/{asset_id}" if asset_id else "https://www.polymarketeye.com"

    def _truncate(self, text: str, max_len: int = 100) -> str:
        """Truncate text with ellipsis."""
        return text[:max_len-1] + "…" if len(text) > max_len else text

    async def send_spike(self, spike_data: dict) -> bool:
        """Send spike alert to Telegram."""
        if not self.enabled:
            return False

        market_id = spike_data.get("market_id", "")
        outcome = spike_data.get("outcome", "")
        question = self._truncate(spike_data.get("question", "Unknown"))
        price = spike_data.get("price", 0)
        amount_usd = spike_data.get("amount_usd", 0)
        count = spike_data.get("count", 0)
        event_slug = spike_data.get("event_slug", "")
        asset_id = spike_data.get("asset_id", "")

        signal_count = self._get_signal_count(market_id, outcome)
        alert_emoji = self._get_alert_strength(amount_usd)
        counter_text = f" x{signal_count}" if signal_count > 1 else ""
        pm_link = self._build_polymarket_link(event_slug)

        # Format message
        message = (
            f"{alert_emoji} <b>VOLUME SPIKE{counter_text}</b>\n"
            f"📊 {question}\n"
            f"🎯 Buy <b>{outcome}</b> @ ${price:.2f}\n"
            f"💰 {count} trades • ${amount_usd:,.0f}\n"
            f"\n#VolumeSpike"
        )

        # Inline button
        trade_url = self._build_trade_url(asset_id)
        keyboard = {
            "inline_keyboard": [[
                {"text": "🚀 Trade via Polymarket Eye", "url": trade_url}
            ]]
        }

        return await self._send_message(message, keyboard)

    async def send_wallet_signal(self, signal_data: dict) -> bool:
        """Send wallet signal to Telegram."""
        if not self.enabled:
            return False

        market_id = signal_data.get("market_id", "")
        outcome = signal_data.get("outcome", "")
        question = self._truncate(signal_data.get("question", "Unknown"))
        price = signal_data.get("price", 0)
        usdc_size = signal_data.get("usdc_size", 0)
        wallets = signal_data.get("wallets", [])
        category = signal_data.get("category", "Unknown")
        event_slug = signal_data.get("event_slug", "")
        asset_id = signal_data.get("asset_id", "")

        signal_count = self._get_signal_count(market_id, outcome)
        counter_text = f" x{signal_count}" if signal_count > 1 else ""
        pm_link = self._build_polymarket_link(event_slug)

        # Format message
        message = (
            f"🎯 <b>SMART WALLETS TRACKER{counter_text}</b>\n"
            f"📊 {question}\n"
            f"🎯 Buy <b>{outcome}</b> @ ${price:.2f}\n"
            f"💰 ${usdc_size:,.0f} • {len(wallets)} wallets ({category})"
        )

        # Add wallet details (max 3) with empty line before
        message += "\n"
        for w in wallets[:3]:
            addr = w.get("address", "")[:6] + "..." + w.get("address", "")[-4:] if w.get("address") else "?"
            wr = w.get("win_rate", 0)
            size = w.get("size", 0)
            message += f"\n👛 {addr} ({wr:.0f}% WR, ${size:,.0f})"

        message += "\n\n#SmartTracker"

        # Inline button
        trade_url = self._build_trade_url(asset_id)
        keyboard = {
            "inline_keyboard": [[
                {"text": "🚀 Trade via Polymarket Eye", "url": trade_url}
            ]]
        }

        return await self._send_message(message, keyboard)

    async def _send_message(self, text: str, reply_markup: Optional[dict] = None) -> bool:
        """Send message to Telegram channel."""
        if not self.enabled:
            return False

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{TELEGRAM_API_URL}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Telegram message sent successfully")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Telegram API error {resp.status}: {error}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False


# Singleton instance
telegram_service = TelegramService()
