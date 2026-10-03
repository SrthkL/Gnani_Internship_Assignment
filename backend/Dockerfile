FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production STORAGE_DIR=/data HOST=0.0.0.0 PORT=8010
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home appuser \
    && mkdir /data && chown appuser:appuser /data

# Copy source explicitly; never bake credentials or recordings into the image.
COPY app ./app
COPY main.py ./
USER appuser
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=12s --start-period=60s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8010')+'/ready',timeout=10)"
CMD ["python", "-m", "app.start"]
