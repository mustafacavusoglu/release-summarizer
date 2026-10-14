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
KEEP_STABLE = 3  # n, n-1, n-2 (n = en yüksek stable sürüm)
MAX_NOTES_CHARS = 15000
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))  # aynı anda en fazla kaç özet isteği

PRODUCTS = {
    "litellm": {"name": "LiteLLM", "repo": "BerriAI/litellm"},
    "mlflow": {"name": "MLflow", "repo": "mlflow/mlflow"},
    "langfuse": {"name": "Langfuse", "repo": "langfuse/langfuse"},
    "openshift": {"name": "OpenShift", "ocp": "https://mirror.openshift.com/pub/openshift-v4/x86_64/clients/ocp"},
    # ponytail: RHOAI'nin public GitHub release'i yok, upstream Open Data Hub izleniyor
    "openshift-ai": {"name": "OpenShift AI (ODH)", "repo": "opendatahub-io/opendatahub-operator"},
    "code-server": {"name": "code-server", "repo": "coder/code-server"},
    "triton": {"name": "Triton", "repo": "triton-inference-server/server"},
    "vllm": {"name": "vLLM", "repo": "vllm-project/vllm"},
}
for p in PRODUCTS.values():
    p["source"] = f"https://github.com/{p['repo']}/releases" if "repo" in p else p["ocp"] + "/stable/release.txt"

# stable (v1.2.3) ve rc (v1.2.3-rc.1, v1.2.3rc1); dev/ea/nightly/model-catalog gibi tag'ler elenir
TAG = re.compile(r"^v?(\d+(?:\.\d+)+)(?:-?rc\.?(\d+))?$", re.I)


def vkey(tag):
    """Sürüm sıralama anahtarı: 1.106.0-rc.2 < 1.106.0 < 1.106.1"""
    m = TAG.match(tag)
    return tuple(map(int, m[1].split("."))), m[2] is None, int(m[2] or 0)


def is_rc(tag):
    return TAG.match(tag)[2] is not None


def pick(rels):
    """n, n-1, n-2 stable + n'den yeni rc'ler."""
    rels = sorted((r for r in rels if TAG.match(r["tag"])), key=lambda r: vkey(r["tag"]), reverse=True)
    stable = [r for r in rels if not is_rc(r["tag"])][:KEEP_STABLE]
    n = vkey(stable[0]["tag"]) if stable else ((0,), True, 0)
    return [r for r in rels if is_rc(r["tag"]) and vkey(r["tag"]) > n] + stable

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
    r = await c.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 50}, headers=headers)
    r.raise_for_status()
    return [
        {"tag": x["tag_name"], "title": x["name"] or x["tag_name"], "url": x["html_url"],
         "published": x["published_at"], "body": x["body"] or ""}
        for x in r.json()
        if not x["draft"]
    ]


def parse_ocp(text, source):
    head = text.split("\nImages:")[0]
    name = re.search(r"^Name:\s+(\S+)", head, re.M)
    if not name:
        raise ValueError("release.txt içinde 'Name:' bulunamadı")
    created = re.search(r"^Created:\s+(\S+)", head, re.M)
    errata = re.search(r"url:\s+(https://\S+)", head)
    upgrades = re.search(r"^\s*Upgrades:\s*(.+)$", head, re.M)
    return {"tag": name[1], "title": f"OpenShift {name[1]}", "url": errata[1] if errata else source,
            "published": created[1] if created else now(), "body": head[name.start():].strip(),
            "upgrades": [v for v in re.split(r",\s*", upgrades[1].strip()) if TAG.match(v)] if upgrades else []}


async def fetch_ocp(c, mirror):
    async def get(ver):
        url = f"{mirror}/{ver}/release.txt"
        r = await c.get(url)
        r.raise_for_status()
        return parse_ocp(r.text, url)
    n = await get("stable")
    # n-1, n-2: n'e yükseltilebilen sürümler (stable kanalın önceki z-stream'leri)
    prev = sorted(n["upgrades"], key=vkey, reverse=True)[:KEEP_STABLE - 1]
    return [n, *await asyncio.gather(*map(get, prev))]


def store(pid, rels):
    first = not db.execute("SELECT 1 FROM releases WHERE product=?", (pid,)).fetchone()
    for r in pick(rels):
        db.execute(
            "INSERT OR IGNORE INTO releases(product,tag,title,url,published,body,seen,found_at) VALUES(?,?,?,?,?,?,?,?)",
            (pid, r["tag"], r["title"], r["url"], r["published"], r["body"], int(first), now()))
    db.commit()


PROMPT = """Bir MLOps ekibi için aşağıdaki sürüm notlarını Türkçe özetle.
Ürün: {name} {tag}{rc_note}

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
                           rc_note=" (release candidate: stable öncesi aday sürüm, bunu özette belirt)" if is_rc(row["tag"]) else "",
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
        async def check_product(pid, p):
            err = None
            try:
                store(pid, await (fetch_github(c, p["repo"]) if "repo" in p else fetch_ocp(c, p["ocp"])))
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
            db.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?)", (pid, now(), err))
            db.commit()

        await asyncio.gather(*(check_product(pid, p) for pid, p in PRODUCTS.items() if not only or pid == only))

        if LLM_BASE_URL and LLM_MODEL:
            sem = asyncio.Semaphore(LLM_CONCURRENCY)

            async def limited(row):
                async with sem:
                    await summarize(c, row)

            rows = db.execute("SELECT * FROM releases WHERE summary IS NULL ORDER BY published DESC").fetchall()
            await asyncio.gather(*map(limited, rows))


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
    tags = {}
    for r in db.execute("SELECT product, tag FROM releases"):
        tags.setdefault(r["product"], []).append(r["tag"])
    for pid, ts in tags.items():
        ts.sort(key=vkey, reverse=True)
        stable = [t for t in ts if not is_rc(t)][:KEEP_STABLE]
        rc = [t for t in ts if is_rc(t) and (not stable or vkey(t) > vkey(stable[0]))]
        tags[pid] = {"stable": stable, "rc": rc[0] if rc else None}
    pending = db.execute("SELECT COUNT(*) FROM releases WHERE summary IS NULL").fetchone()[0]
    return {
        "version": VERSION,
        "llm": {"configured": bool(LLM_BASE_URL and LLM_MODEL), "model": LLM_MODEL},
        "running": lock.locked(), "pending": pending,
        "schedule": {"cron": CHECK_CRON, "timezone": str(CHECK_TZ),
                     "next": next_run(CRON, datetime.now(CHECK_TZ)).isoformat()},
        "products": [{
            "id": pid, "name": p["name"], "source": p["source"], **tags.get(pid, {"stable": [], "rc": None}),
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
