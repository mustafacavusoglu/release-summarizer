import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.services.report_service import seed_sources
from app.routers import sources, releases, reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

os.environ["OPENAI_API_KEY"] = settings.openai_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
    logger.info(f"Uygulama başlatıldı | Model: {settings.model}")
    yield
    logger.info("Uygulama kapatıldı")


app = FastAPI(
    title="Release Monitor",
    description="Teknoloji sürümlerini takip eden ve özet e-posta hazırlayan servis",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(sources.router)
app.include_router(releases.router)
app.include_router(reports.router)


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.model}
