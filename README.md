# release-summarizer

Teknoloji projelerinin GitHub release'lerini haftalık takip eden, OpenAI Agents ile özetleyen ve HTML e-posta raporu oluşturan servis.

## Nasıl Çalışır

1. Aktif kaynakların GitHub release'leri paralel çekilir
2. Yeni release varsa OpenAI ile Türkçe özet üretilir (yeni release yoksa OpenAI çağrısı yapılmaz)
3. Tüm özetler HTML e-posta formatında birleştirilir ve DB'ye kaydedilir

## Varsayılan Kaynaklar

MLflow · Qdrant · OpenShift AI · Red Hat AI (InstructLab) · Ray · KServe · Docker · Kubernetes

## Kurulum

```bash
cp .env.example .env
# .env içine OPENAI_API_KEY değerini gir

docker compose up -d
```

## Çevre Değişkenleri

| Değişken | Zorunlu | Varsayılan | Açıklama |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | OpenAI API anahtarı |
| `MODEL` | | `gpt-5-mini` | Kullanılacak model |
| `GITHUB_TOKEN` | | — | GitHub rate limit için (opsiyonel) |
| `MAX_CONCURRENT_AI` | | `4` | Paralel OpenAI çağrısı limiti |
| `SOURCE_TIMEOUT` | | `90` | Kaynak başına timeout (saniye) |

## API

| Method | Path | Açıklama |
|---|---|---|
| `POST` | `/reports/generate` | Rapor oluştur |
| `GET` | `/reports/{id}/html` | Raporu tarayıcıda görüntüle |
| `GET` | `/sources/` | Kaynakları listele |
| `POST` | `/sources/` | Yeni kaynak ekle |
| `PATCH` | `/sources/{id}/toggle` | Kaynak aktif/pasif |

Swagger UI: `http://localhost:8000/docs`

## Yeni Kaynak Ekleme

**GitHub repo:**
```json
{"name": "LangChain", "slug": "langchain", "source_type": "github", "config": {"repo": "langchain-ai/langchain"}}
```

**URL / RSS:**
```json
{"name": "Red Hat Blog", "slug": "redhat-blog", "source_type": "url", "config": {"url": "https://example.com/rss"}}
```

## OpenShift CronJob

```bash
docker build -t nexus.example.com/release-summarizer:1.0.0 .
docker push nexus.example.com/release-summarizer:1.0.0
```

CronJob manifest'inde:
```yaml
command: ["python", "job.py"]
schedule: "0 7 * * 1"  # Her Pazartesi 07:00
```

## Proje Yapısı

```
app/
├── core/        # config, database
├── db/          # modeller, seed kaynakları
├── agents/      # OpenAI Agents (fetch, summarize, compose)
├── services/    # FastAPI'den bağımsız iş mantığı
└── routers/     # API endpoint'leri
job.py           # Standalone CronJob entrypoint
```
