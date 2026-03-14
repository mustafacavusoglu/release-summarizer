FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --quiet -r requirements.txt

COPY . .

# OpenShift: container'lar rastgele UID ile çalışır, group 0 (root group) sabit kalır.
# g=u: group izinlerini user izinleriyle eşitler → rastgele UID yazabilir.
RUN mkdir -p data && \
    chown -R 1001:0 /app && \
    chmod -R g=u /app

USER 1001

EXPOSE 8000

# Varsayılan: web API. CronJob için command override edilir: ["python", "job.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
