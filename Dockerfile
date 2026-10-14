FROM registry.access.redhat.com/ubi9/python-312

# Kurum içi PyPI mirror için: --build-arg PIP_INDEX_URL=https://nexus.../simple
ARG PIP_INDEX_URL
WORKDIR /opt/app-root/src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY release_summarizer release_summarizer

# OpenShift rastgele UID + GID 0 ile çalıştırır: /data grup 0 tarafından yazılabilir olmalı
USER 0
RUN mkdir -p /data && chgrp -R 0 /data && chmod -R g=u /data
USER 1001

ENV DB_PATH=/data/releases.db PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "release_summarizer.main:app", "--host", "0.0.0.0", "--port", "8080"]
