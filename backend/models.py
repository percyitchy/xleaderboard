from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime

class Market(BaseModel):
    conditionId: str
    question: str
    volume: float
    outcomePrices: List[str]
    endDate: Optional[str] = None
    holders: List[Dict[str, Any]] = []

class SpikeSignal(BaseModel):
    market_id: Optional[str] = None
    question: Optional[str] = None
    outcome: Optional[str] = None
    price: Optional[float] = 0.0
    timestamp: Optional[float] = 0.0
    asset_id: Optional[str] = None
    amount_usd: Optional[float] = 0.0
    event_slug: Optional[str] = None
    
    class Config:
        extra = "ignore"  # Ignore extra fields from DB (id, created_at)

class WalletSignal(BaseModel):
    market_id: Optional[str] = None
    question: Optional[str] = None
    outcome: Optional[str] = None
    price: Optional[float] = 0.0
    usdc_size: Optional[float] = 0.0
    timestamp: Optional[float] = 0.0
    wallets: List[Dict[str, Any]] = []
    category: Optional[str] = None
    asset_id: Optional[str] = None
    event_slug: Optional[str] = None
    
    class Config:
        extra = "ignore"


class LeaderboardEntry(BaseModel):
    rank: int
    proxy_wallet: str
    x_username: str
    name: Optional[str] = None
    profile_image: Optional[str] = None
    verified_badge: Optional[bool] = False
    pnl: float
    volume: Optional[float] = None
    open_positions: Optional[int] = None
    pnl_source: Optional[str] = None


class LeaderboardMeta(BaseModel):
    period: str
    limit: int
    offset: int
    has_more: bool
    as_of: datetime
    pnl_source: Optional[str] = None


class LeaderboardResponse(BaseModel):
    items: List[LeaderboardEntry]
    meta: LeaderboardMeta
