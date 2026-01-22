import asyncio
import aiohttp
import time
import json
import statistics
import logging
from typing import Dict, List, Set, Any
from datetime import datetime, timezone
import urllib3
import random
from itertools import cycle
from aiohttp_socks import ProxyConnector

from . import utils
from .config import (
    API_BASE_URL,
    API_LIMIT,
    REQUEST_TIMEOUT,
    MAX_CONCURRENT_WALLETS,
    MAX_CONCURRENT_STATS,
    MAX_CONCURRENT_INITIAL,
    MAX_CONCURRENT_DETAILED,
    MAX_CONCURRENT_CLOSED_POSITIONS,
    DELAY_BETWEEN_BATCHES,
    MIN_VOLUME,
    MAX_OUTCOME_PRICE,
    MIN_OUTCOME_PRICE,
    OUTPUT_FILE,
    MAX_TRADES,
    MAX_VOL,
    MIN_WALLET_AGE_DAYS,
    MIN_HOLDERS_COUNT,
    MIN_USD_VALUE,
    PROXIES,
    USER_AGENTS,
    MARKET_WHITELIST,
    WHITELIST_ONLY
)

from .processors import (
    process_single_market
)

from .api_client import fetch_holders_for_assets, get_wallet_stats, fetch_closed_positions, fetch_open_positions
from backend.services.signal_store import SignalStore

# Configure logging
logger = logging.getLogger("fetcher")

def extract_asset_ids(market: dict) -> tuple:
    """Extracts both YES and NO asset IDs from market data.
    Returns: (yes_asset_id, no_asset_id)
    """
    try:
        if "clobTokenIds" in market:
            clob_token_ids_str = market["clobTokenIds"]
            clob_token_ids = json.loads(clob_token_ids_str)
            yes_id = clob_token_ids[0] if len(clob_token_ids) > 0 else ""
            no_id = clob_token_ids[1] if len(clob_token_ids) > 1 else ""
            return (yes_id, no_id)
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return ("", "")


def collect_unique_wallets(filtered_markets: list) -> Set[str]:
    """Extract all unique wallet addresses from filtered markets."""
    unique_wallets = set()
    for market in filtered_markets:
        holders = market.get('holders', [])
        for holder in holders:
            wallet_address = holder.get('address')
            if wallet_address:
                unique_wallets.add(wallet_address)
    
    logger.info(f"Collected {len(unique_wallets)} unique wallet addresses")
    return unique_wallets


async def fetch_all_wallet_stats(unique_wallets: Set[str], sessions: List[aiohttp.ClientSession]) -> Dict[str, tuple]:
    """Fetch stats for all unique wallets in parallel."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_INITIAL)

    async def fetch_with_semaphore(wallet: str):
        async with semaphore:
            stats = await get_wallet_stats(sessions, wallet)
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)
            return wallet, stats
    
    logger.info(f"Fetching stats for {len(unique_wallets)} wallets...")
    start_time = time.time()
    
    results = await asyncio.gather(*[fetch_with_semaphore(w) for w in unique_wallets])
    wallet_stats = {wallet: stats for wallet, stats in results}
    
    elapsed = time.time() - start_time
    logger.info(f"Fetched stats in {elapsed:.2f}s")
    return wallet_stats


def filter_wallets_by_criteria(wallet_stats: Dict[str, tuple]) -> tuple[Set[str], Set[str], Set[str]]:
    """Filter wallets into: to_remove, flagged_basic, median_candidates."""
    to_remove = set()  # trades > 100 AND volume > 1M
    flagged_new = set()  # age < 30
    flagged_fresh = set()  # trades <= 5
    median_candidates = set()  # остальные (для проверки median)
    
    for wallet, stats in wallet_stats.items():
        trades_count = stats[0] if len(stats) > 0 else 0
        total_volume = stats[1] if len(stats) > 1 else 0
        wallet_age = stats[2] if len(stats) > 2 else None
        
        # 1. Remove qualified wallets
        if trades_count > 100 and total_volume > 1_000_000:
            to_remove.add(wallet)
            continue
        
        # 2. Flag new (Age < 30)
        if wallet_age is not None and wallet_age < 30:
            flagged_new.add(wallet)
            continue
            
        # 3. Flag fresh (Trades <= 5)
        if trades_count is not None and trades_count <= 5:
            flagged_fresh.add(wallet)
            continue
        
        # 4. Rest are candidates for median check
        median_candidates.add(wallet)
    
    logger.info(f"To remove: {len(to_remove)}, Flagged new: {len(flagged_new)}, Flagged fresh: {len(flagged_fresh)}, Median candidates: {len(median_candidates)}")
    return to_remove, flagged_new, flagged_fresh, median_candidates


async def fetch_detailed_positions(qualified_wallets: Set[str], sessions: List[aiohttp.ClientSession]) -> Dict[str, dict]:
    """Fetch closed and open positions for qualified wallets."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLOSED_POSITIONS)

    async def fetch_wallet_details(wallet: str):
        async with semaphore:
            closed_sizes = await fetch_closed_positions(wallet, sessions, semaphore)
            open_positions = await fetch_open_positions(wallet, sessions, semaphore)
            return wallet, {'closed_sizes': closed_sizes, 'open_positions': open_positions}
    
    logger.info(f"Fetching detailed positions for {len(qualified_wallets)} qualified wallets...")
    start_time = time.time()
    
    results = await asyncio.gather(*[fetch_wallet_details(w) for w in qualified_wallets])
    detailed_cache = {wallet: details for wallet, details in results}
    
    elapsed = time.time() - start_time
    logger.info(f"Fetched detailed positions in {elapsed:.2f}s")
    return detailed_cache


def compute_medians(detailed_cache: Dict[str, dict]) -> Dict[str, dict]:
    """Compute median trade size for each qualified wallet."""
    qualified_cache = {}
    
    for wallet, details in detailed_cache.items():
        closed_sizes = details.get('closed_sizes', [])
        
        if closed_sizes:
            median = statistics.median(closed_sizes)
        else:
            median = 0.0  # Default for wallets with no closed positions
        
        qualified_cache[wallet] = {
            'median': median,
            'open_positions': details.get('open_positions', {})
        }
    
    logger.info(f"Computed medians for {len(qualified_cache)} qualified wallets")
    return qualified_cache


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@utils.retry_async(retries=3, delay=1, backoff=2, exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_market_page(session: aiohttp.ClientSession, offset: int, limit: int) -> List[Dict[str, Any]]:
    """Fetches a single page of markets with retry logic."""
    params = {
        "closed": "false",
        "active": "true",
        "limit": limit,
        "offset": offset
    }
    print(f"📡 Запрос рынков: offset={offset}...")
    # Proxy is already bound to session
    async with session.get(API_BASE_URL, params=params, ssl=False) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_filtered_markets(
    sessions: List[aiohttp.ClientSession],
    min_volume: float = MIN_VOLUME,
    max_outcome_price: float = MAX_OUTCOME_PRICE,
    min_outcome_price: float = MIN_OUTCOME_PRICE
) -> List[Dict[str, Any]]:
    """Phase 1: Fetch and filter markets with holders"""
    
    logger.info("=" * 70)
    logger.info("Starting Polymarket Fetcher with optimizations")
    logger.info(f"Concurrency: Initial={MAX_CONCURRENT_INITIAL}, Detailed={MAX_CONCURRENT_DETAILED}")
    logger.info(f"Filters: trades≤{MAX_TRADES}, vol≤${MAX_VOL:,.0f}, age≥{MIN_WALLET_AGE_DAYS}d")
    logger.info("=" * 70)
    
    # Fetch and filter markets with pagination on-the-fly
    filtered_markets = []
    current_date = datetime.now(timezone.utc)
    offset = 0
    
    while True:
        try:
            session_idx = random.randint(0, len(sessions) - 1)
            session = sessions[session_idx]
            markets = await fetch_market_page(session, offset, API_LIMIT)
        except Exception as e:
            logger.error(f"Failed to load markets page (offset={offset}) after retries. Error: {e}")
            break

        if not markets:
            logger.info("Reached end of data.")
            break
        
        page_filtered = 0
        for market in markets:
            try:
                # Use market slug
                # market['slug'] is already in the market object
                
                # Check for floor price (Low Probability)
                # ... rest of logic ...
                price_yes = 0
                price_no = 0
                
                # Handle outcomePrices which might be string or list
                if "outcomePrices" in market:
                    op = market["outcomePrices"]
                    outcome_prices = json.loads(op) if isinstance(op, str) else op
                    if outcome_prices:
                         price_yes = float(outcome_prices[0])
                         price_no = float(outcome_prices[1]) if len(outcome_prices) > 1 else 1 - price_yes

                volume = float(market.get("volume", 0))
                
                # Check for floor price (Low Probability)
                # User requested: "equal 0.001". Using <= 0.001 to catch tiny prices.
                is_floor_price = False
                if price_yes <= 0.001 or price_no <= 0.001:
                    is_floor_price = True
                
                # Apply limits only if NOT floor price
                if not is_floor_price:
                    if volume <= min_volume:
                        continue
                    
                    # Filter by YES price (primary outcome)
                    if price_yes <= min_outcome_price or price_yes >= max_outcome_price:
                        continue
                
                end_date_str = market.get("endDate", "")
                if end_date_str:
                    end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    if end_date < current_date:
                        continue
                else:
                    continue

                filtered_markets.append(market)
                # Store both outcome prices
                market['_price_yes'] = price_yes
                market['_price_no'] = price_no
                market['_price'] = price_yes  # Keep for backward compat
                market['is_floor_price'] = is_floor_price # Flag for processing
                
                # Parse outcome names
                outcomes_raw = market.get('outcomes', '[]')
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                market['_outcome_yes'] = outcomes[0] if len(outcomes) > 0 else 'Yes'
                market['_outcome_no'] = outcomes[1] if len(outcomes) > 1 else 'No'
                market['_outcome'] = market['_outcome_yes']  # Keep for backward compat
                page_filtered += 1
                
            except Exception as e:
                # logger.debug(f"Skipping market due to error: {e}")
                continue
        
        logger.debug(f"Page: {len(markets)} markets, filtered: {page_filtered} (total: {len(filtered_markets)})")
        
        if len(markets) < API_LIMIT:
            logger.info("Last page received.")
            break
        
        offset += API_LIMIT
        await asyncio.sleep(0.1)
    
    logger.info(f"Found {len(filtered_markets)} markets matching criteria")
    
    # Extract event_slug for all filtered markets
    for market in filtered_markets:
        event_slug = ""
        try:
            if "events" in market:
                events = market["events"]
                if isinstance(events, list) and len(events) > 0:
                    event_slug = events[0].get("slug", "")
        except Exception:
            pass
        market['_event_slug'] = event_slug
    
    # Fetch holders using batch GraphQL - Sequential: YES first, then NO
    # Fetch holders using batch GraphQL - Sequential: YES first, then NO
    logger.info("Fetching YES outcome holders...")
    
    # Phase 1a: YES outcome holders - Split into Normal (300) and Floor (20)
    normal_markets = [m for m in filtered_markets if not m.get('is_floor_price', False)]
    floor_markets = [m for m in filtered_markets if m.get('is_floor_price', False)]
    
    # YES - Normal
    yes_ids_normal = [extract_asset_ids(m)[0] for m in normal_markets if extract_asset_ids(m)[0]]
    yes_results_normal = await fetch_holders_for_assets(sessions, yes_ids_normal, limit=300)
    
    # YES - Floor (Limit 20)
    yes_ids_floor = [extract_asset_ids(m)[0] for m in floor_markets if extract_asset_ids(m)[0]]
    if yes_ids_floor:
        logger.info(f"Fetching Top 20 holders for {len(yes_ids_floor)} low-prob markets (YES) with batch_size=5...")
    yes_results_floor = await fetch_holders_for_assets(sessions, yes_ids_floor, limit=20, batch_size=5)
    
    # Merge YES results
    yes_holders_results = {**yes_results_normal, **yes_results_floor}

    logger.info("Fetching NO outcome holders...")
    
    # Phase 1b: NO outcome holders - Split into Normal (300) and Floor (20)
    # NO - Normal
    no_ids_normal = [extract_asset_ids(m)[1] for m in normal_markets if extract_asset_ids(m)[1]]
    no_results_normal = await fetch_holders_for_assets(sessions, no_ids_normal, limit=300)
    
    # NO - Floor (Limit 20)
    no_ids_floor = [extract_asset_ids(m)[1] for m in floor_markets if extract_asset_ids(m)[1]]
    if no_ids_floor:
        logger.info(f"Fetching Top 20 holders for {len(no_ids_floor)} low-prob markets (NO) with batch_size=5...")
    no_results_floor = await fetch_holders_for_assets(sessions, no_ids_floor, limit=20, batch_size=5)
    
    # Merge NO results
    no_holders_results = {**no_results_normal, **no_results_floor}
    
    market_holders = {}
    skipped_count = 0
    
    for market in filtered_markets:
        yes_id, no_id = extract_asset_ids(market)
        price_yes = market.get('_price_yes', 0)
        price_no = market.get('_price_no', 0)
        
        # Process YES holders
        yes_holders = yes_holders_results.get(yes_id, {})
        valid_yes_holders = {}
        for wallet, balance in yes_holders.items():
            usd_value = balance * price_yes
            # Bypass MIN_USD_VALUE for floor markets
            if market.get('is_floor_price', False) or usd_value >= MIN_USD_VALUE:
                valid_yes_holders[wallet] = balance
        
        # Process NO holders
        no_holders = no_holders_results.get(no_id, {})
        valid_no_holders = {}
        for wallet, balance in no_holders.items():
            usd_value = balance * price_no
            # Bypass MIN_USD_VALUE for floor markets
            if market.get('is_floor_price', False) or usd_value >= MIN_USD_VALUE:
                valid_no_holders[wallet] = balance
        
        # Skip if neither has enough holders
        total_holders = len(valid_yes_holders) + len(valid_no_holders)
        # Skip if neither has enough holders (Unless floor price)
        total_holders = len(valid_yes_holders) + len(valid_no_holders)
        if not market.get('is_floor_price', False) and total_holders < MIN_HOLDERS_COUNT:
            logger.debug(f"Market {market.get('conditionId', '')[:10]}... skipped: {total_holders} total holders")
            skipped_count += 1
            continue
            
        condition_id = market["conditionId"]
        
        # Store both YES and NO holders separately
        market['holders_yes'] = [{'address': w, 'balance': b} for w, b in valid_yes_holders.items()]
        market['holders_no'] = [{'address': w, 'balance': b} for w, b in valid_no_holders.items()]
        market['holders'] = market['holders_yes']  # Keep for backward compat
        market['assetID_yes'] = yes_id
        market['assetID_no'] = no_id
        market_holders[condition_id] = {'yes': valid_yes_holders, 'no': valid_no_holders}
    
    logger.info(f"Found {len(market_holders)} markets with sufficient holders (skipped {skipped_count})")
    
    return filtered_markets


async def fetch_whitelist_markets(sessions: List[aiohttp.ClientSession]) -> List[Dict[str, Any]]:
    """Fetch markets from MARKET_WHITELIST by slug, bypassing standard filters."""
    if not MARKET_WHITELIST:
        return []
    
    logger.info(f"Fetching {len(MARKET_WHITELIST)} whitelist markets...")
    whitelist_markets = []
    
    for slug in MARKET_WHITELIST:
        try:
            session = random.choice(sessions)
            url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
            
            async with session.get(url, ssl=False) as response:
                if response.status != 200:
                    logger.warning(f"Whitelist market '{slug}' not found (status {response.status})")
                    continue
                
                market = await response.json()
                if not market:
                    continue
                
                # Parse outcome prices and set both YES/NO prices
                outcome_prices = json.loads(market.get("outcomePrices", "[]"))
                price_yes = float(outcome_prices[0]) if outcome_prices else 0
                price_no = float(outcome_prices[1]) if len(outcome_prices) > 1 else 1 - price_yes
                market['_price_yes'] = price_yes
                market['_price_no'] = price_no
                market['_price'] = price_yes  # Keep for backward compat
                
                outcomes_raw = market.get('outcomes', '[]')
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                market['_outcome_yes'] = outcomes[0] if len(outcomes) > 0 else 'Yes'
                market['_outcome_no'] = outcomes[1] if len(outcomes) > 1 else 'No'
                market['_outcome'] = market['_outcome_yes']  # Keep for backward compat
                
                # Check for floor price (Low Probability)
                is_floor_price = False
                if price_yes <= 0.001 or price_no <= 0.001:
                    is_floor_price = True
                market['is_floor_price'] = is_floor_price
                
                whitelist_markets.append(market)
                
                # Extract event_slug
                event_slug = ""
                try:
                    if "events" in market:
                        events = market["events"]
                        if isinstance(events, list) and len(events) > 0:
                            event_slug = events[0].get("slug", "")
                except Exception:
                    pass
                market['_event_slug'] = event_slug
                
                logger.info(f"✓ Loaded whitelist market: {market.get('question', slug)[:60]}")
                
        except Exception as e:
            logger.error(f"Failed to fetch whitelist market '{slug}': {e}")
    
    # Fetch holders for whitelist markets - both YES and NO
    if whitelist_markets:
        yes_ids = [extract_asset_ids(m)[0] for m in whitelist_markets if extract_asset_ids(m)[0]]
        no_ids = [extract_asset_ids(m)[1] for m in whitelist_markets if extract_asset_ids(m)[1]]
        
        if yes_ids or no_ids:
            logger.info(f"Fetching holders for whitelist markets...")
            yes_holders = await fetch_holders_for_assets(sessions, yes_ids) if yes_ids else {}
            no_holders = await fetch_holders_for_assets(sessions, no_ids) if no_ids else {}
            
            for market in whitelist_markets:
                yes_id, no_id = extract_asset_ids(market)
                
                # YES holders
                if yes_id and yes_id in yes_holders:
                    holders = yes_holders[yes_id]
                    market['holders_yes'] = [{'address': w, 'balance': b} for w, b in holders.items()]
                else:
                    market['holders_yes'] = []
                
                # NO holders
                if no_id and no_id in no_holders:
                    holders = no_holders[no_id]
                    market['holders_no'] = [{'address': w, 'balance': b} for w, b in holders.items()]
                else:
                    market['holders_no'] = []
                
                market['holders'] = market['holders_yes']  # Keep for backward compat
                market['assetID_yes'] = yes_id
                market['assetID_no'] = no_id
                logger.info(f"  → {len(market['holders_yes'])}/{len(market['holders_no'])} holders for {market.get('question', '')[:40]}")
    
    return whitelist_markets


def output_json(processed_markets: List[dict]):
    """Output processed markets to SignalStore with 24h gain tracking"""
    import time
    current_time = time.time()
    store = SignalStore()
    
    # Cleanup old history entries
    store.cleanup_old_history()
    
    # Keep only essential fields
    markets_dict = {}
    for m in processed_markets:
        if 'conditionId' not in m:
            continue
        
        condition_id = m['conditionId']
        holders_yes = m.get('holders_yes', {})
        holders_no = m.get('holders_no', {})
        
        # Count sus holders separately
        yes_count = len(holders_yes) if isinstance(holders_yes, dict) else len(holders_yes) if isinstance(holders_yes, list) else 0
        no_count = len(holders_no) if isinstance(holders_no, dict) else len(holders_no) if isinstance(holders_no, list) else 0
        sus_count = yes_count + no_count
        
        # Record current snapshot with separate YES/NO counts
        store.record_holder_count(condition_id, sus_count, current_time, yes_count, no_count)
        
        # Compute 24h gain (returns tuple: total, yes, no)
        baseline_total, baseline_yes, baseline_no = store.get_baseline_count(condition_id, current_time)
        sus_gain_24h = sus_count - baseline_total
        sus_gain_24h_yes = yes_count - baseline_yes
        sus_gain_24h_no = no_count - baseline_no
        
        markets_dict[condition_id] = {
            'question': m.get('question', ''),
            'volume': float(m.get('volume', 0)),
            'startDate': m.get('startDate', ''),
            'endDate': m.get('endDate', ''),
            'slug': m.get('slug', ''),
            'event_slug': m.get('_event_slug', ''),
            # YES outcome data
            'price_yes': float(m.get('_price_yes', m.get('_price', 0))),
            'assetID_yes': m.get('assetID_yes', m.get('assetID', '')),
            'holders_yes': holders_yes,
            # NO outcome data
            'price_no': float(m.get('_price_no', 0)),
            'assetID_no': m.get('assetID_no', ''),
            'holders_no': holders_no,
            # Backward compat (deprecated)
            'price': float(m.get('_price_yes', m.get('_price', 0))),
            'outcome': m.get('_outcome', 'Yes'),
            'assetID': m.get('assetID_yes', m.get('assetID', '')),
            'holders': holders_yes,  # Keep YES as default
            # 24h growth - separate YES/NO
            'sus_gain_24h': sus_gain_24h,
            'sus_gain_24h_yes': sus_gain_24h_yes,
            'sus_gain_24h_no': sus_gain_24h_no
        }
    
    # Save to SignalStore instead of file
    try:
        data_to_save = list(markets_dict.values())
        store.save_fetcher_results(data_to_save)
        logger.info(f"Saved {len(data_to_save)} markets to SignalStore")
    except Exception as e:
        logger.error(f"Failed to save to SignalStore: {e}")


async def run_fetcher():
    """Main entry point with comprehensive logging and timing"""
    overall_start = time.time()
    
    # Create proxy sessions pool
    sessions = []
    
    # Ensure we have enough user agents
    agents_to_use = []
    while len(agents_to_use) < len(PROXIES):
        agents_to_use.extend(USER_AGENTS)
    agents_to_use = agents_to_use[:len(PROXIES)]
    
    for proxy_url, ua in zip(PROXIES, agents_to_use):
        proxy_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=30)
        proxy_headers = {'User-Agent': ua}
        
        connector = None
        if proxy_url:
            if proxy_url.startswith('socks'):
                connector = ProxyConnector.from_url(proxy_url, limit=10, ssl=False, rdns=False)
            elif proxy_url.startswith('http'):
                connector = ProxyConnector.from_url(proxy_url, limit=10, ssl=False, rdns=False)
            else:
                # Fallback for unformatted or other types, though ProxyConnector handles most
                connector = aiohttp.TCPConnector(limit=10, ssl=False)
        else:
            connector = aiohttp.TCPConnector(limit=10, ssl=False)

        proxy_session = aiohttp.ClientSession(
            timeout=proxy_timeout,
            connector=connector,
            headers=proxy_headers
        )
        sessions.append(proxy_session)
    
    try:
        # Phase 1: Fetch markets (skip if WHITELIST_ONLY)
        if WHITELIST_ONLY:
            logger.info("Phase 1: WHITELIST_ONLY mode - skipping regular market fetch")
            filtered_markets = []
        else:
            logger.info("Phase 1: Fetching filtered markets...")
            start = time.time()
            filtered_markets = await fetch_filtered_markets(sessions)
            logger.info(f"Fetched {len(filtered_markets)} markets in {time.time()-start:.2f}s")
        
        # Phase 1.5: Fetch whitelist markets (bypass filters)
        whitelist_markets = await fetch_whitelist_markets(sessions)
        if whitelist_markets:
            # Avoid duplicates by conditionId
            existing_ids = {m.get('conditionId') for m in filtered_markets}
            for wm in whitelist_markets:
                if wm.get('conditionId') not in existing_ids:
                    filtered_markets.append(wm)
            logger.info(f"Added {len(whitelist_markets)} whitelist markets (total: {len(filtered_markets)})")
        
        # Phase 2: Collect unique wallets
        logger.info("Phase 2: Collecting unique wallets...")
        start = time.time()
        unique_wallets = collect_unique_wallets(filtered_markets)
        logger.info(f"Collected {len(unique_wallets)} unique wallets in {time.time()-start:.2f}s")
        
        # Phase 3: Fetch initial stats
        logger.info("Phase 3: Fetching wallet stats...")
        wallet_stats = await fetch_all_wallet_stats(unique_wallets, sessions)
        
        # Phase 4: Categorize wallets
        logger.info("Phase 4: Categorizing wallets...")
        to_remove, flagged_new, flagged_fresh, median_candidates = filter_wallets_by_criteria(wallet_stats)
        
        # Phase 5: Fetch detailed positions for median candidates
        logger.info("Phase 5: Fetching detailed positions for median candidates...")
        detailed_cache = await fetch_detailed_positions(median_candidates, sessions)
        
        # Phase 6: Compute medians for median candidates
        logger.info("Phase 6: Computing medians...")
        median_cache = compute_medians(detailed_cache)
        
        # Phase 7: Processing markets
        logger.info("Phase 7: Processing markets...")
        start = time.time()
        # Pass the market's outcome price to process_single_market
        # Pass the market's outcome price to process_single_market
        processed_markets = [
            process_single_market(
                m, 
                to_remove, 
                flagged_new, 
                flagged_fresh, 
                median_cache, 
                wallet_stats,
                bypass_filters=m.get('is_floor_price', False)
            ) for m in filtered_markets
        ]
        logger.info(f"Processed {len(processed_markets)} markets in {time.time()-start:.2f}s")
        
        # Filter out markets with empty holders
        processed_markets = [m for m in processed_markets if len(m.get('holders', {})) > 0]
        logger.info(f"After filtering empty holders: {len(processed_markets)} markets")
        
        # Output JSON
        output_json(processed_markets)
        
        total_time = time.time() - overall_start
        logger.info("=" * 70)
        logger.info(f"Total execution time: {total_time:.2f}s ({total_time/60:.2f} min)")
        logger.info(f"Estimated API calls: ~{len(unique_wallets) + len(median_candidates)*4}")
        logger.info("=" * 70)
        
        # Display summary statistics
        total_flagged = sum(len(m.get('holders', {})) for m in processed_markets)
        logger.info(f"Markets analyzed: {len(processed_markets)}")
        logger.info(f"Flagged holders: {total_flagged}")
    finally:
        for sess in sessions:
            await sess.close()
