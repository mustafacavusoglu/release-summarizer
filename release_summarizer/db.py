"""SQLite kalıcı katman. Dosya: DB_PATH (OpenShift'te /data/releases.db, PVC üzerinde)."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, KEEP_STABLE, PRODUCTS, RETENTION_PER_PRODUCT
from .versions import pick, split

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.executescript("""
CREATE TABLE IF NOT EXISTS releases(
  product TEXT, tag TEXT, title TEXT, url TEXT, published TEXT, body TEXT,
  summary TEXT, seen INTEGER DEFAULT 0, found_at TEXT, PRIMARY KEY(product, tag));
CREATE TABLE IF NOT EXISTS checks(product TEXT PRIMARY KEY, checked_at TEXT, error TEXT);
""")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tags_by_product():
    out = {}
    for r in conn.execute("SELECT product, tag FROM releases"):
        out.setdefault(r["product"], []).append(r["tag"])
    return out


def store(pid, rels):
    """İzlenecek sürümleri ekler; ilk kurulumdakiler okunmuş sayılır."""
    first = not conn.execute("SELECT 1 FROM releases WHERE product=?", (pid,)).fetchone()
    conn.executemany(
        "INSERT OR IGNORE INTO releases(product,tag,title,url,published,body,seen,found_at) VALUES(?,?,?,?,?,?,?,?)",
        [(pid, r["tag"], r["title"], r["url"], r["published"], r["body"], int(first), now())
         for r in pick(rels, KEEP_STABLE)])
    conn.commit()


def record_check(pid, error):
    conn.execute("INSERT OR REPLACE INTO checks VALUES(?,?,?)", (pid, now(), error))
    conn.commit()


def has_checks():
    return conn.execute("SELECT 1 FROM checks").fetchone() is not None


def cleanup():
    """Ürün başına en yeni RETENTION_PER_PRODUCT sürüm kalır.
    Stable'ı çıkmış rc'ler ve artık izlenmeyen ürünlerin kayıtları silinir. Silinen sayıyı döner."""
    doomed = []
    for pid, tags in _tags_by_product().items():
        stable, rcs = split(tags) if pid in PRODUCTS else ([], [])
        keep = set((rcs + stable)[:RETENTION_PER_PRODUCT])
        doomed += [(pid, t) for t in tags if t not in keep]
    conn.executemany("DELETE FROM releases WHERE product=? AND tag=?", doomed)
    conn.executemany("DELETE FROM checks WHERE product=?", [(p,) for p in {p for p, _ in doomed} - PRODUCTS.keys()])
    conn.commit()
    return len(doomed)


def unsummarized():
    return conn.execute("SELECT * FROM releases WHERE summary IS NULL ORDER BY published DESC").fetchall()


def save_summary(pid, tag, summary):
    conn.execute("UPDATE releases SET summary=? WHERE product=? AND tag=?",
                 (json.dumps(summary, ensure_ascii=False), pid, tag))
    conn.commit()


def get_release(pid, tag):
    return conn.execute("SELECT * FROM releases WHERE product=? AND tag=?", (pid, tag)).fetchone()


def list_releases(limit=500):
    rows = conn.execute("SELECT * FROM releases ORDER BY published DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "summary": json.loads(r["summary"]) if r["summary"] else None} for r in rows]


def mark_seen(pid=None, tag=None):
    conn.execute("UPDATE releases SET seen=1 WHERE (?1 IS NULL OR product=?1) AND (?2 IS NULL OR tag=?2)", (pid, tag))
    conn.commit()


def product_state():
    """Ürün başına: n..n-2, en yeni rc, okunmamış sayısı, son kontrol."""
    checks = {r["product"]: dict(r) for r in conn.execute("SELECT * FROM checks")}
    unseen = dict(conn.execute("SELECT product, SUM(1-seen) FROM releases GROUP BY product").fetchall())
    tags = _tags_by_product()
    out = {}
    for pid in PRODUCTS:
        stable, rcs = split(tags.get(pid, []))
        c = checks.get(pid, {})
        out[pid] = {"stable": stable[:KEEP_STABLE], "rc": rcs[0] if rcs else None, "unseen": unseen.get(pid, 0),
                    "checked_at": c.get("checked_at"), "error": c.get("error")}
    return out


def pending_count():
    return conn.execute("SELECT COUNT(*) FROM releases WHERE summary IS NULL").fetchone()[0]
