import asyncio
import os
import sys
from datetime import datetime

# Add the parent directory to Python path if running directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scheduler.orchestrator import run_orchestrator

async def main():
    interval_seconds = int(os.getenv("REALTIME_SCRAPER_INTERVAL_SECONDS", "60"))
    print("=" * 60)
    print("Government Tender Intelligence Platform - Real-time Scraper Daemon")
    print(f"Interval: {interval_seconds} seconds between scrape cycles")
    print("Press Ctrl+C to exit gracefully.")
    print("=" * 60)

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            start_time = datetime.utcnow()
            print(f"\n[{start_time.isoformat()}] --- Starting Scrape Cycle #{cycle_count} ---")
            
            try:
                await run_orchestrator()
                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()
                print(f"[{end_time.isoformat()}] --- Cycle #{cycle_count} Completed successfully in {duration:.2f}s ---")
            except Exception as e:
                end_time = datetime.utcnow()
                print(f"[{end_time.isoformat()}] --- Cycle #{cycle_count} Failed: {e} ---", file=sys.stderr)
            
            print(f"Sleeping for {interval_seconds} seconds...")
            await asyncio.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\nStopping Real-time Scraper Daemon gracefully...")
    except asyncio.CancelledError:
        print("\nReal-time Scraper Daemon cancelled.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
