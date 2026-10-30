# AgentsMind in one container (Render free plan and similar hosts). See docs/DEPLOY_RENDER.md.
# Stage 1: build the web app
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY assets/ /app/assets/
RUN npx vite build

# Stage 2: Python app
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 APP_ENV=prod LOG_JSON=true
WORKDIR /app
COPY requirements/ requirements/
RUN pip install -r requirements/servers.txt -r requirements/postgres.txt
COPY . .
COPY --from=web /app/frontend/dist frontend/dist
RUN mkdir -p data logs && useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
EXPOSE 10000
CMD ["python", "deploy/onebox.py"]
