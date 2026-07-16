FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ ./src/

RUN pip install --no-cache-dir --only-binary=:all: --prefer-binary -e . \
    && find /usr/local -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health'); exit(0)" || exit 1

CMD uvicorn linkedin_agent.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
