import subprocess
import threading
import os
import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "zero_budget_mesh"}

def run_java_execution_engine():
    """
    Runs the compiled low-latency Java JAR as a lightweight background thread.
    Restricts memory allocation explicitly to survive within free hosting limits.
    """
    print("☕ Launching High-Speed Java Execution Block off-heap...")
    # -Xmx256m guarantees Java will never consume more than half of Render's free RAM pool
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    """ Runs the async scanning loops and ping engines inside a separate runtime thread. """
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

if __name__ == "__main__":
    # 1. Boot Java Engine in thread pool
    java_thread = threading.Thread(target=run_java_execution_engine, daemon=True)
    java_thread.start()

    # 2. Boot Keep-Alive & Scanning loops in thread pool
    loop_thread = threading.Thread(target=run_keep_alive_loops, daemon=True)
    loop_thread.start()

    # 3. Bind FastAPI to Render's dynamic web port to keep the container exposed externally
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
