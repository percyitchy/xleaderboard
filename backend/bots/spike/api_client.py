"""API Client for Spike Detector"""
import aiohttp
import json
import asyncio
import logging
import itertools
import random
from aiohttp_socks import ProxyConnector
from .config import API_URLS, USER_AGENTS, PROXIES

# Cycle through user agents for each request
user_agent_cycle = itertools.cycle(USER_AGENTS)


import traceback

async def fetch_with_retry(sessions, url, max_retries=6):
    """
    Fetches URL using a random session from the pool.
    """
    for attempt in range(max_retries):
        # Pick a random session from the pool
        if not sessions:
            logging.error("No sessions available")
            return None
            
        session = random.choice(sessions)
        
        headers = {
            'User-Agent': next(user_agent_cycle),
            'Accept-Encoding': 'gzip, deflate, br'
        }
        
        try:
            # Reduced timeout to 15s (was 30s) to fail faster on bad proxies
            # Proxy is already bound to the session, so we don't pass it here
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            # Reduced backoff: 1s, 2s, 4s...
            wait_time = min(10, 1 * (2 ** attempt))
            # logging.warning(f"API error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"Failed to fetch {url} after {max_retries} attempts.")
                return None
    return None

async def fetch_page_worker(sessions, offset_iterator, markets_list, stop_event, limit):
    while not stop_event.is_set():
        # Get next offset
        try:
            offset = next(offset_iterator)
        except StopIteration:
            break
            
        if stop_event.is_set():
            break

        url = f"{API_URLS}?limit={limit}&offset={offset}&closed=false"
        data = await fetch_with_retry(sessions, url)

        if not data:
            # If data is empty or None (failed), we assume end of list or critical failure.
            if data == []:
                stop_event.set()
            elif data is None:
                # Error case.
                pass
            continue

        # Process data
        for event in data:
            event_slug = event.get('slug')
            for market in event.get('markets', []):
                try:
                    # Parse JSON strings in fields
                    outcomes = json.loads(market.get('outcomes', '[]'))
                    outcome_prices = json.loads(market.get('outcomePrices', '[]'))
                    clob_token_ids = json.loads(market.get('clobTokenIds', '[]'))

                    market_dict = {
                        'id': market.get('id'),
                        'question': market.get('question'),
                        'slug': market.get('slug'),
                        'event_slug': event_slug,
                        'conditionId': market.get('conditionId'),
                        'outcomes': outcomes,
                        'prices': [float(p) for p in outcome_prices],
                        'asset_ids': clob_token_ids,
                        'volume': market.get('volume'),
                        'liquidity': market.get('liquidity'),
                        'endDate': market.get('endDate')
                    }
                    markets_list.append(market_dict)
                except Exception:
                    continue

async def fetch_all_markets():
    markets = []
    limit = 100
    concurrency = 20 # Fetch 20 pages in parallel
    
    # Iterator for offsets: 0, 100, 200, ...
    offset_iterator = itertools.count(0, limit)
    stop_event = asyncio.Event()
    
    # Create session pool
    sessions = []
    
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
        sessions.append(session)
    
    if not sessions:
        # Fallback if no proxies
        sessions.append(aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)))

    try:
        tasks = []
        for _ in range(concurrency):
            task = asyncio.create_task(fetch_page_worker(sessions, offset_iterator, markets, stop_event, limit))
            tasks.append(task)
        
        await asyncio.gather(*tasks)
    finally:
        for session in sessions:
            await session.close()

    logging.info(f"Loaded {len(markets)} markets")
    return markets
