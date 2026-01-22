import sqlite3
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import os

from backend.services.telegram_service import telegram_service

logger = logging.getLogger("signal_store")

DB_PATH = "polymarketeye.db"

class SignalStore:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SignalStore, cls).__new__(cls)
            cls._instance.init_db()
        return cls._instance

    def init_db(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        
        # Create tables
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS spikes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT,
                question TEXT,
                outcome TEXT,
                price REAL,
                timestamp REAL,
                asset_id TEXT,
                event_slug TEXT,
                amount_usd REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Migration: Check if amount_usd exists in spikes
        try:
            self.cursor.execute("SELECT amount_usd FROM spikes LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating spikes table: adding amount_usd column")
            self.cursor.execute("ALTER TABLE spikes ADD COLUMN amount_usd REAL DEFAULT 0")
            self.conn.commit()
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT,
                question TEXT,
                outcome TEXT,
                price REAL,
                usdc_size REAL,
                timestamp REAL,
                wallets TEXT, -- JSON list
                category TEXT,
                event_slug TEXT,
                asset_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migration: Check if asset_id exists in wallet_signals
        try:
            self.cursor.execute("SELECT asset_id FROM wallet_signals LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating wallet_signals table: adding asset_id column")
            self.cursor.execute("ALTER TABLE wallet_signals ADD COLUMN asset_id TEXT")
            self.conn.commit()
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS fetcher_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT, -- JSON blob
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Holder history for 24h gain tracking
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS holder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                condition_id TEXT,
                sus_count INTEGER,
                sus_count_yes INTEGER DEFAULT 0,
                sus_count_no INTEGER DEFAULT 0,
                timestamp REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migration: Add sus_count_yes/no columns if missing
        try:
            self.cursor.execute("SELECT sus_count_yes FROM holder_history LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating holder_history: adding sus_count_yes/no columns")
            self.cursor.execute("ALTER TABLE holder_history ADD COLUMN sus_count_yes INTEGER DEFAULT 0")
            self.cursor.execute("ALTER TABLE holder_history ADD COLUMN sus_count_no INTEGER DEFAULT 0")
            self.conn.commit()
        
        # Index for faster lookups by condition_id and timestamp
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_holder_history_lookup 
            ON holder_history (condition_id, timestamp)
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_value_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_wallet TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (proxy_wallet, timestamp)
            )
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_portfolio_value_lookup
            ON portfolio_value_snapshots (proxy_wallet, timestamp)
        ''')
        
        self.conn.commit()
        logger.info("SignalStore initialized with SQLite")

    def add_spike(self, spike_data: dict):
        try:
            self.cursor.execute('''
                INSERT INTO spikes (market_id, question, outcome, price, timestamp, asset_id, event_slug, amount_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                spike_data.get('market_id'),
                spike_data.get('question'),
                spike_data.get('outcome'),
                spike_data.get('price'),
                spike_data.get('timestamp'),
                spike_data.get('asset_id'),
                spike_data.get('event_slug'),
                spike_data.get('amount_usd', 0)
            ))
            self.conn.commit()
            
            # Send Telegram notification
            try:
                asyncio.get_event_loop().create_task(telegram_service.send_spike(spike_data))
            except RuntimeError:
                asyncio.run(telegram_service.send_spike(spike_data))
            
            # Cleanup old spikes (keep last 100)
            self.cursor.execute('''
                DELETE FROM spikes WHERE id NOT IN (
                    SELECT id FROM spikes ORDER BY id DESC LIMIT 100
                )
            ''')
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding spike: {e}")

    def get_spikes(self, limit: int = 100) -> List[dict]:
        import time
        # Only return spikes from the last 6 hours
        six_hours_ago = time.time() - (6 * 60 * 60)
        
        # First, cleanup old spikes (older than 6 hours)
        self.cursor.execute('DELETE FROM spikes WHERE timestamp < ?', (six_hours_ago,))
        self.conn.commit()
        
        # Return recent spikes
        self.cursor.execute(
            'SELECT * FROM spikes WHERE timestamp >= ? ORDER BY id DESC LIMIT ?', 
            (six_hours_ago, limit)
        )
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows]

    def add_wallet_signal(self, signal_data: dict):
        try:
            wallets_json = json.dumps(signal_data.get('wallets', []))
            self.cursor.execute('''
                INSERT INTO wallet_signals (market_id, question, outcome, price, usdc_size, timestamp, wallets, category, event_slug, asset_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_data.get('market_id'),
                signal_data.get('question'),
                signal_data.get('outcome'),
                signal_data.get('price'),
                signal_data.get('usdc_size'),
                signal_data.get('timestamp'),
                wallets_json,
                signal_data.get('category'),
                signal_data.get('event_slug'),
                signal_data.get('asset_id')
            ))
            self.conn.commit()
            
            # Send Telegram notification
            try:
                asyncio.get_event_loop().create_task(telegram_service.send_wallet_signal(signal_data))
            except RuntimeError:
                asyncio.run(telegram_service.send_wallet_signal(signal_data))
            
            # Cleanup old signals per category (keep last 30)
            category = signal_data.get('category')
            if category:
                self.cursor.execute('''
                    DELETE FROM wallet_signals 
                    WHERE category = ? AND id NOT IN (
                        SELECT id FROM wallet_signals WHERE category = ? ORDER BY id DESC LIMIT 30
                    )
                ''', (category, category))
                self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding wallet signal: {e}")

    def get_wallet_signals(self, category: str = None, limit: int = 100) -> List[dict]:
        import time
        # Only return signals from the last 24 hours
        twenty_four_hours_ago = time.time() - (24 * 60 * 60)
        
        # Cleanup old signals (older than 24 hours)
        self.cursor.execute('DELETE FROM wallet_signals WHERE timestamp < ?', (twenty_four_hours_ago,))
        self.conn.commit()
        
        # Return recent signals
        if category:
            self.cursor.execute(
                'SELECT * FROM wallet_signals WHERE category = ? AND timestamp >= ? ORDER BY id DESC LIMIT ?', 
                (category, twenty_four_hours_ago, limit)
            )
        else:
            self.cursor.execute(
                'SELECT * FROM wallet_signals WHERE timestamp >= ? ORDER BY id DESC LIMIT ?', 
                (twenty_four_hours_ago, limit)
            )
        
        rows = self.cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d['wallets'] = json.loads(d['wallets'])
            results.append(d)
        return results

    def save_fetcher_results(self, data: List[dict]):
        try:
            json_data = json.dumps(data)
            self.cursor.execute('INSERT INTO fetcher_results (data) VALUES (?)', (json_data,))
            self.conn.commit()
            
            # Keep only last 5 runs
            self.cursor.execute('''
                DELETE FROM fetcher_results WHERE id NOT IN (
                    SELECT id FROM fetcher_results ORDER BY id DESC LIMIT 5
                )
            ''')
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error saving fetcher results: {e}")

    def get_latest_fetcher_result(self) -> Dict[str, Any]:
        self.cursor.execute('SELECT data, created_at FROM fetcher_results ORDER BY id DESC LIMIT 1')
        row = self.cursor.fetchone()
        if row:
            return {
                "data": json.loads(row['data']),
                "created_at": row['created_at']
            }
        return {}

    def record_holder_count(self, condition_id: str, sus_count: int, timestamp: float, sus_count_yes: int = 0, sus_count_no: int = 0):
        """Record sus holder count snapshot for 24h gain tracking."""
        try:
            self.cursor.execute(
                'INSERT INTO holder_history (condition_id, sus_count, sus_count_yes, sus_count_no, timestamp) VALUES (?, ?, ?, ?, ?)',
                (condition_id, sus_count, sus_count_yes, sus_count_no, timestamp)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error recording holder count: {e}")

    def get_baseline_count(self, condition_id: str, current_timestamp: float) -> tuple:
        """Get sus counts from ~24h ago (or oldest available if <24h).
        Returns: (sus_count, sus_count_yes, sus_count_no)
        """
        target_time = current_timestamp - (24 * 60 * 60)  # 24 hours ago
        
        # Try to get count closest to 24h ago (but not newer)
        self.cursor.execute('''
            SELECT sus_count, sus_count_yes, sus_count_no FROM holder_history 
            WHERE condition_id = ? AND timestamp <= ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (condition_id, target_time))
        row = self.cursor.fetchone()
        
        if row:
            return (row['sus_count'], row['sus_count_yes'] or 0, row['sus_count_no'] or 0)
        
        # If no record 24h ago, get the oldest available record
        self.cursor.execute('''
            SELECT sus_count, sus_count_yes, sus_count_no FROM holder_history 
            WHERE condition_id = ?
            ORDER BY timestamp ASC LIMIT 1
        ''', (condition_id,))
        row = self.cursor.fetchone()
        if row:
            return (row['sus_count'], row['sus_count_yes'] or 0, row['sus_count_no'] or 0)
        return (0, 0, 0)

    def cleanup_old_history(self):
        """Remove holder history older than 25 hours."""
        import time
        cutoff = time.time() - (25 * 60 * 60)
        try:
            self.cursor.execute('DELETE FROM holder_history WHERE timestamp < ?', (cutoff,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error cleaning up holder history: {e}")

    def add_portfolio_value_snapshot(self, proxy_wallet: str, value: float, timestamp: float):
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO portfolio_value_snapshots (proxy_wallet, value, timestamp)
                VALUES (?, ?, ?)
            ''', (proxy_wallet, value, timestamp))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error adding portfolio value snapshot: {e}")

    def get_portfolio_snapshot_before(self, proxy_wallet: str, target_timestamp: float) -> Optional[Dict[str, Any]]:
        self.cursor.execute('''
            SELECT value, timestamp FROM portfolio_value_snapshots
            WHERE proxy_wallet = ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (proxy_wallet, target_timestamp))
        row = self.cursor.fetchone()
        return dict(row) if row else None
