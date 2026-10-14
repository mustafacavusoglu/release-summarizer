"""OpenAI uyumlu /chat/completions ile sürüm notu özeti."""
import json
import re

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MAX_NOTES_CHARS
from .versions import is_rc

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
        r = await c.post(f"{LLM_BASE_URL}/chat/completions", timeout=300,
                         headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                         json={"model": LLM_MODEL, "temperature": 0.2,
                               "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return parse_summary(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}
