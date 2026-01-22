import asyncio
import aiohttp
import json
from typing import Dict, Optional, Tuple, Any

from .config import (
    MIN_HOLDERS_COUNT
)

from .api_client import (
    get_wallet_stats,
    fetch_holders_for_asset
)

from .filters import (
    filter_wallet
)


async def process_single_wallet(
    session: aiohttp.ClientSession,
    wallet_address: str,
    balance: float,
    cache: Optional[Dict[str, Tuple[Optional[int], Optional[float], Optional[int]]]] = None
) -> Optional[Tuple[str, float, dict]]:
    """Обрабатывает один кошелек"""
    try:
        if cache and wallet_address in cache:
            traded, vol, age = cache[wallet_address]
        else:
            traded, vol, age = await get_wallet_stats(session, wallet_address)
        
        pass_filter, reason, mark_special = filter_wallet(
            wallet_address,
            balance,
            traded,
            vol,
            age
        )
        
        if not pass_filter:
            print(f"    ✗ {wallet_address[:10]}... {reason} - УДАЛЕН")
            return None
        
        wallet_key = wallet_address
        if mark_special:
            wallet_key = f"⚠️{wallet_address}"
            print(f"    ⚠️  {wallet_address[:10]}... {reason} - ПОМЕЧЕН")
        else:
            print(f"    ✓ {wallet_address[:10]}... {reason}")
        
        stats = {
            'traded': traded,
            'vol': vol,
            'age': age,
            'filtered_by': None if pass_filter else reason
        }
        
        return (wallet_key, balance, stats)
        
    except Exception:
        return None


async def process_market_holders(
    session: aiohttp.ClientSession,
    holders: Dict[str, float],
    semaphore: asyncio.Semaphore,
    cache: Optional[Dict[str, Tuple[Optional[int], Optional[float], Optional[int]]]] = None
) -> Tuple[dict, dict]:
    """Обрабатывает всех холдеров маркета параллельно"""
    
    async def process_with_semaphore(wallet_address, balance):
        async with semaphore:
            return await process_single_wallet(session, wallet_address, balance, cache)
    
    tasks = [
        process_with_semaphore(wallet_address, balance)
        for wallet_address, balance in holders.items()
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    filtered_holders = {}
    stats = {
        'filtered_by_trades': 0,
        'filtered_by_vol': 0,
        'marked': 0,
        'kept': 0
    }
    
    for result in results:
        if result and not isinstance(result, Exception):
            wallet_key, balance, wallet_stats = result
            filtered_holders[wallet_key] = balance
            stats['kept'] += 1
            
            if wallet_key.startswith('⚠️'):
                stats['marked'] += 1
    
    return filtered_holders, stats


def process_single_market(market: dict, to_remove: set, flagged_new: set, flagged_fresh: set, median_cache: Dict[str, dict], wallet_stats: Dict[str, tuple], bypass_filters: bool = False) -> dict:
    """Process market with categorized wallets and median cache for both YES and NO outcomes."""

    # Get prices for value calculation
    price_yes = market.get('_price_yes', market.get('_price', 0.0))
    price_no = market.get('_price_no', 0.0)

    # Extract asset IDs for both outcomes
    asset_id_yes = ""
    asset_id_no = ""
    if "clobTokenIds" in market:
        clob_token_ids_str = market["clobTokenIds"]
        clob_token_ids = json.loads(clob_token_ids_str)
        if len(clob_token_ids) > 0:
            asset_id_yes = clob_token_ids[0]
        if len(clob_token_ids) > 1:
            asset_id_no = clob_token_ids[1]

    def process_holders(holders_list, price, asset_id):
        """Process a list of holders and return filtered dict."""
        processed = {}
        for holder in holders_list:
            wallet = holder.get('address')
            balance = holder.get('balance', 0)

            # Skip if no wallet stats available
            if wallet not in wallet_stats:
                continue

            # 1. REMOVE qualified wallets
            if wallet in to_remove:
                continue

            # Common calculation for value (USD)
            position_value = balance * price

            # 2. FLAG NEW criteria (age < 30) with ⚠️
            if wallet in flagged_new:
                wallet_key = f"⚠️{wallet}"
                processed[wallet_key] = position_value
                continue
                
            # 3. FLAG FRESH criteria (trades <= 5) with 🌱
            if wallet in flagged_fresh:
                wallet_key = f"🌱{wallet}"
                processed[wallet_key] = position_value
                continue

            # 4. Check median criteria for median_candidates - flag with ☎️
            should_flag_median = False
            if wallet in median_cache:
                cache_data = median_cache[wallet]
                median = cache_data['median']
                open_positions = cache_data['open_positions']

                # Check if wallet has open position in this market
                if asset_id in open_positions:
                    initial_value = open_positions[asset_id]

                    # Flag if position > 3x median
                    if median > 0 and initial_value > (3 * median):
                        should_flag_median = True

            # Only add if flagged by median criteria (skip clean wallets)
            if should_flag_median:
                wallet_key = f"☎️{wallet}"
                processed[wallet_key] = position_value
            elif bypass_filters:
                # If filters are bypassed, include wallet even if not flagged
                # Use ⭐ to distinct them or just keep as is?
                # Using ⭐ to indicate "Top Holder" in floor market
                wallet_key = f"⭐{wallet}"
                processed[wallet_key] = position_value
        
        return processed

    # Process YES holders
    holders_yes = market.get('holders_yes', market.get('holders', []))
    processed_yes = process_holders(holders_yes, price_yes, asset_id_yes)
    
    # Process NO holders
    holders_no = market.get('holders_no', [])
    processed_no = process_holders(holders_no, price_no, asset_id_no)

    # Store both sets of processed holders
    market['holders_yes'] = processed_yes
    market['holders_no'] = processed_no
    market['holders'] = processed_yes  # Keep for backward compat
    market['assetID_yes'] = asset_id_yes
    market['assetID_no'] = asset_id_no
    market['assetID'] = asset_id_yes  # Keep for backward compat
    
    return market
