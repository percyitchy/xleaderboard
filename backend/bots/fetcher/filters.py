from typing import Optional, Tuple

from .config import (
    MAX_TRADES,
    MIN_TRADES,
    MAX_VOL,
    MIN_WALLET_AGE_DAYS
)


def filter_wallet(
    wallet_address: str,
    balance: float,
    traded_count: Optional[int],
    vol: Optional[float],
    wallet_age_days: Optional[int]
) -> Tuple[bool, str, bool]:
    """Фильтрует кошелек по критериям"""
    marks = []
    
    if traded_count is not None and traded_count > MAX_TRADES:
        return False, f"trades={traded_count}>{MAX_TRADES}", False
    
    if vol is not None and vol > MAX_VOL:
        return False, f"vol=${vol:,.0f}>${MAX_VOL:,.0f}", False
    
    if traded_count is not None and traded_count < MIN_TRADES:
        marks.append(f"trades={traded_count}<{MIN_TRADES}")
    
    if wallet_age_days is not None and wallet_age_days < MIN_WALLET_AGE_DAYS:
        marks.append(f"age={wallet_age_days}d<{MIN_WALLET_AGE_DAYS}d")
    
    has_marks = len(marks) > 0
    reason = " | ".join(marks) if marks else "OK"
    
    return True, reason, has_marks
