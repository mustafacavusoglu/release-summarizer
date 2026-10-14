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
