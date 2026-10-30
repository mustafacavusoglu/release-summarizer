"""HTTP katmanı: arayüz ve REST API."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, service
from .config import CHECK_CRON, CHECK_TZ, INSTALLED, LLM_CONFIGURED, LLM_MODEL, PRODUCTS, RETENTION_PER_PRODUCT, VERSION
from .versions import TAG


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
        "products": [{"id": pid, "name": p["name"], "source": p["source"], "installed": INSTALLED.get(pid), **products[pid]}
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


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    product: str
    messages: list[Message] = Field(min_length=1)
    current: str | None = None  # kullanıcının mevcut sürümü, ör. "1.98"


@app.post("/api/chat")
async def chat(body: ChatIn):
    if not LLM_CONFIGURED:
        raise HTTPException(400, "LLM yapılandırılmamış")
    if body.product not in PRODUCTS:
        raise HTTPException(404, "Bilinmeyen ürün")
    current = (body.current or "").strip() or None
    if current and not TAG.match(current):
        raise HTTPException(400, "Sürüm biçimi geçersiz (ör. 1.98 veya v1.98.0)")
    try:
        return await service.chat(body.product, [m.model_dump() for m in body.messages[-10:]], current)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}"[:300])
