import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from polisense_core.utils.logger import LOGGING_CONFIG
from polisense_core.api.routers import discovery

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    logger.info("PoliSense API starting — warming up embedding model...")
    from polisense_core.utils.postgres_utils import embed_documents
    await asyncio.to_thread(embed_documents, ["warmup"])
    logger.info("Embedding model ready.")
    yield


app = FastAPI(
    title="PoliSense API",
    version="1.1.0",
    description="Discovery pipeline webhook endpoint for Zoho form submissions.",
    lifespan=lifespan,
)

app.include_router(discovery.router)
