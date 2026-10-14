# release-summarizer

LiteLLM, MLflow, Langfuse, OpenShift, OpenShift AI, code-server, Triton ve vLLM release'lerini takip eder,
yeni sürümleri OpenAI uyumlu bir LLM ile Türkçe özetler (TL;DR, öne çıkanlar, breaking, güvenlik, aciliyet).

| Ürün | Kaynak |
|---|---|
| OpenShift | `mirror.openshift.com/.../ocp/stable/release.txt` (stable kanal; n-1, n-2 `Upgrades:` listesinden) |
| OpenShift AI | `opendatahub-io/opendatahub-operator` (upstream ODH) |
| Diğerleri | GitHub Releases (dev/ea/nightly hariç) |

## Ayarlar (env)
| Değişken | Nerede | Varsayılan |
|---|---|---|
| `LLM_BASE_URL`, `LLM_MODEL` | ConfigMap | — (yoksa sadece takip, özet yok); manifestte DeepSeek (`https://api.deepseek.com`, `deepseek-flash`) |
| `LLM_API_KEY`, `GITHUB_TOKEN` | Secret (`oc create secret`) | — |
| `RETENTION_PER_PRODUCT` | ConfigMap | 10 (ürün başına saklanan sürüm, en az 3) |
| `LLM_CONCURRENCY` | ConfigMap | 4 (paralel özet isteği) |
| `CHECK_CRON` | ConfigMap | `0 6 * * *` (her gün 06:00) |
| `CHECK_TIMEZONE` | ConfigMap | `Europe/Istanbul` |
| `DB_PATH` | imaj | `/data/releases.db` (PVC) |

`CHECK_CRON` standart 5 alanlı cron'dur (`*`, `*/n`, `a-b`, `a,b`), Argo CronWorkflow `schedule` ile aynı biçim.
Örn. `0 6 * * 1-5` hafta içi 06:00, `0 */6 * * *` 6 saatte bir. İlk kurulumda zamanı beklemeden bir kez çalışır.

Kurum içi CA için `SSL_CERT_FILE`, proxy için `HTTPS_PROXY` / `NO_PROXY` env'leri yeterli.

## OpenShift'e deploy
İmaj Docker Hub'da hazır (`docker.io/mustafa12/release-summarizer`, linux/amd64, public); cluster'da build gerekmez.

```bash
oc project mlops
oc create secret generic release-summarizer --from-literal=LLM_API_KEY=<key>   # opsiyonel: --from-literal=GITHUB_TOKEN=<token>
oc apply -f openshift/deploy.yaml
oc get route release-summarizer
```

- **Ayar değiştirmek:** `openshift/deploy.yaml` içindeki ConfigMap'i düzenle → `oc apply -f openshift/deploy.yaml` → `oc rollout restart deploy/release-summarizer`
- **Key değiştirmek:** `oc create secret generic release-summarizer --from-literal=LLM_API_KEY=<yeni> --dry-run=client -o yaml | oc apply -f -` → `oc rollout restart deploy/release-summarizer`
- **Yeni imaj:** aynı tag yeniden push'lanırsa `oc rollout restart deploy/release-summarizer` yeter (`imagePullPolicy: Always`). Yeni versiyon için `image:` satırını güncelle.
- **Kaldırmak:** `oc delete -f openshift/deploy.yaml && oc delete secret release-summarizer` (PVC de silinir, veriler gider).

### İmajı yeniden üretmek
```bash
docker build --platform linux/amd64 -t mustafa12/release-summarizer:0.0.1 -t mustafa12/release-summarizer:latest .
docker push mustafa12/release-summarizer:0.0.1 && docker push mustafa12/release-summarizer:latest
```

## Lokal
```bash
pip install -r requirements.txt
LLM_BASE_URL=http://localhost:4000/v1 LLM_MODEL=gpt-4o-mini LLM_API_KEY=sk-... DB_PATH=data/releases.db uvicorn release_summarizer.main:app --port 8080
python -m tests.test_core
```

Ürün eklemek: `release_summarizer/config.py` içindeki `PRODUCTS` sözlüğüne `{"name": ..., "repo": "owner/repo"}` ekleyin.
### Hangi sürümler izleniyor?
Her ürün için **n, n-1, n-2** (n = en yüksek stable sürüm, sıralama yayın tarihine değil sürüm numarasına göre)
ve **n'den yeni RC'ler** (release candidate, stable öncesi aday sürüm; arayüzde `RC` etiketiyle).
Stable çıkınca eski RC'ler listede kalır ama yeni RC eklenmez. İlk kurulumdakiler okunmuş sayılır,
sonra gelenler "YENİ" olarak düşer. Sayı `config.py` içindeki `KEEP_STABLE` ile değiştirilir.

## Veri ve saklama
Tek SQLite dosyası: `DB_PATH` (imajda `/data/releases.db`, OpenShift'te `release-summarizer-data` PVC).
Sürüm notları, LLM özetleri, okundu bilgisi ve ürün başına son kontrol zamanı burada tutulur.

Her kontrolden sonra temizlik çalışır:
- Ürün başına sürüm numarasına göre en yeni `RETENTION_PER_PRODUCT` (varsayılan 10) kayıt kalır, eskiler silinir.
- Stable'ı çıkmış RC'ler silinir (ör. `v1.106.0` çıkınca `v1.106.0-rc.*`).
- `PRODUCTS` listesinden çıkarılan ürünlerin kayıtları silinir.

Bu limitle veritabanı birkaç MB'ı geçmez. Yedek: `oc cp <pod>:/data/releases.db ./releases.db`.

## Proje yapısı
```
release_summarizer/
├── config.py    # env değişkenleri, izlenen ürünler
├── versions.py  # tag tanıma/sıralama, n..n-2 + rc seçimi
├── cron.py      # bağımlılıksız cron ifadesi
├── sources.py   # GitHub Releases, OpenShift mirror
├── db.py        # SQLite, saklama/temizlik
├── llm.py       # prompt ve OpenAI uyumlu çağrı
├── service.py   # akış: çek → kaydet → temizle → özetle, zamanlayıcı
├── main.py      # FastAPI uç noktaları
└── static/index.html
tests/test_core.py
```

## Yol haritası
- **v0.0.1** — release takibi, LLM özeti, web arayüzü, OpenShift deploy
- **v0.0.2** — mail-sender entegrasyonu ve periyodik özet raporu
