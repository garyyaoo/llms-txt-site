# ── Stage 1: build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app/fe
COPY fe/package*.json ./
RUN npm install
COPY fe/ ./
RUN npm run build

# ── Stage 2: Python server ─────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./
COPY --from=frontend /app/fe/dist ./fe/dist

EXPOSE 8080
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "4"]
