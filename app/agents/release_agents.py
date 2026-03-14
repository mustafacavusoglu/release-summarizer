import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Optional

import httpx
from agents import Agent, Runner

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 3000


def _build_http_client() -> httpx.AsyncClient:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"
    return httpx.AsyncClient(
        headers=headers,
        timeout=15,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


http_client = _build_http_client()

# OpenAI paralel çağrı limiti — modül ilk import edildiğinde event loop hazır olduğu için güvenli
_openai_sem: asyncio.Semaphore | None = None


def _get_openai_sem() -> asyncio.Semaphore:
    """Semaphore'u ilk kullanımda oluşturur (event loop garantisi için lazy init)."""
    global _openai_sem
    if _openai_sem is None:
        _openai_sem = asyncio.Semaphore(settings.max_concurrent_ai)
    return _openai_sem


# --- Agents ---

summarizer_agent = Agent(
    name="ReleaseSummarizer",
    model=settings.model,
    instructions="""
Sen bir teknik release özeti yazarısın. Verilen teknolojinin release notlarını Türkçe olarak özetle.

Şunları vurgula:
- Yeni özellikler
- Breaking changes
- Önemli bug düzeltmeleri
- Sürüm numarası ve tarihi

200 kelimeyi geçme. Sade, teknik ve bilgilendirici bir dil kullan.
""",
)

email_composer_agent = Agent(
    name="EmailComposer",
    model=settings.model,
    instructions="""
Sen bir teknik bülten yazarısın. Verilen teknoloji sürüm özetlerinden profesyonel bir HTML e-posta oluştur.

Formatı şu şekilde yap:
- Başlık: "Teknoloji Sürüm Özeti - [Tarih]"
- Her teknoloji için ayrı bir bölüm (h2 başlığı, özet, sürüm linki)
- Temiz, okunabilir HTML
- Footer'da oluşturulma tarihi

Sadece HTML döndür, başka bir şey ekleme.
""",
)


# --- Fetch ---

async def fetch_github_releases(repo: str, per_page: int = 5) -> list[dict]:
    """
    GitHub repo'sunun son sürümlerini paylaşımlı client ile çeker.
    429 rate-limit durumunda exponential backoff ile 3 deneme yapar.
    """
    url = f"https://api.github.com/repos/{repo}/releases"

    for attempt in range(3):
        response = await http_client.get(url, params={"per_page": per_page})

        if response.status_code == 429:
            wait = 2 ** attempt
            logger.warning(f"[{repo}] GitHub rate limit (429), {wait}s bekleniyor... (deneme {attempt + 1}/3)")
            await asyncio.sleep(wait)
            continue

        response.raise_for_status()
        releases = response.json()
        return [
            {
                "tag_name": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "body": (r.get("body") or "")[:MAX_BODY_LENGTH],
                "published_at": r.get("published_at", ""),
                "html_url": r.get("html_url", ""),
            }
            for r in releases
        ]

    raise httpx.HTTPStatusError(
        f"GitHub rate limit aşıldı: {repo}",
        request=response.request,
        response=response,
    )


# --- Orchestration ---

async def _run_agent(agent, prompt: str) -> str:
    async with _get_openai_sem():
        result = await Runner.run(agent, prompt)
    return result.final_output


async def summarize_github_releases(source_name: str, releases: list[dict]) -> str:
    releases_text = "\n\n".join(
        f"Sürüm: {r['tag_name']} ({r['published_at']})\n"
        f"Başlık: {r['name']}\n"
        f"URL: {r['html_url']}\n"
        f"Notlar:\n{r['body']}"
        for r in releases
    )
    return await _run_agent(summarizer_agent, f"{source_name} için son sürümler:\n\n{releases_text}")


async def summarize_url_content(source_name: str, url: str, content: str) -> str:
    prompt = (
        f"{source_name} kaynak URL: {url}\n\n"
        f"Sayfa içeriği (ilk {MAX_BODY_LENGTH} karakter):\n\n{content[:MAX_BODY_LENGTH]}"
    )
    return await _run_agent(summarizer_agent, prompt)


async def compose_email(summaries: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y")
    summaries_text = "\n\n---\n\n".join(
        f"## {s['source_name']}\n{s['summary']}\nSon sürüm: {s.get('latest_version', '')}\nURL: {s.get('url', '')}"
        for s in summaries
    )
    return await _run_agent(email_composer_agent, f"Tarih: {today}\n\nÖzetler:\n\n{summaries_text}")


async def _fetch_github(source: dict, known_version: Optional[str]) -> Optional[dict]:
    repo = source["config"].get("repo", "")
    releases = await fetch_github_releases(repo, per_page=3)
    if not releases:
        return None

    latest_version = releases[0]["tag_name"]
    if latest_version == known_version:
        logger.info(f"[{source['slug']}] Zaten güncel ({latest_version}), atlandı")
        return None

    summary = await summarize_github_releases(source["name"], releases)
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "releases": releases,
        "summary": summary,
        "latest_version": latest_version,
        "url": releases[0]["html_url"],
    }


async def _fetch_url(source: dict, known_version: Optional[str]) -> Optional[dict]:
    url = source["config"].get("url", "")
    response = await http_client.get(url)
    response.raise_for_status()
    content = response.text

    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    if content_hash == known_version:
        logger.info(f"[{source['slug']}] İçerik değişmemiş, atlandı")
        return None

    summary = await summarize_url_content(source["name"], url, content)
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "releases": [{"tag_name": content_hash, "name": source["name"], "body": content[:500],
                      "published_at": "", "html_url": url}],
        "summary": summary,
        "latest_version": content_hash,
        "url": url,
    }


async def fetch_and_summarize_source(source: dict, known_version: Optional[str] = None) -> Optional[dict]:
    """
    Tek bir kaynak için release'leri çeker ve özetler.
    - known_version ile eşleşiyorsa OpenAI çağrısı yapılmaz, None döner.
    - Hata durumunda None döner — diğer kaynakları etkilemez.
    """
    slug = source["slug"]

    try:
        logger.info(f"[{slug}] Kontrol ediliyor (bilinen: {known_version or 'yok'})")

        match source.get("source_type", "github"):
            case "github":
                result = await _fetch_github(source, known_version)
            case "url":
                result = await _fetch_url(source, known_version)
            case unknown:
                logger.error(f"[{slug}] Bilinmeyen kaynak tipi: {unknown}")
                return None

        if result:
            logger.info(f"[{slug}] Yeni release: {result['latest_version']}")
        return result

    except asyncio.TimeoutError:
        logger.error(f"[{slug}] Zaman aşımı ({settings.source_timeout}s) — atlandı")
    except httpx.HTTPStatusError as e:
        logger.error(f"[{slug}] HTTP hatası: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"[{slug}] Ağ hatası: {e}")
    except Exception as e:
        logger.error(f"[{slug}] Beklenmedik hata: {e}", exc_info=True)

    return None
