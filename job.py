"""
Standalone CronJob entrypoint — FastAPI sunucusu olmadan rapor üretir ve çıkar.
OpenShift CronJob: command: ["python", "job.py"]
"""
import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from app.core.config import settings
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key

    from app.core.database import init_db, AsyncSessionLocal
    from app.services.report_service import seed_sources, run_report

    await init_db()

    async with AsyncSessionLocal() as db:
        await seed_sources(db)

    async with AsyncSessionLocal() as db:
        report = await run_report(db)

    if report is None:
        logger.info("Yeni release yok — rapor oluşturulmadı, job başarıyla tamamlandı")
    else:
        logger.info(f"Rapor hazır: {report.id} ({len(report.release_ids)} release)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Job başarısız: {e}", exc_info=True)
        sys.exit(1)
