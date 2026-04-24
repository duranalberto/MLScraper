import json
import logging
import os
import time as _time
from typing import List, Any

from uvicorn import run as uvicorn_run
from asyncio import create_task as asyncio_create_task
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from scrapper import Scrapper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_TOKEN = os.environ.get("MLSCRAPER_TOKEN", "").strip()
_bearer = HTTPBearer(auto_error=False)

if not _TOKEN:
    logger.critical(
        "MLSCRAPER_TOKEN is not set. /api/search and /ws/ are UNPROTECTED. "
        "Set the environment variable before deploying to production."
    )


def _verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """Dependency: raises 401 when a token is configured and the request lacks it."""
    if not _TOKEN:
        return
    if credentials is None or credentials.credentials != _TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _verify_ws_token(token: str | None) -> bool:
    """Returns True when auth passes for WebSocket connections."""
    if not _TOKEN:
        return True
    return token == _TOKEN


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()   # FIX 7: serialise list mutations

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info("Client connected. Total: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info("Client disconnected.")

    async def broadcast(self, data: Any):
        message = json.dumps(data) if isinstance(data, (dict, list)) else str(data)

        async with self._lock:
            snapshot = list(self.active_connections)

        dead: List[WebSocket] = []
        for connection in snapshot:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)

        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self.active_connections:
                        self.active_connections.remove(ws)


connection_manager = ConnectionManager()
scrapper = Scrapper(connection_manager.broadcast)


_health: dict = {
    "status": "starting",
    "last_cycle_finished_at": None,
    "last_cycle_duration_s": None,
    "motor_count": len(scrapper.motors),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    scraping_task = asyncio_create_task(scrapper.run())
    logger.info("Scrapper background task started.")
    yield
    scraping_task.cancel()
    logger.info("Lifespan shutdown: Scrapper task cancelled.")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    """
    Liveness + readiness probe.
    Returns 200 once the scraper is running.
    Returns 503 while still in 'starting' state so orchestrators can gate traffic.
    """
    if _health["status"] == "starting":
        raise HTTPException(status_code=503, detail="Scraper not yet initialised.")
    return _health


@app.get("/api/search", dependencies=[Depends(_verify_token)])
async def search():
    return scrapper.get_list()


@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not _verify_ws_token(token):
        await websocket.close(code=1008)
        logger.warning("WebSocket connection rejected — invalid token.")
        return

    await connection_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        await connection_manager.disconnect(websocket)

_original_run = scrapper.run.__func__  # type: ignore[attr-defined]


async def _instrumented_run(self):
    """Thin wrapper around Scrapper.run() that updates _health after each cycle."""
    import asyncio as _asyncio
    from time import time as _t

    if not self.motors:
        _health["status"] = "idle_no_motors"
        while True:
            await _asyncio.sleep(3600)

    _health["status"] = "running"
    backoff = 30
    _BACKOFF_MAX = 3600

    while True:
        start = _t()
        try:
            await _asyncio.gather(*[self._scrape_with_limit(m) for m in self.motors])
            duration = _t() - start
            _health.update({
                "status": "ok",
                "last_cycle_finished_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "last_cycle_duration_s": round(duration, 2),
            })
            backoff = 30
            await self._broadcast_scrape_finished(f"Scraping cycle finished in {duration:.2f}s.")
        except Exception as exc:
            _health["status"] = "error"
            logger.error("Scraping cycle error: %s", exc)
            await _asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            continue

        await _asyncio.sleep(self.sleep_time)


import types
scrapper.run = types.MethodType(_instrumented_run, scrapper)


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn_run(app, host="0.0.0.0", port=80)