import logging

from uvicorn import run as uvicorn_run
from asyncio import create_task as asyncio_create_task
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from scraper.runtime.orchestrator import Scrapper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


scrapper = Scrapper()


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
    if scrapper.health["status"] == "starting":
        raise HTTPException(status_code=503, detail="Scraper not yet initialised.")
    return scrapper.health


if __name__ == "__main__":
    uvicorn_run(app, host="0.0.0.0", port=80)
