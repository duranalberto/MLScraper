import logging
from argparse import ArgumentParser
from pathlib import Path

from uvicorn import run as uvicorn_run
from asyncio import create_task as asyncio_create_task
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from scraper.jobs.loader import DEFAULT_CONFIG_PATH
from scraper.runtime.url_preview import preview_job_url
from scraper.runtime.orchestrator import Scrapper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


scrapper: Scrapper | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scrapper
    scrapper = Scrapper()
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
    if scrapper is None or scrapper.health["status"] == "starting":
        raise HTTPException(status_code=503, detail="Scraper not yet initialised.")
    return scrapper.health


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="MLScraper service and utilities.")
    subparsers = parser.add_subparsers(dest="command")

    preview = subparsers.add_parser(
        "preview-url",
        help="Generate one job URL from config/jobs.yaml without running the scraper.",
    )
    preview.add_argument("--provider", required=True, choices=("ml", "az", "lv", "ph"))
    preview.add_argument("--job-id", required=True)
    preview.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "preview-url":
        print(
            preview_job_url(
                job_id=args.job_id,
                provider=args.provider,
                config_path=Path(args.config),
            )
        )
    else:
        uvicorn_run(app, host="0.0.0.0", port=80)
