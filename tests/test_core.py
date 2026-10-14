"""Çalıştırma: python -m tests.test_core"""
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["RETENTION_PER_PRODUCT"] = "4"
from release_summarizer.versions import TAG, vkey, is_rc, pick
from release_summarizer.sources import parse_ocp
from release_summarizer.llm import parse_summary
from release_summarizer.db import store, cleanup, conn as db

assert all(TAG.match(t) for t in ["v1.2.3", "4.22.17", "v1.106.0-rc.2", "v3.13.0rc0", "v0.10.1rc1"])
assert not any(TAG.match(t) for t in ["v3.6.0-ea.2", "model-catalog/latest", "v1.2.3-nightly", "v1.106.0-dev.3", "ts/v0.2.0-rc.1"])
assert is_rc("v1.106.0-rc.2") and is_rc("v3.13.0rc0") and not is_rc("v1.105.1")
assert vkey("v1.106.0-rc.1") < vkey("v1.106.0-rc.2") < vkey("v1.106.0") < vkey("v1.106.1")
assert vkey("v1.105.1") < vkey("v1.106.0-rc.1")
assert vkey("4.22.9") < vkey("4.22.17")  # sayısal, alfabetik değil

assert parse_summary('<think>hmm {x}</think>```json\n{"tldr": "ok", "urgency": "low"}\n```') == {"tldr": "ok", "urgency": "low"}
assert parse_summary("düz metin") == {"tldr": "düz metin"}

txt = ("intro\nName:           4.22.17\nCreated:        2026-10-01T19:50:27Z\n\nRelease Metadata:\n"
       "  Version:  4.22.17\n  Upgrades: 4.21.36, 4.22.9, 4.22.16, 4.22.15\n  Metadata:\n"
       "    url: https://access.redhat.com/errata/RHSA-2026:74429\n\nImages:\n  cli  quay.io/x")
r = parse_ocp(txt, "src")
assert (r["tag"], r["published"], r["url"]) == ("4.22.17", "2026-10-01T19:50:27Z", "https://access.redhat.com/errata/RHSA-2026:74429")
assert "Images" not in r["body"]
assert sorted(r["upgrades"], key=vkey, reverse=True)[:2] == ["4.22.16", "4.22.15"]

rel = lambda t, d="2026-01-01": {"tag": t, "title": t, "url": "", "published": d, "body": ""}
tags = lambda rs: [r["tag"] for r in rs]
# yayın sırası karışık: eski hatta backport (v1.3.9) en son yayımlanmış olabilir
src = [rel("v1.5.0-rc.1"), rel("v1.4.1"), rel("v1.3.9"), rel("v1.4.0"), rel("v1.4.0-rc.2"), rel("v1.2.0"), rel("v1.5.0-dev.1")]
assert sorted(tags(pick(src, 3))) == ["v1.3.9", "v1.4.0", "v1.4.1", "v1.5.0-rc.1"]  # n'den yeni rc + n, n-1, n-2
store("x", src)  # ilk kurulum: hepsi okunmuş
assert db.execute("SELECT COUNT(*) FROM releases WHERE seen=0").fetchone()[0] == 0
store("x", src + [rel("v1.5.0"), rel("v1.5.0-rc.2")])  # stable çıktı -> yeni n; eski rc'ler eklenmez
assert [r[0] for r in db.execute("SELECT tag FROM releases WHERE seen=0")] == ["v1.5.0"]

# saklama: "x" izlenen bir ürün değil -> tamamen silinir; izlenen üründe en yeni 4 kalır, stable'ı çıkmış rc silinir
store("litellm", [rel(t) for t in ["v2.0.0-rc.1", "v1.3.0", "v1.2.0", "v1.1.0"]])
for t_ in ["v1.0.0", "v0.9.0", "v0.8.0", "v1.1.0-rc.1"]:  # zamanla birikmiş eskiler
    db.execute("INSERT INTO releases(product, tag) VALUES('litellm', ?)", (t_,))
assert cleanup() == 5 + 4  # x'in 5 kaydı + litellm'de v0.9.0, v0.8.0, v1.1.0-rc.1 ve limit dışı v1.0.0
assert sorted(r[0] for r in db.execute("SELECT tag FROM releases")) == ["v1.1.0", "v1.2.0", "v1.3.0", "v2.0.0-rc.1"]
print("ok")

from datetime import datetime
from zoneinfo import ZoneInfo
from release_summarizer.cron import parse_cron, next_run
ist = ZoneInfo("Europe/Istanbul")
at = lambda *a: datetime(*a, tzinfo=ist)
assert next_run(parse_cron("0 6 * * *"), at(2026, 10, 14, 5, 59)) == at(2026, 10, 14, 6, 0)
assert next_run(parse_cron("0 6 * * *"), at(2026, 10, 14, 6, 0)) == at(2026, 10, 15, 6, 0)   # aynı dakikada tekrar tetiklenmez
assert next_run(parse_cron("0 6 * * 1-5"), at(2026, 10, 16, 7, 0)) == at(2026, 10, 19, 6, 0)  # Cuma sonrası -> Pazartesi
assert next_run(parse_cron("*/15 * * * *"), at(2026, 10, 14, 10, 7)) == at(2026, 10, 14, 10, 15)
assert next_run(parse_cron("0 0 1 * 0"), at(2026, 10, 14, 0, 0)) == at(2026, 10, 18, 0, 0)    # gün VEYA haftanın günü (Pazar)
assert next_run(parse_cron("30 2 * * 7"), at(2026, 10, 14, 0, 0)) == at(2026, 10, 18, 2, 30)  # 7 = Pazar
for bad in ["0 6 * *", "60 * * * *", "0 6 * * 8", "x * * * *"]:
    try: parse_cron(bad); raise AssertionError(bad)
    except ValueError: pass
print("cron ok")
