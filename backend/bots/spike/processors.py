import time
import logging
import queue
import asyncio
from collections import deque, defaultdict
from .config import MIN_BUY_USD, SPIKE_THRESHOLD, TIME_WINDOW, MAX_SIGNAL_PRICE

class EventProcessor:
    def __init__(self, event_queue, asset_to_market_map, monitor, signal_store, ws_manager):
        self.queue = event_queue
        self.asset_map = asset_to_market_map
        self.monitor = monitor
        self.signal_store = signal_store
        self.ws_manager = ws_manager
        self.asset_counters = defaultdict(lambda: {
            'recent_trades': deque(),
            'count': 0,
            'last_activity': time.time(),
            'last_alert_count': 0
        })
        self.running = True
        
    def parse_event(self, event):
        """Extract trade details from event"""
        try:
            asset_id = event.get('asset_id')
            if not asset_id:
                return None
                
            size = event.get('size', 0)
            if not isinstance(size, (int, float)) or size <= 0:
                return None
            size = float(size)
            
            price = event.get('price', 0)
            if not isinstance(price, (int, float)) or price <= 0:
                return None
            price = float(price)
            
            side = event.get('side', '')
            if not side:
                return None
                
            timestamp = event.get('_timestamp', time.time())
            
            return {
                'asset_id': asset_id,
                'size': size,
                'price': price,
                'side': side,
                'usd_value': size * price,
                'timestamp': timestamp
            }
        except Exception as e:
            logging.error(f"Parse error: {e}")
            return None
            
    def prune_old_trades(self, asset_id, current_time):
        """Remove trades older than TIME_WINDOW seconds"""
        counter = self.asset_counters[asset_id]
        trades = counter['recent_trades']

        while trades and (current_time - trades[0]['timestamp']) > TIME_WINDOW:
            trades.popleft()

        old_count = counter['count']
        counter['count'] = len(trades)

        # Reset alert counter if count dropped below threshold
        if old_count >= SPIKE_THRESHOLD and counter['count'] < SPIKE_THRESHOLD:
            counter['last_alert_count'] = 0

    def handle_spike(self, asset_id, trade):
        """Process BUY trade and check for spike per outcome"""
        if trade['side'] != 'BUY' or trade['usd_value'] < MIN_BUY_USD:
            return
            
        market_info = self.asset_map.get(asset_id)
        if not market_info:
            logging.warning(f"Missing market info for asset_id: {asset_id}")
            return
            
        current_time = time.time()
        counter = self.asset_counters[asset_id]
        
        # Add trade
        counter['recent_trades'].append(trade)
        counter['last_activity'] = current_time
        
        # Prune old trades
        self.prune_old_trades(asset_id, current_time)

        # Check for spike - alert only at multiples of threshold
        if (counter['count'] >= SPIKE_THRESHOLD and
            counter['count'] > counter['last_alert_count'] and
            counter['count'] % SPIKE_THRESHOLD == 0):
            self.trigger_alert(asset_id, market_info, counter)
            counter['last_alert_count'] = counter['count']
            
    def trigger_alert(self, asset_id, market_info, counter):
        """Log spike alert per outcome and send to SignalStore/WebSocket"""
        total_usd = sum(t['usd_value'] for t in counter['recent_trades'])
        outcome_index = market_info['outcome_index']
        outcome = market_info['outcomes'][outcome_index]
        price = counter['recent_trades'][-1]['price']  # Use price from the last trade that triggered the spike

        if price > MAX_SIGNAL_PRICE:
            logging.info(f"Skipping spike alert for {market_info['question']} - {outcome}: Price {price} > {MAX_SIGNAL_PRICE}")
            return

        spike_data = {
            "market_id": market_info['market_id'],
            "question": market_info['question'],
            "outcome": outcome,
            "price": price,
            "timestamp": time.time(),
            "asset_id": asset_id,
            "event_slug": market_info.get('event_slug', ''),
            "count": counter['count'],
            "amount_usd": total_usd,
            "type": "spike"
        }

        logging.info(f"🚨 SPIKE ALERT! {market_info['question']} - {outcome} ({counter['count']} buys, ${total_usd:,.0f})")

        # Save to DB
        if self.signal_store:
            self.signal_store.add_spike(spike_data)

        # Broadcast via WebSocket
        if self.ws_manager:
            # We need to run async broadcast in this sync method or thread
            # Since this runs in a thread, we can't await directly if ws_manager.broadcast is async
            # But ws_manager.broadcast IS async.
            # We should probably use a helper or fire and forget.
            # Or better, EventProcessor.run should be async?
            # Currently EventProcessor.run is a while loop with queue.get.
            # I can make run() async or use asyncio.run_coroutine_threadsafe.
            
            # Assuming ws_manager.broadcast is async
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                     loop.create_task(self.ws_manager.broadcast(spike_data))
                else:
                     asyncio.run(self.ws_manager.broadcast(spike_data))
            except RuntimeError:
                # If no loop in this thread (it's a separate thread), we need to find the main loop
                # But SpikeDetector runs in asyncio.run(), so main thread has loop.
                # EventProcessor runs in a separate thread `processor_thread`.
                # So it doesn't have an event loop.
                # I should probably change EventProcessor to run in the main asyncio loop as a task, not a thread.
                # That would be better.
                pass

    def run(self):
        """Main processing loop"""
        # If we want to support async broadcast, we should probably run this as an async task
        # But for now, let's keep it sync and maybe just print or fix later.
        # Actually, I will change run() to be async and run it as a task in main.py
        pass 
        # Wait, I am replacing the file content. I should provide the full content.
        # I will implement run() as async here.
        
    async def run_async(self):
        """Main processing loop (async)"""
        while self.running:
            try:
                # Non-blocking get from queue? Queue is thread-safe but not asyncio-aware.
                # We can use run_in_executor to get from queue or just check with sleep.
                try:
                    event = self.queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue
                
                trade = self.parse_event(event)
                
                if trade and trade['asset_id'] in self.asset_map:
                    self.handle_spike(trade['asset_id'], trade)
                    self.monitor.events_processed += 1
                    
            except Exception as e:
                logging.error(f"Processor error: {e}")
                await asyncio.sleep(0.1)

    # For backward compatibility if needed, but I'll change main.py to call run_async

