import asyncio
import aiohttp
import time
import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone
import random

from . import utils
from .config import (
    DATA_API_BASE,
    LEADERBOARD_URL,
    GRAPHQL_URL,
    DELAY_BETWEEN_REQUESTS,
    DELAY_AFTER_429,
    MIN_HOLDER_BALANCE,
    DELAY_BETWEEN_BATCHES,
    ADAPTIVE_BACKOFF_MULTIPLIER
)


@utils.retry_async(retries=5, delay=1.0, backoff=1.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_traded_count(sessions: List[aiohttp.ClientSession], wallet_address: str) -> Optional[int]:
    """Fetches traded count for wallet."""
    session_idx = random.randint(0, len(sessions) - 1)
    session = sessions[session_idx]
    # Proxy is already bound to session
    traded_url = f"{DATA_API_BASE}/traded"
    params = {'user': wallet_address}

    async with session.get(traded_url, params=params, ssl=False) as response:
        if response.status == 429:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Rate limit exceeded",
                headers=response.headers,
            )
        response.raise_for_status()
        data = await response.json()
    
    return data.get('traded', 0)


@utils.retry_async(retries=5, delay=1.0, backoff=1.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_volume(sessions: List[aiohttp.ClientSession], wallet_address: str) -> Optional[float]:
    """Fetches trading volume for wallet."""
    session_idx = random.randint(0, len(sessions) - 1)
    session = sessions[session_idx]
    # Proxy is already bound to session
    leaderboard_params = {
        'timePeriod': 'all',
        'orderBy': 'VOL',
        'limit': 1,
        'offset': 0,
        'category': 'overall',
        'user': wallet_address
    }

    async with session.get(LEADERBOARD_URL, params=leaderboard_params, ssl=False) as response:
        if response.status == 429:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Rate limit exceeded",
                headers=response.headers,
            )
        response.raise_for_status()
        leaderboard_data = await response.json()
    
    if leaderboard_data and len(leaderboard_data) > 0:
        return float(leaderboard_data[0].get('vol', 0))
    return 0.0


@utils.retry_async(retries=5, delay=1.0, backoff=1.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_wallet_age(sessions: List[aiohttp.ClientSession], wallet_address: str) -> Optional[int]:
    """Fetches wallet age in days."""
    session_idx = random.randint(0, len(sessions) - 1)
    session = sessions[session_idx]
    # Proxy is already bound to session
    activity_url = f"{DATA_API_BASE}/activity"
    params = {
        'user': wallet_address,
        'type': 'TRADE',
        'sortDirection': 'ASC',
        'limit': 1
    }

    async with session.get(activity_url, params=params, ssl=False) as response:
        if response.status == 429:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Rate limit exceeded",
                headers=response.headers,
            )
        response.raise_for_status()
        trades = await response.json()
    
    if trades and len(trades) > 0:
        first_trade_timestamp = trades[0].get('timestamp')
        if first_trade_timestamp:
            current_timestamp = int(time.time())
            age_seconds = current_timestamp - first_trade_timestamp
            return int(age_seconds / (60 * 60 * 24))
    return None


@utils.retry_async(retries=5, delay=1.0, backoff=1.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_wallet_stats(sessions: List[aiohttp.ClientSession], wallet_address: str) -> Tuple[Optional[int], Optional[float], Optional[int]]:
    """Асинхронно получает статистику кошелька параллельно."""
    tasks = [
        fetch_traded_count(sessions, wallet_address),
        fetch_volume(sessions, wallet_address),
        fetch_wallet_age(sessions, wallet_address)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    traded_count = 0
    if not isinstance(results[0], Exception):
        traded_count = results[0] or 0
    
    vol = 0.0
    if not isinstance(results[1], Exception):
        vol = results[1] or 0.0
    
    wallet_age_days = None
    if not isinstance(results[2], Exception):
        wallet_age_days = results[2]
    
    await asyncio.sleep(0.3)  # Increased delay to mitigate rate limits
    
    return traded_count, vol, wallet_age_days


@utils.retry_async(retries=3, delay=2, backoff=2, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_holders_for_asset(
    session: aiohttp.ClientSession,
    asset_id: str,
    min_balance: float = MIN_HOLDER_BALANCE,
    limit: int = 300
) -> Dict[str, float]:
    """Асинхронно получает холдеров с использованием retry-механизма."""
    if not asset_id:
        return {}

    min_balance_raw = str(int(min_balance * 1000000))
    
    query = """
    query GetHolders {
      userBalances(
        first: %d
        skip: 0
        where: {
          balance_gt: "%s"
          asset_in: ["%s"]
        }
        orderBy: balance
        orderDirection: desc
      ) {
        user
        balance
        asset {
          id
        }
      }
    }
    """ % (limit, min_balance_raw, asset_id)
    
    payload = {"query": query}
    
    # Proxy is already bound to session
    async with session.post(GRAPHQL_URL, json=payload, ssl=False) as response:
        if response.status == 429:
            # Для ошибки 429 (Too Many Requests) вызываем исключение, чтобы retry-декоратор сработал
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Rate limit exceeded",
                headers=response.headers,
            )
        
        response.raise_for_status()
        data = await response.json()
    
    await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
    
    if "data" in data and "userBalances" in data["data"]:
        holders = {}
        for balance_data in data["data"]["userBalances"]:
            user_address = balance_data["user"]
            asset_obj = balance_data.get("asset")
            if not asset_obj or asset_obj.get("id") != asset_id:
                continue  # Skip mismatch
            balance_raw = float(balance_data["balance"])
            balance_shares = round(balance_raw / 1000000, 2)
            if user_address not in holders:
                holders[user_address] = balance_shares
        
        return holders
    
    # Если 'data' или 'userBalances' отсутствуют, это может быть ошибка GraphQL
    # Логируем это, но возвращаем пустой словарь, т.к. это не сетевая ошибка
    if "errors" in data:
        print(f"GraphQL error for asset {asset_id}: {data['errors']}")

    return {}


@utils.retry_async(retries=3, delay=0.5, backoff=1.5, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_holders_for_assets(
    sessions: List[aiohttp.ClientSession],
    asset_ids: List[str],
    min_balance: float = MIN_HOLDER_BALANCE,
    batch_size: int = 30,  # Increased for efficiency
    limit: int = 300
) -> Dict[str, Dict[str, float]]:
    """Batches GraphQL queries for multiple assets to fetch holders efficiently."""
    if not asset_ids:
        return {}
    
    results = {}
    for i in range(0, len(asset_ids), batch_size):
        batch = asset_ids[i:i + batch_size]
        min_balance_raw = str(int(min_balance * 1000000))
        
        assets_str = '", "'.join(batch)
        query = """
        query GetHoldersBatch {
          userBalances(
            first: %d
            skip: 0
            where: {
              balance_gt: "%s"
              asset_in: ["%s"]
            }
            orderBy: balance
            orderDirection: desc
          ) {
            user
            balance
            asset {
              id
            }
          }
        }
        """ % (limit, min_balance_raw, assets_str)
        
        payload = {"query": query}
        
        session_idx = random.randint(0, len(sessions) - 1)
        session = sessions[session_idx]
        # Proxy is already bound to session
        async with session.post(GRAPHQL_URL, json=payload, ssl=False) as response:
            if response.status == 429:
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message="Rate limit exceeded",
                    headers=response.headers,
                )
            
            response.raise_for_status()
            data = await response.json()
        
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
        
        if "data" in data and "userBalances" in data["data"]:
            for balance_data in data["data"]["userBalances"]:
                user_address = balance_data["user"]
                asset_obj = balance_data.get("asset")
                if not asset_obj or "id" not in asset_obj:
                    print(f"Warning: Invalid asset for user {user_address[:10]}...")
                    continue
                asset_id = asset_obj["id"]
                balance_raw = float(balance_data["balance"])
                balance_shares = round(balance_raw / 1000000, 2)
                
                if asset_id not in results:
                    results[asset_id] = {}
                if user_address not in results[asset_id]:  # Avoid duplicates
                    results[asset_id][user_address] = balance_shares
        
        if "errors" in data:
            print(f"GraphQL error for batch {i//batch_size + 1}: {data['errors']}")
        else:
            print(f"Batch {i//batch_size + 1}: {len(batch)} assets, processed {len(data['data']['userBalances'])} balances")
    
    return results


@utils.retry_async(retries=3, delay=1.0, backoff=2.0, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_closed_positions(wallet: str, sessions: List[aiohttp.ClientSession], semaphore: asyncio.Semaphore) -> List[float]:
    """Fetch closed positions with sequential offset calls to avoid rate limits."""
    offsets = [0, 25, 50]
    all_positions = []

    for offset in offsets:
        # Don't use semaphore here - it's controlled at higher level
        url = f"https://data-api.polymarket.com/closed-positions?user={wallet}&sortBy=realizedpnl&sortDirection=DESC&limit=25&offset={offset}"
        session_idx = random.randint(0, len(sessions) - 1)
        session = sessions[session_idx]
        # Proxy is already bound to session
        async with session.get(url, ssl=False) as response:
            if response.status == 429:
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message="Rate limit exceeded",
                    headers=response.headers,
                )
            response.raise_for_status()
            data = await response.json()

            # Handle response - it should be a list directly
            if isinstance(data, list):
                positions = [float(pos.get('totalBought', 0)) for pos in data if isinstance(pos, dict)]
            else:
                # Some APIs return {data: [...]}
                positions = data.get('data', []) if isinstance(data, dict) else []
                positions = [float(pos.get('totalBought', 0)) for pos in positions if isinstance(pos, dict)]

            all_positions.extend(positions)

        # Add delay between offset requests to reduce rate limiting
        await asyncio.sleep(0.15)

    return all_positions


@utils.retry_async(retries=3, delay=1.0, backoff=2.0, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_open_positions(wallet: str, sessions: List[aiohttp.ClientSession], semaphore: asyncio.Semaphore) -> Dict[str, float]:
    """Fetch open positions and return dict of asset_id -> initialValue."""
    # Don't use semaphore here - it's controlled at higher level
    url = f"https://data-api.polymarket.com/positions?user={wallet}&sortBy=CURRENT&sortDirection=DESC&sizeThreshold=.1&limit=50&offset=0"
    session_idx = random.randint(0, len(sessions) - 1)
    session = sessions[session_idx]
    # Proxy is already bound to session
    async with session.get(url, ssl=False) as response:
        if response.status == 429:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message="Rate limit exceeded",
                headers=response.headers,
            )
        response.raise_for_status()
        data = await response.json()
        
        # Handle response - it should be a list directly
        positions = data if isinstance(data, list) else data.get('data', [])
        if isinstance(positions, list):
            return {pos.get('asset', pos.get('asset_id', '')): float(pos.get('initialValue', 0)) 
                    for pos in positions if isinstance(pos, dict)}
        return {}
