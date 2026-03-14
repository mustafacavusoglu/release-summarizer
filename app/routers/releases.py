import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.db.models import Release, ReleaseRead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/releases", tags=["releases"])


@router.get("/", response_model=list[ReleaseRead])
async def list_releases(
    source_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Release).order_by(desc(Release.fetched_at)).limit(limit)
    if source_id:
        query = query.where(Release.source_id == source_id)
    result = await db.execute(query)
    return result.scalars().all()
