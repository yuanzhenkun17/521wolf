# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS backend

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY engine ./engine
COPY skills ./skills
COPY storage ./storage
COPY ui/backend ./ui/backend

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "ui.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:22-alpine AS frontend-build

WORKDIR /app
COPY ui/frontend/package*.json ./ui/frontend/
RUN npm ci --prefix ui/frontend
COPY ui/frontend ./ui/frontend
RUN npm run build --prefix ui/frontend

FROM nginx:1.27-alpine AS frontend

COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/ui/frontend/dist /usr/share/nginx/html

EXPOSE 80
