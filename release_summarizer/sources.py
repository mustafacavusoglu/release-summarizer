"""Release kaynakları: GitHub Releases ve OpenShift mirror (release.txt)."""
import asyncio
import re

from .config import GITHUB_TOKEN, KEEP_STABLE
from .versions import TAG, vkey


async def fetch(c, product):
    return await (fetch_github(c, product["repo"]) if "repo" in product else fetch_ocp(c, product["ocp"]))


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
            "published": created[1] if created else None, "body": head[name.start():].strip(),
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
