#!/bin/bash
set -e

echo "Building containers..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit passwords, SECRET_KEY, SendGrid, and ScraperAPI values, then rerun ./deploy.sh."
  exit 1
fi

mkdir -p ssl
docker compose build --no-cache

echo "Starting services..."
docker compose up -d

echo "Checking service health..."
docker compose ps

echo "Deployment complete. Open http://localhost"
