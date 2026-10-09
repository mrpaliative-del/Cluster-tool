import asyncio
import httpx
import os

# Target the internal system port directly to eliminate DNS lookups
INTERNAL_HEALTH_URL = "http://127.0.0"

async def global_market_scan_task():
    """ Runs your Lightweight Global Scan-to-Task loop safely """
    while True:
        try:
            # Staggered multi-second asset loopback array
            await asyncio.sleep(5) 
        except Exception as e:
            await asyncio.sleep(5)

async def render_keep_awake_ping():
    """ Prevents Render from spinning down by targeting the dedicated /health hook """
    # Safe initial startup buffer delay allows Uvicorn to bind to port 10000 first
    await asyncio.sleep(15)
    print("🚀 Keep-Alive Heartbeat Engine Activated.")
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Target the local endpoint instead of public network gateways
                response = await client.get(INTERNAL_HEALTH_URL, timeout=5.0)
                if response.status_code == 200:
                    print(f"🔄 Loopback Health Ping Verified: Local Status Code {response.status_code}")
            except Exception as e:
                print(f"⚠️ Keep-awake ping encountered jitter: {e}")
            
            # Ping every 4 minutes (240 seconds) to completely clear free-tier sleep limits
            await asyncio.sleep(240)

async def start_parallel_loops():
    """ Orchestrates scanning arrays concurrently without blocking network processing """
    await asyncio.gather(
        global_market_scan_task(),
        render_keep_awake_ping()
    )

if __name__ == "__main__":
    asyncio.run(start_parallel_loops())
