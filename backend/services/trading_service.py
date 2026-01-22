"""
Trading Service for Polymarket using py-clob-client
Supports user wallet trading with EIP-712 signing via MetaMask
"""

import os
import time
import json
import logging
import requests
from typing import Optional, Dict, Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, RequestArgs
from py_clob_client.headers.headers import create_level_2_headers, enrich_l2_headers_with_builder_headers
from py_clob_client.constants import POLYGON
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds

logger = logging.getLogger("trading_service")

# Configuration from environment
POLYGON_PRIVATE_KEY = os.getenv("POLYGON_PRIVATE_KEY", "")
POLY_BUILDER_API_KEY = os.getenv("POLY_BUILDER_API_KEY", "")
POLY_BUILDER_SECRET = os.getenv("POLY_BUILDER_SECRET", "")
POLY_BUILDER_PASSPHRASE = os.getenv("POLY_BUILDER_PASSPHRASE", "")
TRADING_PROXY = os.getenv("TRADING_PROXY", "")

# Security limits
MAX_ORDER_USDC = float(os.getenv("MAX_ORDER_USDC", "10000.0"))  # Increased limit
MAX_SLIPPAGE = float(os.getenv("MAX_SLIPPAGE", "0.10"))  # 10% max price deviation

CHAIN_ID = 137  # Polygon Mainnet
CLOB_HOST = "https://clob.polymarket.com"

# Exchange contracts
EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_EXCHANGE_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"


# ============ Rounding Utilities ============

def round_down(val: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(val * factor) / factor

def round_normal(val: float, decimals: int) -> float:
    return round(val, decimals)

def round_up(val: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(val * factor + 0.999999) / factor

def decimal_places(val: float) -> int:
    s = str(val)
    return len(s.split('.')[1]) if '.' in s else 0

def to_token_decimals(val: float) -> int:
    """Convert to USDC decimals (6)"""
    return int(val * (10**6))


class TradingService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TradingService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.client: Optional[ClobClient] = None
        self.builder_config = None
        self._exchange_address = None
        self._initialized = True
        self._init_client()
    
    def _init_client(self):
        """Initialize the CLOB client with credentials"""
        if not all([POLY_BUILDER_API_KEY, POLY_BUILDER_SECRET, POLY_BUILDER_PASSPHRASE]):
            logger.warning("Trading credentials not configured. Set environment variables.")
            return
        
        try:
            # Initialize client (key optional for user wallet trading)
            self.client = ClobClient(
                host=CLOB_HOST,
                key=POLYGON_PRIVATE_KEY if POLYGON_PRIVATE_KEY else None,
                chain_id=POLYGON,
            )
            
            # Builder config for order attribution
            builder_creds = BuilderApiKeyCreds(
                key=POLY_BUILDER_API_KEY,
                secret=POLY_BUILDER_SECRET,
                passphrase=POLY_BUILDER_PASSPHRASE
            )
            self.builder_config = BuilderConfig(local_builder_creds=builder_creds)
            
            logger.info("Trading client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize trading client: {e}")
            self.client = None
    
    def is_ready(self) -> bool:
        return self.client is not None
    
    def get_exchange_address(self) -> str:
        """Get Exchange contract address (cached)"""
        if not self._exchange_address and self.client:
            try:
                self._exchange_address = self.client.get_exchange_address()
            except:
                self._exchange_address = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # Fallback
        return self._exchange_address or "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    
    def get_price(self, token_id: str, side: str = None) -> Optional[Dict[str, float]]:
        """Get current price for a token"""
        if not self.client:
            return None
        try:
            buy_result = self.client.get_price(token_id=token_id, side="BUY")
            sell_result = self.client.get_price(token_id=token_id, side="SELL")
            
            buy_price = float(buy_result.get('price', 0)) if isinstance(buy_result, dict) else float(buy_result)
            sell_price = float(sell_result.get('price', 0)) if isinstance(sell_result, dict) else float(sell_result)
            
            return {
                "bid": buy_price,
                "ask": sell_price,
                "mid": (buy_price + sell_price) / 2
            }
        except Exception as e:
            logger.error(f"Failed to get price for {token_id}: {e}")
            return None
    
    def get_best_ask(self, token_id: str) -> Optional[float]:
        """
        Get best ask price from orderbook for immediate BUY execution.
        Returns the lowest price someone is willing to sell at.
        Note: Polymarket orderbook asks may be sorted descending, so we use min().
        """
        if not self.client:
            return None
        try:
            book = self.client.get_order_book(token_id)
            if book and book.asks and len(book.asks) > 0:
                # Find the LOWEST ask price (best for buyer)
                best_ask = min(float(ask.price) for ask in book.asks)
                logger.info(f"Best ask for {token_id[:10]}...: ${best_ask:.4f}")
                return best_ask
            return None
        except Exception as e:
            logger.error(f"Failed to get orderbook for {token_id}: {e}")
            return None
    
    def get_best_bid(self, token_id: str) -> Optional[float]:
        """
        Get best bid price from orderbook for immediate SELL execution.
        Returns the highest price someone is willing to buy at.
        Note: Polymarket orderbook bids may be sorted ascending, so we use max().
        """
        if not self.client:
            return None
        try:
            book = self.client.get_order_book(token_id)
            if book and book.bids and len(book.bids) > 0:
                # Find the HIGHEST bid price (best for seller)
                best_bid = max(float(bid.price) for bid in book.bids)
                logger.info(f"Best bid for {token_id[:10]}...: ${best_bid:.4f}")
                return best_bid
            return None
        except Exception as e:
            logger.error(f"Failed to get orderbook for {token_id}: {e}")
            return None
    
    def is_neg_risk(self, token_id: str) -> bool:
        """
        Check if a token uses the NegRisk exchange contract.
        Queries the CLOB API for market info.
        """
        try:
            # Query orderbook summary which includes neg_risk flag
            resp = requests.get(
                f"{CLOB_HOST}/book",
                params={"token_id": token_id},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                is_neg = data.get("neg_risk", False)
                logger.info(f"Token {token_id[:15]}... neg_risk={is_neg}")
                return is_neg
        except Exception as e:
            logger.warning(f"Failed to check neg_risk for {token_id}: {e}")
        return False  # Default to normal exchange
    
    def get_exchange_for_token(self, token_id: str) -> str:
        """Get the correct exchange address for a token."""
        if self.is_neg_risk(token_id):
            return NEG_RISK_EXCHANGE_ADDRESS.lower()
        return EXCHANGE_ADDRESS.lower()

    def calculate_vwap(self, token_id: str, side: str, amount_usdc: float) -> Optional[Dict]:
        """
        Calculate VWAP (Volume Weighted Average Price) for a given order size.
        Walks through the orderbook to determine average fill price for large orders.
        
        Args:
            token_id: Token to trade
            side: "BUY" or "SELL"
            amount_usdc: Total USD amount to trade
            
        Returns:
            {
                "vwap": float,           # Average fill price
                "worst_price": float,    # Worst price level touched
                "best_price": float,     # Best price level  
                "total_shares": float,   # Total shares from this fill
                "is_fillable": bool,     # Whether there's enough liquidity
                "levels_used": int,      # Number of orderbook levels used
                "remaining_usdc": float  # Unfilled amount if not fillable
            }
        """
        if not self.client:
            return None
            
        try:
            book = self.client.get_order_book(token_id)
            
            # For BUY: walk through asks (sorted low to high)
            # For SELL: walk through bids (sorted high to low)
            if side.upper() == "BUY":
                if not book.asks:
                    return None
                orders = sorted(book.asks, key=lambda x: float(x.price))  # Ascending
            else:
                if not book.bids:
                    return None
                orders = sorted(book.bids, key=lambda x: float(x.price), reverse=True)  # Descending
            
            total_shares = 0.0
            total_cost = 0.0
            worst_price = 0.0
            best_price = float(orders[0].price) if orders else 0.0
            levels_used = 0
            remaining = amount_usdc
            
            for order in orders:
                price = float(order.price)
                size = float(order.size)
                available_usd = size * price
                
                # How much can we fill from this level?
                fill_usd = min(remaining, available_usd)
                fill_shares = fill_usd / price
                
                total_shares += fill_shares
                total_cost += fill_usd
                worst_price = price
                levels_used += 1
                remaining -= fill_usd
                
                if remaining <= 0.001:  # Small tolerance for float precision
                    break
            
            vwap = total_cost / total_shares if total_shares > 0 else None
            is_fillable = remaining <= 0.001
            
            logger.info(
                f"VWAP for ${amount_usdc} {side}: "
                f"vwap=${vwap:.4f}, worst=${worst_price:.4f}, "
                f"shares={total_shares:.2f}, levels={levels_used}, fillable={is_fillable}"
            )
            
            return {
                "vwap": round(vwap, 6) if vwap else None,
                "worst_price": worst_price,
                "best_price": best_price,
                "total_shares": round(total_shares, 2),
                "is_fillable": is_fillable,
                "levels_used": levels_used,
                "remaining_usdc": round(remaining, 2) if not is_fillable else 0
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate VWAP for {token_id}: {e}")
            return None
    
    def _calculate_amounts(self, side: str, price: float, size: float) -> tuple:
        """Calculate maker/taker amounts with proper rounding for Polymarket"""
        # Price supports 4 decimals (min 0.0001 = 0.01¢), size 2 decimals
        round_config = {"price": 4, "size": 2, "amount": 6}
        raw_price = round_normal(price, round_config["price"])
        
        if side == "BUY":
            raw_taker_amt = round_down(size, round_config["size"])
            raw_maker_amt = raw_taker_amt * raw_price
            if decimal_places(raw_maker_amt) > round_config["amount"]:
                raw_maker_amt = round_up(raw_maker_amt, round_config["amount"] + 4)
                if decimal_places(raw_maker_amt) > round_config["amount"]:
                    raw_maker_amt = round_down(raw_maker_amt, round_config["amount"])
            return to_token_decimals(raw_maker_amt), to_token_decimals(raw_taker_amt)
        else:  # SELL
            raw_maker_amt = round_down(size, round_config["size"])
            raw_taker_amt = raw_maker_amt * raw_price
            if decimal_places(raw_taker_amt) > round_config["amount"]:
                raw_taker_amt = round_up(raw_taker_amt, round_config["amount"] + 4)
                if decimal_places(raw_taker_amt) > round_config["amount"]:
                    raw_taker_amt = round_down(raw_taker_amt, round_config["amount"])
            return to_token_decimals(raw_maker_amt), to_token_decimals(raw_taker_amt)
    
    def prepare_order_for_user(
        self, 
        user_address: str, 
        proxy_address: str, 
        token_id: str, 
        price: float, 
        size: float, 
        side: str,
        order_type: str = "FOK"
    ) -> Dict[str, Any]:
        """
        Create unsigned EIP-712 order structure for frontend MetaMask signing.
        
        Security validations:
        - Price within MAX_SLIPPAGE of current market (only for FOK/market orders)
        - Order value <= MAX_ORDER_USDC
        
        Args:
            order_type: "FOK" (market) or "GTC" (limit) - limits skip slippage check
        
        Returns:
            dict with {domain, types, message} for signTypedData
        """
        # ============ SECURITY VALIDATIONS ============
        
        # Validate token_id
        if not token_id:
            raise ValueError("Token ID is required")
        token_id = str(token_id).strip()
        logger.info(f"Token ID bytes: {token_id.encode('utf-8')}")
        
        # Validate side
        side = side.upper()
        if side not in ["BUY", "SELL"]:
            raise ValueError(f"Invalid side: {side}")
        
        # Validate price range (only for market orders - limit orders can set any price)
        is_limit_order = order_type.upper() in ["GTC", "GTD"]
        if not is_limit_order:
            current_prices = self.get_price(token_id)
            if current_prices:
                market_price = current_prices["ask"] if side == "BUY" else current_prices["bid"]
                if market_price > 0:
                    deviation = abs(price - market_price) / market_price
                    if deviation > MAX_SLIPPAGE:
                        raise ValueError(
                            f"Price deviation too high: {deviation:.1%}. "
                            f"Market: ${market_price:.4f}, Your price: ${price:.4f}. "
                            f"Max allowed: {MAX_SLIPPAGE:.0%}"
                        )
        
        # Validate order size
        order_value = price * size
        if order_value > MAX_ORDER_USDC:
            raise ValueError(f"Order value ${order_value:.2f} exceeds limit ${MAX_ORDER_USDC:.2f}")
        
        if order_value < 1.0:
            raise ValueError(f"Minimum order value is $1.00, got ${order_value:.2f}")
        
        # ============ CREATE ORDER STRUCTURE ============
        
        maker_amount, taker_amount = self._calculate_amounts(side, price, size)
        salt = int(time.time() * 1000)
        
        # Get correct exchange based on token type (normal vs neg_risk)
        exchange_address = self.get_exchange_for_token(token_id)
        
        # All addresses MUST be lowercase
        proxy_address_lower = proxy_address.lower()
        user_address_lower = user_address.lower()
        
        domain = {
            "name": "Polymarket CTF Exchange",
            "version": "1",
            "chainId": CHAIN_ID,  # Must be INTEGER for ethers.js
            "verifyingContract": exchange_address
        }
        
        types = {
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"}
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"}
            ]
        }
        
        message = {
            "salt": str(salt),
            "maker": proxy_address_lower,
            "signer": user_address_lower,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0",
            "side": "0" if side == "BUY" else "1",  # Must be STRING
            "signatureType": "2"  # Must be STRING, Proxy wallet
        }
        
        logger.info(f"Prepared order: {user_address[:10]}... {side} {size} @ ${price} = ${order_value:.2f}")
        logger.info(f"TokenId: {token_id[:20]}..., Exchange: {exchange_address}")
        
        return {
            "types": types,  # types first (matching betmoar order)
            "domain": domain,
            "primaryType": "Order",  # CRITICAL: was missing!
            "message": message,
            "order_summary": {
                "side": side,
                "price": price,
                "size": size,
                "total_usdc": order_value,
                "user_address": user_address,
                "proxy_address": proxy_address
            }
        }
    
    def submit_user_order(
        self, 
        signed_order: Dict[str, Any],
        user_api_key: str,
        user_api_secret: str,
        user_passphrase: str,
        order_type: str = "FOK"
    ) -> Dict[str, Any]:
        """
        Submit an order that was signed by user's wallet.
        Uses USER's L2 credentials for authentication (not backend wallet).
        Builder headers are added for volume attribution.
        
        Args:
            signed_order: dict with {domain, types, message, signature}
            user_api_key: User's Polymarket API key
            user_api_secret: User's API secret
            user_passphrase: User's API passphrase
            order_type: "FOK" (market) or "GTC" (limit)
            
        Returns:
            Order result from Polymarket
        """
        if not self.client:
            raise ValueError("Trading client not initialized")
        
        # Create user credentials object
        user_creds = ApiCreds(
            api_key=user_api_key,
            api_secret=user_api_secret,
            api_passphrase=user_passphrase
        )
        
        # ============ TRANSFORM TO SDK FORMAT ============
        # Input: {domain, types, message, signature, primaryType, order_summary}
        # Output: {order: {..., signature}, owner: api_key, orderType: "GTC"}
        
        message = signed_order.get("message", {})
        signature = signed_order.get("signature", "")
        domain = signed_order.get("domain", {})
        
        # Convert side: "0" → "BUY", "1" → "SELL"
        side_raw = message.get("side", "0")
        side = "BUY" if str(side_raw) == "0" else "SELL"
        
        # Convert signatureType: "2" → 2 (integer)
        sig_type_raw = message.get("signatureType", "2")
        sig_type = int(sig_type_raw) if isinstance(sig_type_raw, str) else sig_type_raw
        
        # salt must be INTEGER
        salt_raw = message.get("salt", "0")
        salt = int(salt_raw) if isinstance(salt_raw, str) else salt_raw
        
        order = {
            "salt": salt,  # INTEGER!
            "maker": message.get("maker"),
            "signer": message.get("signer"),
            "taker": message.get("taker", "0x0000000000000000000000000000000000000000"),
            "tokenId": str(message.get("tokenId")),
            "makerAmount": str(message.get("makerAmount")),
            "takerAmount": str(message.get("takerAmount")),
            "expiration": str(message.get("expiration", "0")),
            "nonce": str(message.get("nonce", "0")),
            "feeRateBps": str(message.get("feeRateBps", "0")),
            "side": side,
            "signatureType": sig_type,
            "signature": signature
        }
        
        # Debug: compare signed message vs submitted order
        logger.info(f"Original message tokenId type: {type(message.get('tokenId'))}, value: {str(message.get('tokenId'))[:20]}...")
        logger.info(f"Original message salt type: {type(message.get('salt'))}, value: {message.get('salt')}")
        logger.info(f"Transformed order salt type: {type(salt)}, value: {salt}")
        logger.info(f"Verifying Contract: {domain.get('verifyingContract')}")
        
        # Build final payload - owner is USER's api_key (not backend's!)
        # Validate order_type
        if order_type not in ["FOK", "GTC", "GTD"]:
            order_type = "FOK"
        
        payload = {
            "order": order,
            "owner": user_api_key,  # USER's API key!
            "orderType": order_type  # FOK=market, GTC=limit
        }
        
        body_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        endpoint = "/order"
        
        logger.info(f"Submitting order for user: {order.get('signer', '')[:10]}...")
        
        # L2 Headers (auth) - using USER's credentials!
        # CRITICAL: body must be payload (what we send), not signed_order (what we received)
        req_args = RequestArgs(method="POST", request_path=endpoint, body=payload, serialized_body=body_json)
        headers = create_level_2_headers(self.client.signer, user_creds, req_args)
        
        # CRITICAL FIX: Override POLY_ADDRESS with USER's address (not backend wallet!)
        # The API key belongs to the user, so POLY_ADDRESS must be their EOA address
        user_address = message.get("signer", "")  # User's EOA from signed order
        headers["POLY_ADDRESS"] = user_address.lower()
        
        logger.info(f"L2 Headers: address={user_address[:10]}..., api_key={user_api_key[:10]}...")
        
        # Builder Headers (platform attribution) - using PLATFORM's credentials
        if self.builder_config:
            builder_headers = self.builder_config.generate_builder_headers("POST", endpoint, body_json)
            if builder_headers:
                headers = enrich_l2_headers_with_builder_headers(headers, builder_headers.to_dict())
                logger.info(f"Builder attribution headers added: {list(builder_headers.to_dict().keys())}")
        
        # Browser-like headers
        headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://polymarket.com/",
            "Origin": "https://polymarket.com",
            "Content-Type": "application/json"
        })
        
        # Proxy
        proxies = {"http": TRADING_PROXY, "https": TRADING_PROXY} if TRADING_PROXY else None
        
        logger.info(f"Submitting order to CLOB...")
        logger.info(f"Order payload: {body_json}")
        logger.info(f"Order details: maker={order.get('maker', '')[:10]}, signer={order.get('signer', '')[:10]}, tokenId={order.get('tokenId', '')[:10]}, sig_len={len(signature)}")
        logger.info(f"Full order: salt={order.get('salt')}, side={order.get('side')}, makerAmt={order.get('makerAmount')}, takerAmt={order.get('takerAmount')}")
        
        resp = requests.post(
            f"{CLOB_HOST}{endpoint}",
            headers=headers,
            data=body_json,
            proxies=proxies,
            timeout=60
        )
        
        if resp.status_code != 200:
            error_msg = resp.text[:500]
            logger.error(f"CLOB error {resp.status_code}: {error_msg}")
            raise ValueError(f"Order submission failed: {error_msg}")
        
        result = resp.json()
        logger.info(f"Order submitted successfully: {result}")
        return result
    
    def get_open_orders(
        self,
        user_address: str,
        user_api_key: str,
        user_api_secret: str,
        user_passphrase: str
    ) -> list:
        """
        Get user's open orders from CLOB.
        
        Returns:
            List of open orders
        """
        if not self.client:
            raise ValueError("Trading client not initialized")
        
        user_creds = ApiCreds(
            api_key=user_api_key,
            api_secret=user_api_secret,
            api_passphrase=user_passphrase
        )
        
        # Use /data/orders endpoint for fetching active orders
        endpoint = "/data/orders"
        req_args = RequestArgs(method="GET", request_path=endpoint)
        headers = create_level_2_headers(self.client.signer, user_creds, req_args)
        headers["POLY_ADDRESS"] = user_address.lower()
        
        headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        })
        
        proxies = {"http": TRADING_PROXY, "https": TRADING_PROXY} if TRADING_PROXY else None
        
        logger.info(f"Fetching open orders for {user_address[:10]}...")
        
        resp = requests.get(
            f"{CLOB_HOST}{endpoint}",
            headers=headers,
            proxies=proxies,
            timeout=30
        )
        
        if resp.status_code != 200:
            logger.error(f"Get orders error {resp.status_code}: {resp.text[:200]}")
            return []
        
        result = resp.json()
        # API returns {data: [...], next_cursor, limit, count}
        orders = result.get("data", []) if isinstance(result, dict) else result
        logger.info(f"Found {len(orders)} open orders")
        return orders
    
    def cancel_order(
        self,
        order_id: str,
        user_address: str,
        user_api_key: str,
        user_api_secret: str,
        user_passphrase: str
    ) -> Dict[str, Any]:
        """
        Cancel an open order.
        
        Args:
            order_id: ID of order to cancel
            user_address: User's EOA wallet address
            user_api_key: User's API key
            user_api_secret: User's API secret
            user_passphrase: User's passphrase
            
        Returns:
            Cancel result from CLOB
        """
        if not self.client:
            raise ValueError("Trading client not initialized")
        
        user_creds = ApiCreds(
            api_key=user_api_key,
            api_secret=user_api_secret,
            api_passphrase=user_passphrase
        )
        
        payload = {"orderID": order_id}
        body_json = json.dumps(payload, separators=(",", ":"))
        endpoint = "/order"
        
        req_args = RequestArgs(method="DELETE", request_path=endpoint, body=payload, serialized_body=body_json)
        headers = create_level_2_headers(self.client.signer, user_creds, req_args)
        headers["POLY_ADDRESS"] = user_address.lower()
        
        headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        })
        
        proxies = {"http": TRADING_PROXY, "https": TRADING_PROXY} if TRADING_PROXY else None
        
        logger.info(f"Cancelling order {order_id}...")
        
        resp = requests.delete(
            f"{CLOB_HOST}{endpoint}",
            headers=headers,
            data=body_json,
            proxies=proxies,
            timeout=30
        )
        
        if resp.status_code != 200:
            error_msg = resp.text[:300]
            logger.error(f"Cancel order error {resp.status_code}: {error_msg}")
            raise ValueError(f"Failed to cancel order: {error_msg}")
        
        result = resp.json()
        logger.info(f"Order cancelled: {result}")
        return result


# Singleton instance
trading_service = TradingService()
