import asyncio
import httpx

# Map directly to local system network loopback interfaces
INTERNAL_HEALTH_URL = "http://127.0.0"

async def global_market_scan_task():
    while True:
        try:
            await asyncio.sleep(5) 
        except Exception:
            await asyncio.sleep(5)

async def render_keep_awake_ping():
    # Wait for the lifespan container configuration blocks to pass completely first
    await asyncio.sleep(25)
    print("🚀 Keep-Alive Heartbeat Engine Activated Natively.")
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.get(INTERNAL_HEALTH_URL, timeout=5.0)
                if response.status_code == 200:
                    print("🔄 Internal loopback health tracking ping confirmed (200 OK).")
            except Exception as e:
                print(f"⚠️ Keep-awake thread ping caught network jitter: {e}")
            
            # Ping every 4 minutes to comfortably pass Render's free timeout constraints
            await asyncio.sleep(240)

async def start_parallel_loops():
    await asyncio.gather(
        global_market_scan_task(),
        render_keep_awake_ping()
    )
