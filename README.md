# release-summarizer

LiteLLM, MLflow, Langfuse, OpenShift, OpenShift AI, code-server, Triton ve vLLM release'lerini takip eder,
yeni sürümleri OpenAI uyumlu bir LLM ile Türkçe özetler (TL;DR, öne çıkanlar, breaking, güvenlik, aciliyet).

| Ürün | Kaynak |
|---|---|
| OpenShift | `mirror.openshift.com/.../ocp/stable/release.txt` (stable kanal) |
| OpenShift AI | `opendatahub-io/opendatahub-operator` (upstream ODH) |
| Diğerleri | GitHub Releases (rc/ea/nightly hariç) |

## Ayarlar (env)
| Değişken | Nerede | Varsayılan |
|---|---|---|
| `LLM_BASE_URL`, `LLM_MODEL` | ConfigMap | — (yoksa sadece takip, özet yok) |
| `LLM_API_KEY`, `GITHUB_TOKEN` | Secret | — |
| `CHECK_INTERVAL_MINUTES` | ConfigMap | 360 |
| `DB_PATH` | imaj | `/data/releases.db` (PVC) |

Kurum içi CA için `SSL_CERT_FILE`, proxy için `HTTPS_PROXY` / `NO_PROXY` env'leri yeterli.

## OpenShift'e deploy

**A) Cluster içinde build (önerilen)**
```bash
oc project mlops
oc apply -f openshift/build.yaml
oc start-build release-summarizer --from-dir=. --follow
oc apply -f openshift/deploy.yaml     # önce ConfigMap/Secret değerlerini düzenleyin
oc get route release-summarizer
```
Güncelleme: `oc start-build release-summarizer --from-dir=. --follow` (deployment otomatik yenilenir).

**B) Harici registry (Quay/Nexus/Harbor)**
```bash
podman build --platform linux/amd64 -t registry.example/mlops/release-summarizer:0.0.1 .
podman push registry.example/mlops/release-summarizer:0.0.1
```
`openshift/deploy.yaml` içinde trigger annotation'ını silip `image:` alanına bu adresi yazın, sonra `oc apply`.

## Lokal
```bash
pip install -r requirements.txt
LLM_BASE_URL=http://localhost:4000/v1 LLM_MODEL=gpt-4o-mini LLM_API_KEY=sk-... DB_PATH=data/releases.db uvicorn app:app --port 8080
python test_app.py
```

Ürün eklemek: `app.py` içindeki `PRODUCTS` sözlüğüne `{"name": ..., "repo": "owner/repo"}` ekleyin.
İlk çalıştırmada ürün başına son 3 sürüm alınır (okunmuş olarak); sonrakilerde yeniler "YENİ" olarak düşer.

## Yol haritası
- **v0.0.1** — release takibi, LLM özeti, web arayüzü, OpenShift deploy
- **v0.0.2** — mail-sender entegrasyonu ve periyodik özet raporu
