"""HTTP katmanı: arayüz ve REST API."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import db, service
from .config import CHECK_CRON, CHECK_TZ, LLM_CONFIGURED, LLM_MODEL, PRODUCTS, RETENTION_PER_PRODUCT, VERSION


@asynccontextmanager
async def lifespan(_):
    task = asyncio.create_task(service.scheduler())
    yield
    task.cancel()


app = FastAPI(title="Release Summarizer", version=VERSION, lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static/index.html")


@app.get("/api/state")
def state():
    products = db.product_state()
    return {
        "version": VERSION,
        "llm": {"configured": LLM_CONFIGURED, "model": LLM_MODEL},
        "running": service.lock.locked(), "pending": db.pending_count(),
        "retention": RETENTION_PER_PRODUCT,
        "schedule": {"cron": CHECK_CRON, "timezone": str(CHECK_TZ), "next": service.next_check().isoformat()},
        "products": [{"id": pid, "name": p["name"], "source": p["source"], **products[pid]}
                     for pid, p in PRODUCTS.items()],
    }


@app.get("/api/releases")
def releases():
    return db.list_releases()


@app.post("/api/check", status_code=202)
def check(bg: BackgroundTasks, product: str | None = None):
    if product and product not in PRODUCTS:
        raise HTTPException(404, "Bilinmeyen ürün")
    bg.add_task(service.run_check, product)
    return {"started": not service.lock.locked()}


@app.post("/api/seen")
def mark_seen(product: str | None = None, tag: str | None = None):
    db.mark_seen(product, tag)
    return {"ok": True}


@app.post("/api/summarize")
async def resummarize(product: str, tag: str):
    if not LLM_CONFIGURED:
        raise HTTPException(400, "LLM yapılandırılmamış")
    summary = await service.resummarize(product, tag)
    if summary is None:
        raise HTTPException(404, "Release bulunamadı")
    return summary
