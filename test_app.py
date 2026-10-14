import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
from app import STABLE_TAG, parse_ocp, parse_summary, store, db

assert all(STABLE_TAG.match(t) for t in ["v1.2.3", "4.22.17", "v2.73.0"])
assert not any(STABLE_TAG.match(t) for t in ["v1.106.0-rc.2", "v3.6.0-ea.2", "model-catalog/latest", "v1.2.3-nightly"])

assert parse_summary('<think>hmm {x}</think>```json\n{"tldr": "ok", "urgency": "low"}\n```') == {"tldr": "ok", "urgency": "low"}
assert parse_summary("düz metin") == {"tldr": "düz metin"}

txt = "intro\nName:           4.22.17\nCreated:        2026-10-01T19:50:27Z\n  Metadata:\n    url: https://access.redhat.com/errata/RHSA-2026:74429\n\nImages:\n  cli  quay.io/x"
r = parse_ocp(txt, "src")[0]
assert (r["tag"], r["published"], r["url"]) == ("4.22.17", "2026-10-01T19:50:27Z", "https://access.redhat.com/errata/RHSA-2026:74429")
assert "Images" not in r["body"]

rel = lambda t, d: {"tag": t, "title": t, "url": "", "published": d, "body": ""}
store("x", [rel(f"v1.{i}", f"2026-01-0{i}") for i in range(1, 6)])  # ilk çalıştırma: en yeni 3, okunmuş
assert [r[0] for r in db.execute("SELECT tag FROM releases WHERE seen=1 ORDER BY tag")] == ["v1.3", "v1.4", "v1.5"]
store("x", [rel("v1.6", "2026-01-06"), rel("v1.5", "2026-01-05"), rel("v1.1", "2026-01-01")])  # sonraki: sadece yeniler, eskiler geri dolmaz
assert [r[0] for r in db.execute("SELECT tag FROM releases WHERE seen=0")] == ["v1.6"]
print("ok")

from datetime import datetime
from zoneinfo import ZoneInfo
from app import parse_cron, next_run
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
