#!/bin/bash
set -e

# Start MQTT broker in the background using container-specific config
echo "Starting amqtt broker on 127.0.0.1..."
amqtt -c infra/amqtt/broker.container.yaml &

# Wait for broker to initialize
sleep 2

# Start the FastAPI backend
echo "Starting Uvicorn backend on port ${PORT:-8000}..."
exec python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port "${PORT:-8000}"
