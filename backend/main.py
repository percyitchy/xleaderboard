from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import asyncio
import time
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
import httpx
from httpx_socks import AsyncProxyTransport
from bs4 import BeautifulSoup
import re
import random
import os

# Load environment variables
load_dotenv()

from backend.services.signal_store import SignalStore
from backend.services.websocket_mgr import WebSocketManager
from backend.services.bot_manager import BotManager
from backend.services.trading_service import trading_service
from backend.models import SpikeSignal, WalletSignal, Market, LeaderboardResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# Force formatter on all handlers (including uvicorn's)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
for handler in logging.getLogger().handlers:
    handler.setFormatter(formatter)

# Global services
signal_store = SignalStore()
ws_manager = WebSocketManager()
bot_manager = BotManager(signal_store, ws_manager)

cache_warm_task = None
leaderboard_warm_task = None

# External API config
DATA_API_BASE_URL = "https://data-api.polymarket.com"
USER_PNL_API_BASE_URL = "https://user-pnl-api.polymarket.com"

# Load proxies for API requests
LEADERBOARD_PROXIES = []
try:
    # Try multiple possible locations for proxies.txt
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.join(base_dir, 'proxies.txt'),  # backend/proxies.txt
        os.path.join(os.path.dirname(base_dir), 'proxies.txt'),  # root/proxies.txt
    ]
    proxy_file = None
    for path in possible_paths:
        if os.path.exists(path):
            proxy_file = path
            break
    
    if proxy_file:
        with open(proxy_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and (line.startswith('http') or line.startswith('socks')):
                    LEADERBOARD_PROXIES.append(line)
    if not LEADERBOARD_PROXIES:
        LEADERBOARD_PROXIES = [None]  # Fallback to no proxy
except Exception as e:
    logger.warning(f"Error loading proxies: {e}")
    LEADERBOARD_PROXIES = [None]

def _get_proxy_for_request() -> Optional[str]:
    """Get a random proxy for API requests"""
    if LEADERBOARD_PROXIES:
        return random.choice(LEADERBOARD_PROXIES)
    return None

def _create_httpx_client(timeout: float = 15.0, **kwargs) -> httpx.AsyncClient:
    """Create httpx client with proxy support (SOCKS5 and HTTP)"""
    proxy = _get_proxy_for_request()
    
    if proxy:
        if proxy.startswith('socks5://'):
            transport = AsyncProxyTransport.from_url(proxy)
            return httpx.AsyncClient(transport=transport, timeout=timeout, **kwargs)
        elif proxy.startswith('http://') or proxy.startswith('https://'):
            proxies = {"http://": proxy, "https://": proxy}
            return httpx.AsyncClient(proxies=proxies, timeout=timeout, **kwargs)
    
    return httpx.AsyncClient(timeout=timeout, **kwargs)

# Leaderboard cache settings
LEADERBOARD_CACHE: Dict[str, Dict[str, Any]] = {}
LEADERBOARD_CACHE_TTL_SECONDS = int(os.getenv("LEADERBOARD_CACHE_TTL_SECONDS", "300"))
LEADERBOARD_MAX_PAGES = int(os.getenv("LEADERBOARD_MAX_PAGES", "50"))
LEADERBOARD_PAGE_SIZE = int(os.getenv("LEADERBOARD_PAGE_SIZE", "50"))

# Portfolio value cache settings (Variant B - legacy)
PORTFOLIO_VALUE_CACHE: Dict[str, Dict[str, Any]] = {}
PORTFOLIO_VALUE_CACHE_TTL_SECONDS = int(os.getenv("PORTFOLIO_VALUE_CACHE_TTL_SECONDS", "300"))
PORTFOLIO_VALUE_CONCURRENCY = int(os.getenv("PORTFOLIO_VALUE_CONCURRENCY", "10"))

# User PnL cache settings
USER_PNL_CACHE: Dict[str, Dict[str, Any]] = {}
USER_PNL_CACHE_TTL_SECONDS = int(os.getenv("USER_PNL_CACHE_TTL_SECONDS", "300"))
USER_PNL_CONCURRENCY = int(os.getenv("USER_PNL_CONCURRENCY", "8"))
USER_PNL_INTERVAL = os.getenv("USER_PNL_INTERVAL", "1m")
USER_PNL_FIDELITY = os.getenv("USER_PNL_FIDELITY", "1d")

# Open positions cache settings
OPEN_POSITIONS_CACHE: Dict[str, Dict[str, Any]] = {}
OPEN_POSITIONS_CACHE_TTL_SECONDS = int(os.getenv("OPEN_POSITIONS_CACHE_TTL_SECONDS", "600"))
OPEN_POSITIONS_CONCURRENCY = int(os.getenv("OPEN_POSITIONS_CONCURRENCY", "2"))
OPEN_POSITIONS_MAX_PAGES = int(os.getenv("OPEN_POSITIONS_MAX_PAGES", "4"))
OPEN_POSITIONS_WARM_ENABLED = os.getenv("OPEN_POSITIONS_WARM_ENABLED", "true").lower() == "true"

PERIOD_SECONDS = {
    "DAY": 24 * 60 * 60,
    "WEEK": 7 * 24 * 60 * 60,
    "MONTH": 30 * 24 * 60 * 60,
}

LEADERBOARD_PERIODS = ["DAY", "WEEK", "MONTH"]


def _extract_list_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _to_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_leaderboard_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    proxy_wallet = raw.get("proxyWallet") or raw.get("proxy_wallet") or raw.get("user") or ""
    x_username = raw.get("xUsername") or raw.get("x_username") or ""
    name = raw.get("name") or raw.get("username") or raw.get("displayName")
    profile_image = raw.get("profileImage") or raw.get("profile_image") or raw.get("avatar")
    verified_badge = raw.get("verifiedBadge") or raw.get("verified_badge") or False

    return {
        "proxy_wallet": proxy_wallet,
        "x_username": x_username,
        "name": name,
        "profile_image": profile_image,
        "verified_badge": bool(verified_badge),
        "pnl": _to_float(raw.get("pnl")),
        "volume": _to_float(raw.get("volume"), default=None),
        "pnl_source": "leaderboard",
        "open_positions": None,
    }


async def _fetch_portfolio_value(client, proxy_wallet: str, now_ts: float) -> Optional[float]:
    cached = PORTFOLIO_VALUE_CACHE.get(proxy_wallet)
    if cached and cached["expires_at"] > now_ts:
        return cached["value"]

    response = await client.get(
        f"{DATA_API_BASE_URL}/value",
        params={"user": proxy_wallet}
    )
    if response.status_code != 200:
        logger.warning(f"Value API error for {proxy_wallet}: {response.status_code}")
        return None

    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("data", [])
    value = None
    if items:
        try:
            value = float(items[0].get("value"))
        except (TypeError, ValueError):
            value = None

    if value is not None:
        PORTFOLIO_VALUE_CACHE[proxy_wallet] = {
            "value": value,
            "expires_at": now_ts + PORTFOLIO_VALUE_CACHE_TTL_SECONDS
        }
    return value


async def _fetch_user_pnl_series(client, proxy_wallet: str, now_ts: float) -> Optional[List[Dict[str, Any]]]:
    cached = USER_PNL_CACHE.get(proxy_wallet)
    if cached and cached["expires_at"] > now_ts:
        return cached["series"]

    response = await client.get(
        f"{USER_PNL_API_BASE_URL}/user-pnl",
        params={
            "user_address": proxy_wallet,
            "interval": USER_PNL_INTERVAL,
            "fidelity": USER_PNL_FIDELITY,
        },
    )
    if response.status_code != 200:
        logger.warning(f"User PnL API error for {proxy_wallet}: {response.status_code}")
        return None

    series = response.json()
    if not isinstance(series, list):
        series = []

    USER_PNL_CACHE[proxy_wallet] = {
        "series": series,
        "expires_at": now_ts + USER_PNL_CACHE_TTL_SECONDS
    }
    return series


def _compute_pnl_from_series(series: List[Dict[str, Any]], target_ts: float) -> Optional[float]:
    if not series:
        return None

    points = []
    for item in series:
        try:
            t_val = int(item.get("t"))
            p_val = float(item.get("p"))
        except (TypeError, ValueError):
            continue
        points.append((t_val, p_val))

    if not points:
        return None

    points.sort(key=lambda p: p[0])
    latest_t, latest_p = points[-1]

    # Pick the point closest to target_ts (prefer earlier if tied)
    closest = None
    closest_dist = None
    for t_val, p_val in points[:-1]:
        dist = abs(t_val - target_ts)
        if closest_dist is None or dist < closest_dist or (dist == closest_dist and t_val < closest[0]):
            closest = (t_val, p_val)
            closest_dist = dist

    if not closest:
        closest = points[0]

    return latest_p - closest[1]


async def _fetch_open_positions_count(client, proxy_wallet: str, now_ts: float) -> Optional[int]:
    cached = OPEN_POSITIONS_CACHE.get(proxy_wallet)
    if cached and cached["expires_at"] > now_ts:
        return cached["count"]

    unique_conditions = set()
    offset = 0
    page_limit = 500
    pages = 0

    while True:
        if pages >= OPEN_POSITIONS_MAX_PAGES:
            logger.warning(f"Open positions page cap reached for {proxy_wallet}")
            break
        response = await client.get(
            f"{DATA_API_BASE_URL}/positions",
            params={
                "user": proxy_wallet,
                "limit": page_limit,
                "offset": offset,
                "sizeThreshold": 0.0,
            },
        )
        if response.status_code != 200:
            logger.warning(f"Positions API error for {proxy_wallet}: {response.status_code}")
            return None

        payload = response.json()
        items = payload if isinstance(payload, list) else payload.get("data", [])
        if not items:
            break

        for item in items:
            try:
                size = float(item.get("size", 0))
            except (TypeError, ValueError):
                size = 0

            if size <= 0:
                continue

            # Ignore redeemable (resolved) positions to match "open predictions"
            if item.get("redeemable") is True:
                continue

            condition_id = item.get("conditionId") or item.get("condition_id")
            if condition_id:
                unique_conditions.add(condition_id)
            else:
                asset_id = item.get("asset") or item.get("assetId")
                if asset_id:
                    unique_conditions.add(asset_id)

        if len(items) < page_limit:
            break
        offset += page_limit
        pages += 1

    count = len(unique_conditions)
    OPEN_POSITIONS_CACHE[proxy_wallet] = {
        "count": count,
        "expires_at": now_ts + OPEN_POSITIONS_CACHE_TTL_SECONDS
    }
    return count


async def _fetch_leaderboard_candidates(
    client, period: str, target_count: int, only_twitter: bool
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    data_offset = 0
    page_size = LEADERBOARD_PAGE_SIZE

    for _ in range(LEADERBOARD_MAX_PAGES):
        params = {
            "timePeriod": period,
            "orderBy": "PNL",
            "limit": page_size,
            "offset": data_offset,
        }
        response = await client.get(f"{DATA_API_BASE_URL}/v1/leaderboard", params=params)
        if response.status_code != 200:
            logger.warning(f"Leaderboard API error: {response.status_code}")
            break

        rows = _extract_list_payload(response.json())
        if not rows:
            break

        for raw in rows:
            entry = _normalize_leaderboard_entry(raw)
            if only_twitter and not entry["x_username"]:
                continue
            collected.append(entry)

        if len(collected) >= target_count:
            break
        data_offset += len(rows)

    return collected[:target_count]


async def _warm_open_positions_cache():
    while True:
        if not OPEN_POSITIONS_WARM_ENABLED:
            await asyncio.sleep(600)
            continue
        try:
            now_ts = time.time()
            async with httpx.AsyncClient(timeout=15.0) as client:
                for period in LEADERBOARD_PERIODS:
                    entries = await _fetch_leaderboard_candidates(client, period, 100, True)
                    semaphore = asyncio.Semaphore(OPEN_POSITIONS_CONCURRENCY)

                    async def warm_entry(entry: Dict[str, Any]) -> None:
                        async with semaphore:
                            await _fetch_open_positions_count(client, entry["proxy_wallet"], now_ts)
                        await asyncio.sleep(0.05)

                    await asyncio.gather(*[warm_entry(entry) for entry in entries])
        except Exception as exc:
            logger.warning(f"Open positions warm-up failed: {exc}")

        await asyncio.sleep(600)


async def _warm_leaderboard_cache():
    while True:
        try:
            now_ts = time.time()
            async with httpx.AsyncClient(timeout=15.0) as client:
                for period in LEADERBOARD_PERIODS:
                    entries = await _fetch_leaderboard_candidates(client, period, 100, True)

                    period_seconds = PERIOD_SECONDS[period]
                    target_ts = int(now_ts - period_seconds)
                    semaphore = asyncio.Semaphore(USER_PNL_CONCURRENCY)

                    async def load_user_pnl(entry: Dict[str, Any]) -> Dict[str, Any]:
                        async with semaphore:
                            series = await _fetch_user_pnl_series(client, entry["proxy_wallet"], now_ts)
                        pnl_value = _compute_pnl_from_series(series or [], target_ts)
                        if pnl_value is not None:
                            entry["pnl"] = pnl_value
                            entry["pnl_source"] = "user_pnl"
                        return entry

                    entries = await asyncio.gather(*[load_user_pnl(entry) for entry in entries])

                    entries.sort(key=lambda item: item["pnl"], reverse=True)
                    for idx, item in enumerate(entries):
                        item["rank"] = idx + 1

                    cache_key = f"{period}:100:0:True:user_pnl:False"
                    LEADERBOARD_CACHE[cache_key] = {
                        "expires_at": now_ts + LEADERBOARD_CACHE_TTL_SECONDS,
                        "payload": {
                            "items": entries,
                            "meta": {
                                "period": period,
                                "limit": 100,
                                "offset": 0,
                                "has_more": True,
                                "as_of": datetime.now(timezone.utc),
                                "pnl_source": "user_pnl",
                            }
                        }
                    }
        except Exception as exc:
            logger.warning(f"Leaderboard warm-up failed: {exc}")

        await asyncio.sleep(600)


# Pydantic models for trading
class TradeRequest(BaseModel):
    token_id: str
    amount_usdc: float
    side: str = "BUY"  # BUY or SELL


class PrepareOrderRequest(BaseModel):
    """Request to prepare an unsigned order for MetaMask signing"""
    user_address: str
    proxy_address: str
    token_id: str
    price: float
    size: float
    side: str = "BUY"
    order_type: str = "FOK"  # "FOK" (market) or "GTC" (limit)


class SubmitOrderRequest(BaseModel):
    """Request to submit a signed order"""
    signed_order: dict
    # User L2 Credentials (required for user wallet trading)
    user_api_key: str
    user_api_secret: str
    user_passphrase: str
    order_type: str = "FOK"  # "FOK" (market) or "GTC" (limit)


class CancelOrderRequest(BaseModel):
    """Request to cancel an open order"""
    order_id: str
    user_address: str
    user_api_key: str
    user_api_secret: str
    user_passphrase: str


class GetOrdersRequest(BaseModel):
    """Request to get open orders"""
    user_address: str
    user_api_key: str
    user_api_secret: str
    user_passphrase: str


class DeriveApiKeyRequest(BaseModel):
    """Request to derive L2 API credentials from user signature"""
    address: str
    signature: str
    timestamp: int
    nonce: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Polymarketeye Backend...")
    await bot_manager.start_bots()
    global cache_warm_task
    global leaderboard_warm_task
    cache_warm_task = asyncio.create_task(_warm_open_positions_cache())
    leaderboard_warm_task = asyncio.create_task(_warm_leaderboard_cache())
    yield
    # Shutdown
    logger.info("Shutting down Polymarketeye Backend...")
    if cache_warm_task:
        cache_warm_task.cancel()
    if leaderboard_warm_task:
        leaderboard_warm_task.cancel()
    await bot_manager.stop_bots()

app = FastAPI(title="Polymarketeye API", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "Polymarketeye"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# API Endpoints
@app.get("/api/spikes", response_model=List[SpikeSignal])
async def get_spikes():
    return signal_store.get_spikes()

@app.get("/api/wallets", response_model=List[WalletSignal])
async def get_wallet_signals(category: str = None):
    return signal_store.get_wallet_signals(category)

@app.get("/api/fetcher")
async def get_fetcher_results():
    return signal_store.get_latest_fetcher_result()

@app.get("/api/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    period: str = "DAY",
    limit: int = 100,
    offset: int = 0,
    only_twitter: bool = True,
    refresh: bool = False,
    pnl_source: str = "user_pnl",
    include_open_positions: bool = False
):
    """
    Leaderboard of Polymarket users with linked X accounts.
    Uses Data API leaderboard and filters by xUsername.
    """
    period = period.upper()
    if period not in {"DAY", "WEEK", "MONTH"}:
        raise HTTPException(status_code=400, detail="period must be DAY, WEEK, or MONTH")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if pnl_source not in {"leaderboard", "portfolio", "user_pnl"}:
        raise HTTPException(status_code=400, detail="pnl_source must be leaderboard, portfolio, or user_pnl")

    cache_key = f"{period}:{limit}:{offset}:{only_twitter}:{pnl_source}:{include_open_positions}"
    now_ts = time.time()
    cached = LEADERBOARD_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now_ts and not refresh:
        return cached["payload"]

    target_count = offset + limit
    collected: List[Dict[str, Any]] = []
    data_offset = 0
    page_size = LEADERBOARD_PAGE_SIZE
    exhausted = False

    async with _create_httpx_client(timeout=15.0) as client:
        for _ in range(LEADERBOARD_MAX_PAGES):
            params = {
                "timePeriod": period,
                "orderBy": "PNL",
                "limit": page_size,
                "offset": data_offset,
            }
            response = await client.get(f"{DATA_API_BASE_URL}/v1/leaderboard", params=params)
            if response.status_code != 200:
                logger.error(f"Leaderboard API error: {response.status_code} - {response.text}")
                raise HTTPException(status_code=502, detail="Failed to fetch leaderboard data")

            rows = _extract_list_payload(response.json())
            if not rows:
                exhausted = True
                break

            for raw in rows:
                entry = _normalize_leaderboard_entry(raw)
                if only_twitter and not entry["x_username"]:
                    continue
                collected.append(entry)

            if len(collected) >= target_count:
                break

            data_offset += len(rows)

    # Optionally compute PnL from portfolio value snapshots (Variant B)
    if pnl_source == "portfolio":
        period_seconds = PERIOD_SECONDS[period]
        target_ts = now_ts - period_seconds

        semaphore = asyncio.Semaphore(PORTFOLIO_VALUE_CONCURRENCY)
        async with _create_httpx_client(timeout=10.0) as value_client:
            async def load_value(entry: Dict[str, Any]) -> Dict[str, Any]:
                async with semaphore:
                    current_value = await _fetch_portfolio_value(value_client, entry["proxy_wallet"], now_ts)
                if current_value is not None:
                    signal_store.add_portfolio_value_snapshot(entry["proxy_wallet"], current_value, now_ts)

                past_snapshot = signal_store.get_portfolio_snapshot_before(entry["proxy_wallet"], target_ts)
                if current_value is not None and past_snapshot:
                    entry["pnl"] = current_value - float(past_snapshot["value"])
                    entry["pnl_source"] = "portfolio"
                else:
                    entry["pnl_source"] = "leaderboard"
                return entry

            collected = await asyncio.gather(*[load_value(entry) for entry in collected])

    # Compute PnL from user-pnl time series (site endpoint)
    if pnl_source == "user_pnl":
        period_seconds = PERIOD_SECONDS[period]
        target_ts = int(now_ts - period_seconds)

        semaphore = asyncio.Semaphore(USER_PNL_CONCURRENCY)
        async with _create_httpx_client(timeout=12.0) as pnl_client:
            async def load_user_pnl(entry: Dict[str, Any]) -> Dict[str, Any]:
                async with semaphore:
                    series = await _fetch_user_pnl_series(pnl_client, entry["proxy_wallet"], now_ts)
                pnl_value = _compute_pnl_from_series(series or [], target_ts)
                if pnl_value is not None:
                    entry["pnl"] = pnl_value
                    entry["pnl_source"] = "user_pnl"
                else:
                    entry["pnl_source"] = "leaderboard"
                return entry

            collected = await asyncio.gather(*[load_user_pnl(entry) for entry in collected])

    if include_open_positions:
        semaphore = asyncio.Semaphore(OPEN_POSITIONS_CONCURRENCY)
        async with _create_httpx_client(timeout=12.0) as positions_client:
            async def load_open_positions(entry: Dict[str, Any]) -> Dict[str, Any]:
                async with semaphore:
                    count = await _fetch_open_positions_count(positions_client, entry["proxy_wallet"], now_ts)
                entry["open_positions"] = count
                return entry

            collected = await asyncio.gather(*[load_open_positions(entry) for entry in collected])

    collected.sort(key=lambda item: item["pnl"], reverse=True)

    page_items = collected[offset:offset + limit]
    for idx, item in enumerate(page_items):
        item["rank"] = offset + idx + 1

    has_more = len(collected) > offset + limit or (len(collected) >= offset + limit and not exhausted)
    response_payload = {
        "items": page_items,
        "meta": {
            "period": period,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "as_of": datetime.now(timezone.utc),
            "pnl_source": pnl_source,
        }
    }

    LEADERBOARD_CACHE[cache_key] = {
        "expires_at": now_ts + LEADERBOARD_CACHE_TTL_SECONDS,
        "payload": response_payload
    }

    return response_payload

@app.get("/api/polymarket-profile")
async def get_polymarket_profile(address: str):
    """Proxy endpoint for Polymarket public profile API (bypasses CORS)"""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://gamma-api.polymarket.com/public-profile?address={address}",
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code, detail="Profile not found")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {str(e)}")


# Trader stats cache
TRADER_STATS_CACHE: Dict[str, Dict[str, Any]] = {}
TRADER_STATS_CACHE_TTL_SECONDS = 20 * 60  # 20 minutes


def _parse_win_rate(html: str) -> Optional[float]:
    """Parse 30-day win rate from HTML"""
    soup = BeautifulSoup(html, 'lxml')
    
    # Try to find JSON data in script tags (Next.js often embeds data)
    for script in soup.find_all('script'):
        script_text = script.string or ''
        # Look for JSON with win rate data
        if 'win' in script_text.lower() and 'rate' in script_text.lower():
            # Try to extract percentage values
            matches = re.findall(r'([\d.]+)%', script_text)
            for match in matches:
                try:
                    value = float(match)
                    if 0 <= value <= 100:  # Reasonable win rate
                        return value
                except ValueError:
                    continue
    
    # Try to find win rate in various formats
    # Look for text containing "win rate" or "30d" or "30 day"
    win_rate_patterns = [
        r'30[-\s]?day.*?win.*?rate[:\s]+([\d.]+)%',
        r'win.*?rate.*?30[-\s]?day[:\s]+([\d.]+)%',
        r'30d.*?win.*?rate[:\s]+([\d.]+)%',
        r'win.*?rate[:\s]+([\d.]+)%',
    ]
    
    text = soup.get_text()
    for pattern in win_rate_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                continue
    
    # Try to find in structured elements
    for elem in soup.find_all(['div', 'span', 'p', 'td', 'th']):
        text = elem.get_text()
        if 'win rate' in text.lower() and '30' in text.lower():
            numbers = re.findall(r'([\d.]+)%', text)
            if numbers:
                try:
                    return float(numbers[0])
                except ValueError:
                    continue
    
    return None


def _parse_pnl_all_time(html: str) -> Optional[float]:
    """Parse all-time PnL from HTML"""
    soup = BeautifulSoup(html, 'lxml')
    
    # Try to find JSON data in script tags
    for script in soup.find_all('script'):
        script_text = script.string or ''
        # Look for PnL values in JSON
        if 'pnl' in script_text.lower() or 'profit' in script_text.lower():
            # Try to extract dollar amounts
            matches = re.findall(r'[+-]?\$?([\d,]+\.?\d*)', script_text)
            for match in matches:
                try:
                    value = float(match.replace(',', ''))
                    # Filter reasonable PnL values (not too small, could be negative)
                    if abs(value) > 10:  # At least $10
                        return value
                except ValueError:
                    continue
    
    # Look for "all-time PnL" or "total PnL" or similar
    pnl_patterns = [
        r'all[-\s]?time.*?pnl[:\s]+[+-]?\$?([\d,]+\.?\d*)',
        r'total.*?pnl[:\s]+[+-]?\$?([\d,]+\.?\d*)',
        r'pnl.*?all[-\s]?time[:\s]+[+-]?\$?([\d,]+\.?\d*)',
        r'pnl[:\s]+[+-]?\$?([\d,]+\.?\d*)',
    ]
    
    text = soup.get_text()
    for pattern in pnl_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value_str = match.group(1).replace(',', '')
                return float(value_str)
            except (ValueError, IndexError):
                continue
    
    # Try to find in structured elements
    for elem in soup.find_all(['div', 'span', 'p', 'td', 'th']):
        text = elem.get_text()
        if ('all-time' in text.lower() or 'total' in text.lower()) and 'pnl' in text.lower():
            # Look for number with $ sign
            numbers = re.findall(r'[+-]?\$?([\d,]+\.?\d*)', text)
            if numbers:
                try:
                    return float(numbers[0].replace(',', ''))
                except ValueError:
                    continue
    
    return None


def _parse_favorite_category(html: str) -> Optional[str]:
    """Parse favorite category from HTML (category with max volume/activity)"""
    soup = BeautifulSoup(html, 'lxml')
    
    # Try to find category data in JSON/script tags first
    common_categories = [
        'Politics', 'Sports', 'Crypto', 'Economics', 'Entertainment',
        'Science', 'World', 'Technology', 'Business', 'Health', 'News',
        'Culture', 'Gaming', 'Weather', 'Markets'
    ]
    
    for script in soup.find_all('script'):
        script_text = script.string or ''
        # Look for category names in script content
        for cat in common_categories:
            if cat.lower() in script_text.lower():
                # Check if it's in a meaningful context (not just in a URL)
                if 'category' in script_text.lower() or 'tag' in script_text.lower():
                    return cat
    
    # Look for categories section (usually after #categories anchor)
    categories_section = None
    anchor = soup.find('a', {'name': 'categories'}) or soup.find(id='categories')
    if anchor:
        # Find parent container
        categories_section = anchor.find_parent(['div', 'section', 'article'])
        # Also check next siblings
        if not categories_section:
            next_sibling = anchor.find_next_sibling(['div', 'section', 'article'])
            if next_sibling:
                categories_section = next_sibling
    
    if not categories_section:
        # Try to find any section with "category" or "categories" in text
        for elem in soup.find_all(['div', 'section', 'article']):
            text = elem.get_text().lower()
            if 'categor' in text:
                categories_section = elem
                break
    
    if categories_section:
        # Try to find category in a table or list with volume/activity data
        # Look for table rows or list items
        rows = categories_section.find_all(['tr', 'li', 'div'])
        category_with_volume = None
        max_volume = 0
        
        for row in rows:
            text = row.get_text()
            # Look for patterns like "Category Name $123" or "Category Name 45%"
            for cat in common_categories:
                if cat.lower() in text.lower():
                    # Try to extract volume/percentage
                    volume_match = re.search(r'[\$]?([\d,]+\.?\d*)', text)
                    if volume_match:
                        try:
                            volume = float(volume_match.group(1).replace(',', ''))
                            if volume > max_volume:
                                max_volume = volume
                                category_with_volume = cat
                        except ValueError:
                            pass
                    elif not category_with_volume:
                        # If no volume found, use first category as fallback
                        category_with_volume = cat
        
        if category_with_volume:
            return category_with_volume
        
        # Fallback: Look for category names in headings, buttons, or list items
        category_elements = categories_section.find_all(['h1', 'h2', 'h3', 'h4', 'button', 'div', 'span'], 
                                                        class_=re.compile(r'category|tag', re.I))
        
        # If no specific category elements, look for text that looks like category names
        if not category_elements:
            text = categories_section.get_text()
            for cat in common_categories:
                if cat.lower() in text.lower():
                    return cat
        
        # Get the first category found
        for elem in category_elements:
            cat_text = elem.get_text().strip()
            if cat_text and len(cat_text) < 50:  # Reasonable category name length
                # Clean up the text (remove numbers, symbols)
                cat_text = re.sub(r'[\d\$%]+', '', cat_text).strip()
                if cat_text:
                    return cat_text
    
    # Last resort: search entire page for category mentions
    page_text = soup.get_text().lower()
    for cat in common_categories:
        if cat.lower() in page_text and 'category' in page_text:
            return cat
    
    return None


@app.get("/api/trader-stats")
async def get_trader_stats(address: str):
    """
    Fetch trader statistics from Polymarket APIs.
    Returns win rate (30d), all-time PnL, and favorite category.
    Uses data-api.polymarket.com for closed positions data.
    """
    if not address or not address.startswith('0x'):
        raise HTTPException(status_code=400, detail="Invalid address format")
    
    # Check cache
    now_ts = time.time()
    cached = TRADER_STATS_CACHE.get(address.lower())
    if cached and cached.get("expires_at", 0) > now_ts:
        return cached["data"]
    
    try:
        # Fetch closed positions to calculate stats
        async with _create_httpx_client(timeout=15.0) as client:
            # Get closed positions (up to 100 for better accuracy)
            closed_positions_url = f"https://data-api.polymarket.com/closed-positions"
            params = {
                "user": address,
                "sortBy": "realizedpnl",
                "sortDirection": "DESC",
                "limit": 100,
                "offset": 0
            }
            
            response = await client.get(closed_positions_url, params=params)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch closed positions for {address}: {response.status_code}")
                result = {
                    "winRate30d": None,
                    "pnlAllTime": None,
                    "favoriteCategory": None
                }
                TRADER_STATS_CACHE[address.lower()] = {
                    "data": result,
                    "expires_at": now_ts + 300
                }
                return result
            
            positions = response.json()
            if not isinstance(positions, list):
                positions = positions.get('data', []) if isinstance(positions, dict) else []
            
            if not positions:
                result = {
                    "winRate30d": None,
                    "pnlAllTime": None,
                    "favoriteCategory": None
                }
                TRADER_STATS_CACHE[address.lower()] = {
                    "data": result,
                    "expires_at": now_ts + TRADER_STATS_CACHE_TTL_SECONDS
                }
                return result
            
            # Calculate all-time PnL (sum of all realized PnL)
            all_time_pnl = sum(float(pos.get('realizedPnl', 0)) for pos in positions)
            
            # Calculate 30-day win rate
            # IMPORTANT: closed-positions API only returns positions where the market has ended.
            # This means positions closed early by the trader (with losses) may not be included
            # until the market actually ends. This can lead to inflated win rates.
            # We use endDate (market end date) as approximation - if market ended in last 30 days,
            # we consider the position as closed in that period.
            from datetime import datetime, timedelta
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            recent_positions = []
            for pos in positions:
                # Use endDate to approximate when position was closed
                # (market end date is when position gets realized PnL)
                end_date_str = pos.get('endDate')
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        # Only include positions where market ended in last 30 days
                        # and market has already ended (endDate <= now)
                        now = datetime.now(timezone.utc)
                        if end_date >= thirty_days_ago and end_date <= now:
                            recent_positions.append(pos)
                    except (ValueError, AttributeError):
                        # Skip positions with invalid endDate
                        pass
            
            # Calculate win rate from recent positions
            win_rate_30d = None
            if recent_positions:
                wins = sum(1 for pos in recent_positions if float(pos.get('realizedPnl', 0)) > 0)
                losses = sum(1 for pos in recent_positions if float(pos.get('realizedPnl', 0)) < 0)
                total = len(recent_positions)
                if total > 0:
                    win_rate_30d = (wins / total) * 100
                    
                    # If win rate is 100% but we have very few positions, it might be inaccurate
                    # Log a warning for debugging
                    if win_rate_30d == 100.0 and total < 10:
                        logger.debug(f"Win rate 100% for {address} with only {total} positions - may be inaccurate due to API limitations")
            
            # Determine favorite category from positions
            category_counts = {}
            for pos in positions:
                # Try to extract category from icon URL or slug
                icon = pos.get('icon', '')
                slug = pos.get('slug', '')
                
                # Extract category from icon URL (e.g., "nhl.png" -> "Sports")
                category = None
                if 'nhl' in icon.lower() or 'nfl' in icon.lower() or 'nba' in icon.lower() or 'mlb' in icon.lower() or 'soccer' in icon.lower() or 'cfb' in icon.lower():
                    category = 'Sports'
                elif 'crypto' in icon.lower() or 'bitcoin' in icon.lower() or 'ethereum' in icon.lower():
                    category = 'Crypto'
                elif 'politics' in icon.lower() or 'election' in icon.lower() or 'president' in icon.lower():
                    category = 'Politics'
                elif 'economics' in icon.lower() or 'economy' in icon.lower():
                    category = 'Economics'
                elif 'entertainment' in icon.lower():
                    category = 'Entertainment'
                
                # Also check slug
                if not category:
                    if any(sport in slug.lower() for sport in ['nhl', 'nfl', 'nba', 'mlb', 'soccer', 'cfb', 'football', 'basketball', 'hockey']):
                        category = 'Sports'
                    elif any(crypto in slug.lower() for crypto in ['crypto', 'bitcoin', 'btc', 'eth', 'ethereum']):
                        category = 'Crypto'
                    elif any(pol in slug.lower() for pol in ['politics', 'election', 'president', 'trump', 'biden']):
                        category = 'Politics'
                
                if category:
                    category_counts[category] = category_counts.get(category, 0) + 1
            
            favorite_category = None
            if category_counts:
                favorite_category = max(category_counts.items(), key=lambda x: x[1])[0]
            
            result = {
                "winRate30d": round(win_rate_30d, 1) if win_rate_30d is not None else None,
                "pnlAllTime": round(all_time_pnl, 2) if all_time_pnl else None,
                "favoriteCategory": favorite_category
            }
            
            # Cache result
            TRADER_STATS_CACHE[address.lower()] = {
                "data": result,
                "expires_at": now_ts + TRADER_STATS_CACHE_TTL_SECONDS
            }
            
            return result
            
    except httpx.RequestError as e:
        logger.error(f"Request error fetching trader stats for {address}: {e}")
        result = {
            "winRate30d": None,
            "pnlAllTime": None,
            "favoriteCategory": None
        }
        TRADER_STATS_CACHE[address.lower()] = {
            "data": result,
            "expires_at": now_ts + 300
        }
        return result
    except Exception as e:
        logger.error(f"Error fetching trader stats for {address}: {e}")
        result = {
            "winRate30d": None,
            "pnlAllTime": None,
            "favoriteCategory": None
        }
        TRADER_STATS_CACHE[address.lower()] = {
            "data": result,
            "expires_at": now_ts + 300
        }
        return result


@app.get("/api/user/positions")
async def get_user_positions(address: str):
    """
    Get user's current positions for Dashboard.
    Returns positions where user has > 1 share.
    """
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            # Fetch positions from Polymarket data API
            response = await client.get(
                f"https://data-api.polymarket.com/positions?user={address}&sortBy=CURRENT&sortDirection=DESC&sizeThreshold=.1&limit=100&offset=0",
                timeout=15.0
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            positions = data if isinstance(data, list) else data.get('data', [])
            
            # Filter and transform positions
            result = []
            for pos in positions:
                shares = float(pos.get('size', 0))
                if shares < 1:
                    continue
                
                # Get current price from position data
                current_price = float(pos.get('curPrice', pos.get('price', 0)))
                
                result.append({
                    "token_id": pos.get('asset', pos.get('assetId', '')),
                    "condition_id": pos.get('conditionId', ''),
                    "question": pos.get('title', pos.get('question', 'Unknown Market')),
                    "outcome": pos.get('outcome', 'Yes'),
                    "shares": shares,
                    "avg_price": float(pos.get('avgPrice', current_price)),
                    "current_price": current_price,
                    "value_usd": shares * current_price,
                    "pnl": float(pos.get('pnl', 0)),
                    "pnl_percent": float(pos.get('pnlPercent', 0))
                })
            
            return result
            
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {str(e)}")

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

@app.get("/api/auth/clob-message")
async def get_clob_auth_message(address: str):
    """
    Get EIP-712 ClobAuth message for user to sign in MetaMask.
    User signs this to derive their L2 API credentials.
    """
    import time
    
    timestamp = int(time.time())
    nonce = 0
    
    # ClobAuth EIP-712 structure (matching py-clob-client SDK)
    domain = {
        "name": "ClobAuthDomain",
        "version": "1",
        "chainId": str(CHAIN_ID)
    }
    
    types = {
        "ClobAuth": [
            {"name": "address", "type": "address"},
            {"name": "timestamp", "type": "string"},
            {"name": "nonce", "type": "uint256"},
            {"name": "message", "type": "string"}
        ],
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"}
        ]
    }
    
    message = {
        "address": address.lower(),
        "timestamp": str(timestamp),
        "nonce": nonce,
        "message": "This message attests that I control the given wallet"
    }
    
    return {
        "domain": domain,
        "types": types,
        "primaryType": "ClobAuth",
        "message": message,
        "timestamp": timestamp,
        "nonce": nonce
    }


@app.post("/api/auth/derive-api-key")
async def derive_api_key(request: DeriveApiKeyRequest):
    """
    Derive L2 API credentials using user's signature.
    Forwards signature to Polymarket CLOB to get/create API key.
    """
    import httpx
    
    # L1 Headers matching py-clob-client format
    headers = {
        "POLY_ADDRESS": request.address.lower(),
        "POLY_SIGNATURE": request.signature,
        "POLY_TIMESTAMP": str(request.timestamp),
        "POLY_NONCE": str(request.nonce),
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # Try to derive existing key first
            response = await client.get(
                f"{CLOB_HOST}/auth/derive-api-key",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "apiKey": data.get("apiKey"),
                    "apiSecret": data.get("secret"),
                    "passphrase": data.get("passphrase")
                }
            
            # If derive fails, create new key
            response = await client.post(
                f"{CLOB_HOST}/auth/api-key",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "apiKey": data.get("apiKey"),
                    "apiSecret": data.get("secret"),
                    "passphrase": data.get("passphrase")
                }
            else:
                logger.error(f"CLOB auth error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"Failed to derive API key: {response.text}"
                )
                
    except httpx.RequestError as e:
        logger.error(f"CLOB request error: {e}")
        raise HTTPException(status_code=500, detail=f"Connection error: {str(e)}")

# Trading Endpoints
@app.get("/api/trade/status")
async def trade_status():
    """Check if trading service is ready"""
    return {"ready": trading_service.is_ready()}

@app.get("/api/trade/price")
async def get_token_price(token_id: str):
    """Get current price for a token"""
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    prices = trading_service.get_price(token_id)
    if not prices:
        raise HTTPException(status_code=404, detail="Could not get price")
    return prices


@app.get("/api/trade/best-price")
async def get_best_price(token_id: str, side: str = "BUY"):
    """
    Get best orderbook price for immediate execution.
    For BUY: returns best ask (lowest sell price)
    For SELL: returns best bid (highest buy price)
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    if side.upper() == "BUY":
        price = trading_service.get_best_ask(token_id)
    else:
        price = trading_service.get_best_bid(token_id)
    
    if not price:
        raise HTTPException(status_code=404, detail="No liquidity in orderbook")
    
    return {"price": price, "side": side.upper()}


@app.get("/api/trade/orderbook-depth")
async def get_orderbook_depth(token_id: str, side: str = "BUY", amount: float = 100.0):
    """
    Calculate VWAP and required price for a given order size.
    Returns average fill price, worst price level, and liquidity info.
    
    Use this to show accurate estimated price for large orders that span multiple levels.
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    
    result = trading_service.calculate_vwap(token_id, side, amount)
    
    if not result:
        raise HTTPException(status_code=404, detail="Could not calculate VWAP - no orderbook data")
    
    return result


# ============ USER WALLET TRADING ENDPOINTS ============

@app.post("/api/trade/prepare-order")
async def prepare_order(request: PrepareOrderRequest):
    """
    Prepare an unsigned EIP-712 order for MetaMask signing.
    
    Security validations:
    - Price within 10% of market price
    - Order value <= $100
    - Minimum order $1
    
    Returns EIP-712 {domain, types, message} structure
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    try:
        order_data = trading_service.prepare_order_for_user(
            user_address=request.user_address,
            proxy_address=request.proxy_address,
            token_id=request.token_id,
            price=request.price,
            size=request.size,
            side=request.side,
            order_type=request.order_type
        )
        return order_data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Prepare order error: {e}")
        raise HTTPException(status_code=500, detail="Failed to prepare order")


@app.post("/api/trade/submit-order")
async def submit_order(request: SubmitOrderRequest):
    """
    Submit a signed order to Polymarket CLOB.
    
    The order must have been signed by user's MetaMask wallet.
    Uses user's L2 credentials for authentication.
    Returns order ID on success.
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    try:
        result = trading_service.submit_user_order(
            signed_order=request.signed_order,
            user_api_key=request.user_api_key,
            user_api_secret=request.user_api_secret,
            user_passphrase=request.user_passphrase,
            order_type=request.order_type
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Submit order error: {e}")
        raise HTTPException(status_code=500, detail=f"Order submission failed: {str(e)}")


@app.post("/api/trade/open-orders")
async def get_open_orders(request: GetOrdersRequest):
    """
    Get user's open orders from CLOB.
    Returns list of pending limit orders.
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    try:
        orders = trading_service.get_open_orders(
            user_address=request.user_address,
            user_api_key=request.user_api_key,
            user_api_secret=request.user_api_secret,
            user_passphrase=request.user_passphrase
        )
        return {"orders": orders}
    except Exception as e:
        logger.error(f"Get orders error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trade/cancel-order")
async def cancel_order_endpoint(request: CancelOrderRequest):
    """
    Cancel an open limit order.
    """
    if not trading_service.is_ready():
        raise HTTPException(status_code=503, detail="Trading service not ready")
    
    try:
        result = trading_service.cancel_order(
            order_id=request.order_id,
            user_address=request.user_address,
            user_api_key=request.user_api_key,
            user_api_secret=request.user_api_secret,
            user_passphrase=request.user_passphrase
        )
        return {"success": True, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Cancel order error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Legacy endpoint (deprecated - use prepare-order + submit-order for user wallets)
@app.post("/api/trade/buy")
async def place_buy_order(request: TradeRequest):
    """Place a market buy order (DEPRECATED)"""
    raise HTTPException(
        status_code=410, 
        detail="Deprecated. Use /api/trade/prepare-order + /api/trade/submit-order"
    )

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages if any (e.g. ping)
            data = await websocket.receive_text()
            # We can handle client messages here if needed
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

