import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.db.models import Report, ReportRead
from app.services.report_service import run_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=ReportRead, status_code=201)
async def generate_report(db: AsyncSession = Depends(get_db)):
    """
    Tüm aktif kaynakların son release'lerini çeker, özetler ve HTML e-posta oluşturur.
    Yeni release yoksa o kaynak için OpenAI çağrısı yapılmaz.
    """
    report = await run_report(db)
    if report is None:
        raise HTTPException(status_code=204, detail="Yeni release yok, rapor oluşturulmadı")
    return report


@router.get("/", response_model=list[ReportRead])
async def list_reports(limit: int = 10, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).order_by(desc(Report.created_at)).limit(limit))
    return result.scalars().all()


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(report_id: str, db: AsyncSession = Depends(get_db)):
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı")
    return report


@router.get("/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(report_id: str, db: AsyncSession = Depends(get_db)):
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı")
    return report.content
