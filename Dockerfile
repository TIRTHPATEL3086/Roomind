# Stage 1: Build React Frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install MQTT broker (amqtt)
RUN pip install --no-cache-dir amqtt

# Install backend dependencies (without large ML models)
COPY backend/requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Copy application files
COPY backend/ ./backend/
COPY infra/ ./infra/
COPY docker/ ./docker/

# Ensure start script has executable permissions and unix line endings
RUN chmod +x docker/start.sh && \
    sed -i 's/\r$//' docker/start.sh

# Expose the port (Render sets this dynamically, but good for local/docs)
EXPOSE 8000

CMD ["./docker/start.sh"]
