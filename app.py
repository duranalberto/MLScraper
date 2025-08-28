import json
import logging
from typing import List, Any
from uvicorn import run as uvicorn_run
from asyncio import create_task as asyncio_create_task
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from scrapper import Scrapper

# Setup logging instead of print for production readiness
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepts connection and adds to registry."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Removes connection from registry."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("Client disconnected.")

    async def broadcast(self, data: Any):
        """Broadcasts data as JSON to all active clients."""
        # Convert to string if it's a dict/list
        message = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
        
        # Iterate over a copy to prevent errors if a client disconnects during loop
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except (WebSocketDisconnect, Exception):
                self.disconnect(connection)

connection_manager = ConnectionManager()
scrapper = Scrapper(connection_manager.broadcast)



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background scraping task
    scraping_task = asyncio_create_task(scrapper.run())
    logger.info("Scrapper background task started.")
    
    yield
    
    # Graceful shutdown
    scraping_task.cancel()
    logger.info("Lifespan shutdown: Scrapper task cancelled.")

app = FastAPI(lifespan=lifespan)

@app.get("/api/search")
async def search():
    # Recommended to use async def even if internal logic is sync 
    # for consistent FastAPI behavior
    return scrapper.get_list()

@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    try:
        while True:
            # We keep the connection open and listen for incoming messages (pings/config)
            data = await websocket.receive_text()
            # Handle incoming client messages here if needed
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Websocket error: {e}")
        connection_manager.disconnect(websocket)

# Mount static files (ensure 'static' folder exists)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    # Note: host 0.0.0.0 is correct for Docker/Cloud, port 80 requires root on Linux
    uvicorn_run(app, host="0.0.0.0", port=80)