# Orẽgdo en conteneur : docker compose up --build   (voir compose.yaml)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 OREGDO_COMMUNE=ouaga
# libgomp1 : requis par scikit-learn ; le reste (GEOS, GDAL, PROJ) est embarqué dans les roues Python.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' scripts/docker_entree.sh && chmod +x scripts/docker_entree.sh \
    && useradd --create-home --uid 10001 oregdo && mkdir -p /app/data && chown -R oregdo /app/data
USER oregdo

VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/sante', timeout=4).status == 200 else 1)"
ENTRYPOINT ["scripts/docker_entree.sh"]
