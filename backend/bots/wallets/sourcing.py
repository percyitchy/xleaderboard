import aiohttp
import asyncio
import random
import time
import logging
from aiohttp_socks import ProxyConnector
from .config import SOURCING_URL, SOURCING_CATEGORIES, WALLETS_PER_CATEGORY, SOURCING_CRITERIA_BASE, USER_AGENTS, PROXIES

logger = logging.getLogger("wallets_bot")

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip, deflate, br"
    }

async def fetch_traders_by_category(session, category):
    """
    Fetch traders for a specific category using the provided session.
    Returns list of trader dictionaries with category field added.
    """
    # Determine limit for this category
    if isinstance(WALLETS_PER_CATEGORY, dict):
        base_limit = WALLETS_PER_CATEGORY.get(category, WALLETS_PER_CATEGORY.get("default", 500))
    else:
        base_limit = int(WALLETS_PER_CATEGORY)
        
    logger.info(f"[*] Fetching {base_limit} traders for category '{category}'...")

    criteria = SOURCING_CRITERIA_BASE.copy()
    criteria["tag"] = category

    max_retries = 4
    # Retry limits sequence: 1st retry -> 499, 2nd -> 400, 3rd -> 300, 4th -> 300
    retry_limits = [499, 400, 300, 300]

    for attempt in range(max_retries + 1):
        # Determine limit for this attempt
        if attempt == 0:
            current_limit = base_limit
        else:
            # Use requested retry limit, but don't exceed base config
            current_limit = min(base_limit, retry_limits[attempt - 1])
            
        criteria["limit"] = current_limit
        
        try:
            headers = get_random_headers()
            
            # Proxy is already handled by the session's connector
            async with session.post(
                SOURCING_URL,
                json=criteria,
                headers=headers,
                timeout=30,
                ssl=False
            ) as response:

                if response.status == 200:
                    data = await response.json()
                    # Handle response format: list or dict with 'data' key
                    if isinstance(data, dict) and "data" in data:
                        data = data["data"]

                    traders = []
                    if isinstance(data, list):
                        for item in data:
                            if "trader" in item:
                                # Add category to trader data
                                trader_data = item.copy()
                                trader_data["category"] = category
                                traders.append(trader_data)

                    # Limit per category
                    traders = traders[:current_limit]

                    logger.info(f"[+] Successfully sourced {len(traders)} traders for category '{category}' (limit={current_limit}).")
                    return traders
                else:
                    logger.warning(f"[-] Attempt {attempt+1}/{max_retries+1} failed for '{category}' (limit={current_limit}). Status Code: {response.status}")
                    # logger.error(f"[-] Response: {await response.text()}")

        except Exception as e:
            logger.warning(f"[-] Attempt {attempt+1}/{max_retries+1} error fetching traders for '{category}' (limit={current_limit}): {e}")
        
        if attempt < max_retries:
            await asyncio.sleep(2)

    logger.error(f"[-] Failed to fetch traders for '{category}' after {max_retries+1} attempts.")
    return []

async def fetch_top_traders():
    """
    Fetches the top traders from all categories defined in SOURCING_CATEGORIES.
    Returns a list of trader dictionaries (full data with category field).
    """
    logger.info(f"[*] Sourcing top traders from all categories: {SOURCING_CATEGORIES}")
    logger.info(f"[*] Limits configuration: {WALLETS_PER_CATEGORY}")

    all_traders = []
    
    # Create a local session pool for sourcing
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
         sessions.append(aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)))

    try:
        for category in SOURCING_CATEGORIES:
            # Pick a random session for each category request
            session = random.choice(sessions)
            traders = await fetch_traders_by_category(session, category)
            all_traders.extend(traders)
            await asyncio.sleep(1)  # Small delay between category requests
    finally:
        for session in sessions:
            await session.close()

    total_count = len(all_traders)
    logger.info(f"[+] Successfully sourced {total_count} top traders across all categories.")

    # Show breakdown by category
    category_breakdown = {}
    for trader in all_traders:
        cat = trader.get("category", "Unknown")
        category_breakdown[cat] = category_breakdown.get(cat, 0) + 1

    for cat, count in category_breakdown.items():
        logger.info(f"  - {cat}: {count} traders")

    return all_traders

if __name__ == "__main__":
    # Configure logging for standalone run
    logging.basicConfig(level=logging.INFO)
    # Test the function
    traders = asyncio.run(fetch_top_traders())
    print(f"\nSample traders: {traders[:3] if traders else 'None'}")
