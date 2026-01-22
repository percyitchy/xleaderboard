import asyncio
import sys
from sourcing import fetch_top_traders
from monitoring import monitor_wallets

# 1 hour in seconds
REFRESH_INTERVAL = 3600 

async def main():
    print("=== Polymarket Smart Money Tracker v3.0 ===")

    while True:
        try:
            # Each monitoring cycle fetches fresh traders and monitors for REFRESH_INTERVAL
            await monitor_wallets(duration=REFRESH_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n[!] Stopping bot...")
            break
        except Exception as e:
            print(f"[!] Unexpected error in main loop: {e}")
            print("[!] Restarting loop in 10 seconds...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
