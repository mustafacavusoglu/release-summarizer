"""OpenAI uyumlu /chat/completions ile sürüm notu özeti."""
import json
import re

from .config import CHAT_MAX_CHARS, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_NOTES_CHARS
from .versions import TAG, is_rc, split, vkey

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


async def summarize(c, product_name, tag, notes):
    """Özet dict'i döner; hata olursa {"error": ...} (arayüzde 'Tekrar dene' için)."""
    prompt = PROMPT.format(name=product_name, tag=tag,
                           rc_note=" (release candidate: stable öncesi aday sürüm, bunu özette belirt)" if is_rc(tag) else "",
                           notes=(notes or "(not yok)")[:MAX_NOTES_CHARS])
    try:
        return parse_summary(await complete(c, [{"role": "user", "content": prompt}]))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}


async def complete(c, messages):
    r = await c.post(f"{LLM_BASE_URL}/chat/completions", timeout=300,
                     headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                     json={"model": LLM_MODEL, "temperature": 0.2, "messages": messages})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


CHAT_PROMPT = """Sen bir MLOps ekibinin sürüm danışmanısın. Soruları {name} sürüm notlarına dayanarak Türkçe ve kısa cevapla.
{current}
- Bir özellik/düzeltme sorulursa hangi sürümde geldiğini tag ile açıkça yaz. Aynı değişiklik birden fazla hatta
  (ör. 1.105.x ve 1.106.x backport) geldiyse hepsini belirt.
- Geçiş önerisinde sorunu çözen en düşük sürümü ve oraya kadarki breaking change'leri söyle.
- Notlarda yoksa uydurma, "sürüm notlarında bulamadım" de. RC sürümlerin stable olmadığını belirt.
{cut}
Sürüm notları (eskiden yeniye):
{notes}"""


def clean_notes(body):
    """Bağlamı küçültür: imza/kurulum ön metni, katkıda bulunanlar, link ve '@kişi' kırpılır."""
    body = body or ""
    i = body.find("## What's Changed")
    body = re.split(r"\n#+ New Contributors|\n\*\*Full Changelog", body[i:] if i >= 0 else body)[0]
    return re.sub(r" by @\S+ in https://\S+|\(?https?://\S+\)?", "", body).strip()


def notes_context(rels, since=None, budget=CHAT_MAX_CHARS):
    """since'ten yeni stable'lar + n'den yeni rc'ler, eskiden yeniye. (metin, sürüm sayısı, kırpıldı mı)"""
    rels = {r["tag"]: r for r in rels if TAG.match(r["tag"]) and (not since or vkey(r["tag"]) > vkey(since))}
    stable, rcs = split(rels)
    rels = [rels[t] for t in sorted(stable + rcs, key=vkey)]
    texts = [clean_notes(r["body"]) for r in rels]
    # ponytail: bütçe aşılırsa her sürüm eşit kırpılır; çok daha uzun geçmiş gerekirse arama/RAG
    cap = budget if sum(map(len, texts)) <= budget else budget // max(len(texts), 1)
    text = "\n\n".join(f"### {r['tag']} ({(r['published'] or '')[:10]})\n{t[:cap] or '(not yok)'}" for r, t in zip(rels, texts))
    return text, len(rels), cap < budget


async def chat(c, name, rels, messages, since=None):
    notes, n, cut = notes_context(rels, since)
    system = CHAT_PROMPT.format(
        name=name, notes=notes or "(bu aralıkta sürüm yok)",
        current=f"Kullanıcının mevcut sürümü: {since}. Notlar yalnızca bundan yeni sürümleri kapsar." if since
        else "Kullanıcı mevcut sürümünü belirtmedi; notlar son yayınlanan sürümleri kapsar.",
        cut="Not: bağlam sınırı nedeniyle her sürümün notu kısaltıldı, ayrıntı eksik olabilir." if cut else "")
    answer = await complete(c, [{"role": "system", "content": system}, *messages])
    return {"answer": re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip(), "releases": n, "truncated": cut}
