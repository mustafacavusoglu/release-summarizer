"""Release Summarizer: MLOps ürünlerinin release'lerini takip edip LLM ile özetler."""
import asyncio
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse

VERSION = "0.0.1"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")  # OpenAI uyumlu, ör. http://litellm:4000/v1
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # opsiyonel; token'sız limit 60 istek/saat
DB_PATH = os.getenv("DB_PATH", "data/releases.db")
CHECK_CRON = os.getenv("CHECK_CRON", "0 6 * * *")  # dakika saat gün ay haftanın-günü
CHECK_TZ = ZoneInfo(os.getenv("CHECK_TIMEZONE", "Europe/Istanbul"))
SEED_PER_PRODUCT = 3  # ilk çalıştırmada ürün başına alınacak geçmiş release sayısı
MAX_NOTES_CHARS = 15000

PRODUCTS = {
    "litellm": {"name": "LiteLLM", "repo": "BerriAI/litellm"},
    "mlflow": {"name": "MLflow", "repo": "mlflow/mlflow"},
    "langfuse": {"name": "Langfuse", "repo": "langfuse/langfuse"},
    "openshift": {"name": "OpenShift", "ocp": "https://mirror.openshift.com/pub/openshift-v4/x86_64/clients/ocp/stable/release.txt"},
    # ponytail: RHOAI'nin public GitHub release'i yok, upstream Open Data Hub izleniyor
    "openshift-ai": {"name": "OpenShift AI (ODH)", "repo": "opendatahub-io/opendatahub-operator"},
    "code-server": {"name": "code-server", "repo": "coder/code-server"},
    "triton": {"name": "Triton", "repo": "triton-inference-server/server"},
    "vllm": {"name": "vLLM", "repo": "vllm-project/vllm"},
}
for p in PRODUCTS.values():
    p["source"] = f"https://github.com/{p['repo']}/releases" if "repo" in p else p["ocp"]

STABLE_TAG = re.compile(r"^v?\d+(\.\d+)+$")  # rc/ea/nightly/model-catalog gibi tag'leri eler

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS releases(
  product TEXT, tag TEXT, title TEXT, url TEXT, published TEXT, body TEXT,
  summary TEXT, seen INTEGER DEFAULT 0, found_at TEXT, PRIMARY KEY(product, tag));
CREATE TABLE IF NOT EXISTS checks(product TEXT PRIMARY KEY, checked_at TEXT, error TEXT);
""")
lock = asyncio.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cron_field(spec, lo, hi):
    vals = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = map(int, rng.split("-"))
        else:
            a = b = int(rng)
            if step:  # "5/15" = 5'ten başlayıp 15'er
                b = hi
        vals.update(range(a, b + 1, int(step or 1)))
    if not vals or min(vals) < lo or max(vals) > hi:
        raise ValueError(f"Geçersiz cron alanı: {spec!r}")
    return vals


def parse_cron(expr):
    f = expr.split()
    if len(f) != 5:
        raise ValueError(f"Cron 5 alanlı olmalı (dakika saat gün ay haftanın-günü): {expr!r}")
    minute, hour, dom, month, dow = (_cron_field(s, lo, hi) for s, (lo, hi) in
                                     zip(f, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]))
    return minute, hour, dom, month, {d % 7 for d in dow}, f[2] != "*" and f[4] != "*"


def next_run(cron, after):
    minute, hour, dom, month, dow, either_day = cron
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):  # ponytail: dakika dakika tarama, en kötü ~0.5 sn; yeter
        d, w = t.day in dom, t.isoweekday() % 7 in dow
        if t.minute in minute and t.hour in hour and t.month in month and ((d or w) if either_day else (d and w)):
            return t
        t += timedelta(minutes=1)
    raise ValueError("Cron bir yıl içinde hiç tetiklenmiyor")


CRON = parse_cron(CHECK_CRON)  # hatalı ifade pod'u başlangıçta düşürsün


async def fetch_github(c, repo):
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    r = await c.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 30}, headers=headers)
    r.raise_for_status()
    return [
        {"tag": x["tag_name"], "title": x["name"] or x["tag_name"], "url": x["html_url"],
         "published": x["published_at"], "body": x["body"] or ""}
        for x in r.json()
        if not x["draft"] and not x["prerelease"] and STABLE_TAG.match(x["tag_name"])
    ]


def parse_ocp(text, source):
    head = text.split("\nImages:")[0]
    name = re.search(r"^Name:\s+(\S+)", head, re.M)
    if not name:
        raise ValueError("release.txt içinde 'Name:' bulunamadı")
    created = re.search(r"^Created:\s+(\S+)", head, re.M)
    errata = re.search(r"url:\s+(https://\S+)", head)
    return [{"tag": name[1], "title": f"OpenShift {name[1]}", "url": errata[1] if errata else source,
             "published": created[1] if created else now(), "body": head[name.start():].strip()}]


async def fetch_ocp(c, url):
    r = await c.get(url)
    r.raise_for_status()
    return parse_ocp(r.text, url)


def store(pid, rels):
    rels.sort(key=lambda r: r["published"] or "", reverse=True)
    cutoff = db.execute("SELECT MAX(published) FROM releases WHERE product=?", (pid,)).fetchone()[0]
    first = cutoff is None
    for r in rels[:SEED_PER_PRODUCT] if first else [r for r in rels if (r["published"] or "") > cutoff]:
        db.execute(
            "INSERT OR IGNORE INTO releases(product,tag,title,url,published,body,seen,found_at) VALUES(?,?,?,?,?,?,?,?)",
            (pid, r["tag"], r["title"], r["url"], r["published"], r["body"], int(first), now()))
    db.commit()


PROMPT = """Bir MLOps ekibi için aşağıdaki sürüm notlarını Türkçe özetle.
Ürün: {name} {tag}

YALNIZCA şu şemada geçerli JSON döndür, başka metin yazma:
{{"tldr": "tek cümlelik özet",
  "highlights": ["öne çıkan yenilik/değişiklik (en fazla 6)"],
  "breaking": ["geriye uyumsuz değişiklik, kaldırılan özellik, migration gereksinimi"],
  "security": ["güvenlik düzeltmesi / CVE"],
  "urgency": "low | medium | high",
  "urgency_reason": "neden bu aciliyet, tek cümle"}}
urgency: güvenlik açığı veya kritik hata düzeltmesi varsa high, breaking change veya önemli özellik varsa medium, diğerleri low.
Boş kategoriler için [] kullan. Katkıda bulunan listelerini ve PR numaralarını özetleme.

Sürüm notları:
{notes}"""


def parse_summary(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {"tldr": text.strip()}


async def summarize(c, row):
    prompt = PROMPT.format(name=PRODUCTS[row["product"]]["name"], tag=row["tag"],
                           notes=(row["body"] or "(not yok)")[:MAX_NOTES_CHARS])
    try:
        r = await c.post(f"{LLM_BASE_URL}/chat/completions", timeout=300,
                         headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                         json={"model": LLM_MODEL, "temperature": 0.2,
                               "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        summary = parse_summary(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        summary = {"error": f"{type(e).__name__}: {e}"[:300]}
    db.execute("UPDATE releases SET summary=? WHERE product=? AND tag=?",
               (json.dumps(summary, ensure_ascii=False), row["product"], row["tag"]))
    db.commit()
    return summary


async def run_check(only=None):
    if lock.locked():
        return
    async with lock, httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        for pid, p in PRODUCTS.items():
            if only and pid != only:
                continue
            err = None
            try:
                store(pid, await (fetch_github(c, p["repo"]) if "repo" in p else fetch_ocp(c, p["ocp"])))
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
            db.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?)", (pid, now(), err))
            db.commit()
        if LLM_BASE_URL and LLM_MODEL:
            for row in db.execute("SELECT * FROM releases WHERE summary IS NULL ORDER BY published DESC").fetchall():
                await summarize(c, row)


async def scheduler():
    if not db.execute("SELECT 1 FROM checks").fetchone():
        await run_check()  # ilk kurulum: zamanını beklemeden doldur
    nxt = next_run(CRON, datetime.now(CHECK_TZ))
    while True:
        await asyncio.sleep(max(0, (nxt - datetime.now(CHECK_TZ)).total_seconds()))
        await run_check()
        nxt = next_run(CRON, max(nxt, datetime.now(CHECK_TZ)))


@asynccontextmanager
async def lifespan(_):
    task = asyncio.create_task(scheduler())
    yield
    task.cancel()


app = FastAPI(title="Release Summarizer", version=VERSION, lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static/index.html")


@app.get("/api/state")
def state():
    checks = {r["product"]: dict(r) for r in db.execute("SELECT * FROM checks")}
    stats = {r["product"]: dict(r) for r in db.execute(
        "SELECT product, SUM(1-seen) unseen, COUNT(*) total FROM releases GROUP BY product")}
    latest = {r["product"]: r["tag"] for r in db.execute(
        "SELECT product, tag, MAX(published) FROM releases GROUP BY product")}
    pending = db.execute("SELECT COUNT(*) FROM releases WHERE summary IS NULL").fetchone()[0]
    return {
        "version": VERSION,
        "llm": {"configured": bool(LLM_BASE_URL and LLM_MODEL), "model": LLM_MODEL},
        "running": lock.locked(), "pending": pending,
        "schedule": {"cron": CHECK_CRON, "timezone": str(CHECK_TZ),
                     "next": next_run(CRON, datetime.now(CHECK_TZ)).isoformat()},
        "products": [{
            "id": pid, "name": p["name"], "source": p["source"], "latest": latest.get(pid),
            "unseen": (stats.get(pid) or {}).get("unseen", 0),
            "checked_at": (checks.get(pid) or {}).get("checked_at"),
            "error": (checks.get(pid) or {}).get("error"),
        } for pid, p in PRODUCTS.items()],
    }


@app.get("/api/releases")
def releases():
    rows = db.execute("SELECT * FROM releases ORDER BY published DESC LIMIT 500").fetchall()
    return [{**dict(r), "summary": json.loads(r["summary"]) if r["summary"] else None} for r in rows]


@app.post("/api/check", status_code=202)
def check(bg: BackgroundTasks, product: str | None = None):
    if product and product not in PRODUCTS:
        raise HTTPException(404, "Bilinmeyen ürün")
    bg.add_task(run_check, product)
    return {"started": not lock.locked()}


@app.post("/api/seen")
def mark_seen(product: str | None = None, tag: str | None = None):
    db.execute("UPDATE releases SET seen=1 WHERE (?1 IS NULL OR product=?1) AND (?2 IS NULL OR tag=?2)", (product, tag))
    db.commit()
    return {"ok": True}


@app.post("/api/summarize")
async def resummarize(product: str, tag: str):
    if not (LLM_BASE_URL and LLM_MODEL):
        raise HTTPException(400, "LLM yapılandırılmamış")
    row = db.execute("SELECT * FROM releases WHERE product=? AND tag=?", (product, tag)).fetchone()
    if not row:
        raise HTTPException(404, "Release bulunamadı")
    async with httpx.AsyncClient() as c:
        return await summarize(c, row)
