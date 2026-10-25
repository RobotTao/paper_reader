# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.2

# Dependencies are installed from the committed uv.lock file.
COPY backend/pyproject.toml backend/uv.lock ./backend/
COPY backend/app ./backend/app
RUN cd backend && uv sync --frozen --no-dev

COPY frontend ./frontend

ENV PDF_ROOT=/data \
    DATA_DIR=/data/db \
    FRONTEND_DIR=/app/frontend \
    PORT=8080

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/healthz').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8080"]
