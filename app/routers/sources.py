import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.db.models import Source, SourceCreate, SourceRead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/", response_model=list[SourceRead])
async def list_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Source).order_by(Source.created_at))
    return result.scalars().all()


@router.post("/", response_model=SourceRead, status_code=201)
async def create_source(payload: SourceCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Source).where(Source.slug == payload.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"'{payload.slug}' slug'ı zaten mevcut")

    source = Source(**payload.model_dump())
    db.add(source)
    await db.commit()
    await db.refresh(source)
    logger.info(f"Yeni kaynak eklendi: {source.slug}")
    return source


@router.patch("/{source_id}/toggle", response_model=SourceRead)
async def toggle_source(source_id: str, db: AsyncSession = Depends(get_db)):
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı")
    source.enabled = not source.enabled
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı")
    await db.delete(source)
    await db.commit()
