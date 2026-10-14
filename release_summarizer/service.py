"""İş akışı: kaynakları çek → kaydet → temizle → özetle; cron zamanlayıcı."""
import asyncio
from datetime import datetime

import httpx

from . import db, llm, sources
from .config import CHECK_CRON, CHECK_TZ, LLM_CONCURRENCY, LLM_CONFIGURED, PRODUCTS
from .cron import next_run, parse_cron

CRON = parse_cron(CHECK_CRON)  # hatalı ifade pod'u başlangıçta düşürsün
lock = asyncio.Lock()


def next_check():
    return next_run(CRON, datetime.now(CHECK_TZ))


async def summarize_release(c, row):
    summary = await llm.summarize(c, PRODUCTS.get(row["product"], {}).get("name", row["product"]), row["tag"], row["body"])
    db.save_summary(row["product"], row["tag"], summary)
    return summary


async def run_check(only=None):
    if lock.locked():
        return
    async with lock, httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        async def check_product(pid, p):
            err = None
            try:
                db.store(pid, await sources.fetch(c, p))
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
            db.record_check(pid, err)

        await asyncio.gather(*(check_product(pid, p) for pid, p in PRODUCTS.items() if not only or pid == only))
        db.cleanup()

        if LLM_CONFIGURED:
            sem = asyncio.Semaphore(LLM_CONCURRENCY)

            async def limited(row):
                async with sem:
                    await summarize_release(c, row)

            await asyncio.gather(*map(limited, db.unsummarized()))


async def resummarize(pid, tag):
    row = db.get_release(pid, tag)
    if not row:
        return None
    async with httpx.AsyncClient() as c:
        return await summarize_release(c, row)


async def scheduler():
    if not db.has_checks():
        await run_check()  # ilk kurulum: zamanını beklemeden doldur
    nxt = next_check()
    while True:
        await asyncio.sleep(max(0, (nxt - datetime.now(CHECK_TZ)).total_seconds()))
        await run_check()
        nxt = next_run(CRON, max(nxt, datetime.now(CHECK_TZ)))
