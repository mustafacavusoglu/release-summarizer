"""
FastAPI'den bağımsız core iş mantığı.
Hem API router'ı hem de standalone CronJob (job.py) tarafından kullanılır.
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Source, Release, Report
from app.db.seeds import DEFAULT_SOURCES
from app.agents.release_agents import fetch_and_summarize_source, compose_email

logger = logging.getLogger(__name__)


async def seed_sources(db: AsyncSession) -> None:
    """Varsayılan kaynakları DB'ye ekler (idempotent)."""
    for source in DEFAULT_SOURCES:
        data = source.to_dict()
        existing = await db.execute(select(Source).where(Source.slug == data["slug"]))
        if existing.scalar_one_or_none() is None:
            db.add(Source(**data))
    await db.commit()
    logger.info("Varsayılan kaynaklar yüklendi")


async def get_known_versions(db: AsyncSession, source_ids: list[str]) -> dict[str, str]:
    """
    Her kaynak için DB'deki en son bilinen latest release versiyonunu döner.
    summary IS NOT NULL filtresi — latest release'e summary yazılır, eski sürümlerle karışmaz.
    """
    latest_subq = (
        select(Release.source_id, func.max(Release.fetched_at).label("latest_fetched"))
        .where(Release.source_id.in_(source_ids))
        .where(Release.summary.is_not(None))
        .group_by(Release.source_id)
        .subquery()
    )
    rows = await db.execute(
        select(Release.source_id, Release.version)
        .join(latest_subq,
              (Release.source_id == latest_subq.c.source_id) &
              (Release.fetched_at == latest_subq.c.latest_fetched))
    )
    return {row.source_id: row.version for row in rows}


async def run_report(db: AsyncSession) -> Report | None:
    """
    Tüm aktif kaynakları paralel çeker, özetler, HTML rapor oluşturur ve kaydeder.
    Yeni release yoksa o kaynak OpenAI çağrısı yapmaz.
    Hiç yeni release yoksa None döner.
    """
    result = await db.execute(select(Source).where(Source.enabled == True))
    sources = result.scalars().all()

    if not sources:
        logger.warning("Aktif kaynak bulunamadı")
        return None

    source_dicts = [
        {"id": s.id, "slug": s.slug, "name": s.name, "source_type": s.source_type, "config": s.config}
        for s in sources
    ]

    known_versions = await get_known_versions(db, [s["id"] for s in source_dicts])

    async def _timed(source: dict):
        return await asyncio.wait_for(
            fetch_and_summarize_source(source, known_version=known_versions.get(source["id"])),
            timeout=settings.source_timeout,
        )

    results = await asyncio.gather(*[_timed(s) for s in source_dicts], return_exceptions=True)
    summaries = [r for r in results if r is not None and not isinstance(r, BaseException)]

    if not summaries:
        logger.info("Yeni release yok, rapor oluşturulmadı")
        return None

    saved_release_ids = []
    for result_data in summaries:
        source = next(s for s in source_dicts if s["id"] == result_data["source_id"])
        for raw in result_data["releases"]:
            published_at = None
            if raw.get("published_at"):
                try:
                    published_at = datetime.fromisoformat(raw["published_at"].replace("Z", "+00:00"))
                except ValueError:
                    pass

            release = Release(
                source_id=source["id"],
                source_name=source["name"],
                version=raw["tag_name"],
                title=raw.get("name"),
                body=raw.get("body"),
                summary=result_data["summary"] if raw["tag_name"] == result_data["latest_version"] else None,
                url=raw.get("html_url"),
                published_at=published_at,
            )
            db.add(release)
            await db.flush()
            saved_release_ids.append(release.id)

    logger.info(f"{len(summaries)}/{len(source_dicts)} kaynaktan özet alındı, e-posta oluşturuluyor...")
    email_html = await compose_email(summaries)

    report = Report(content=email_html, release_ids=saved_release_ids)
    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info(f"Rapor oluşturuldu: {report.id}")
    return report
