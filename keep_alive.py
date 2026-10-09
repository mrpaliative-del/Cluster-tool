import asyncio
import httpx
import os

# Grab your Render web service public URL automatically from environment variables
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://render.com")

async def global_market_scan_task():
    """
    Runs your Lightweight Global Scan-to-Task loop at an organic, 
    multi-second interval to check for arbitrage spreads.
    """
    while True:
        try:
            # Insert your lightweight asset scanning API calls here
            # print("⏱️ Scanning global asset feeds for price gaps...")
            
            # Keep the intervals staggered using multi-second scheduling
            await asyncio.sleep(5) 
        except Exception as e:
            await asyncio.sleep(5)

async def render_keep_awake_ping():
    """
    Prevents Render from spinning down your application by sending an HTTP request 
    to itself every 10 minutes. Completely neutralizes free tier sleep mode.
    """
    # Wait 30 seconds after initial bootup before firing the first ping
    await asyncio.sleep(30)
    print("🚀 Keep-Alive Heartbeat Engine Activated.")
    
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Ping the health or root endpoint of your app
                response = await client.get(RENDER_EXTERNAL_URL, timeout=10.0)
                print(f"🔄 Loopback Ping Sent to {RENDER_EXTERNAL_URL}. Status Code: {response.status_code} (Instance Kept Awake)")
            except Exception as e:
                print(f"⚠️ Keep-awake ping encountered jitter: {e}")
            
            # Sleep for 10 minutes (600 seconds) before repeating
            await asyncio.sleep(600)

async def start_parallel_loops():
    """
    Orchestrates and runs your multi-second scanning mesh and keep-awake pings 
    concurrently without blocking network execution.
    """
    await asyncio.gather(
        global_market_scan_task(),
        render_keep_awake_ping()
    )

if __name__ == "__main__":
    asyncio.run(start_parallel_loops())
