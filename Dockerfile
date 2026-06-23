FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY requirements.txt requirements-speech.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY src ./src

# Non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Bind to $PORT (Render/Cloud Run inject it); default 8000 for local `docker run`.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health')"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
