"""Ortam değişkenleri ve izlenen ürünler."""
import os
from zoneinfo import ZoneInfo

VERSION = "0.0.1"

# LLM (OpenAI uyumlu, ör. https://api.deepseek.com veya http://litellm:4000/v1)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))  # aynı anda en fazla kaç özet isteği
LLM_CONFIGURED = bool(LLM_BASE_URL and LLM_MODEL)
MAX_NOTES_CHARS = 15000  # LLM'e gönderilen sürüm notu üst sınırı

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # opsiyonel; token'sız limit 60 istek/saat

# Zamanlama
CHECK_CRON = os.getenv("CHECK_CRON", "0 6 * * *")  # dakika saat gün ay haftanın-günü
CHECK_TZ = ZoneInfo(os.getenv("CHECK_TIMEZONE", "Europe/Istanbul"))

# Veri
DB_PATH = os.getenv("DB_PATH", "data/releases.db")  # OpenShift'te /data (PVC)
KEEP_STABLE = 3  # izlenen stable sürümler: n, n-1, n-2
RETENTION_PER_PRODUCT = max(int(os.getenv("RETENTION_PER_PRODUCT", "10")), KEEP_STABLE)

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
