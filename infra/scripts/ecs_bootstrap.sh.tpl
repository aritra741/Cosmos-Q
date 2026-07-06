#!/bin/bash
set -euo pipefail
exec > /var/log/cosmos-bootstrap.log 2>&1   # log for debugging

# --- Install Docker, psql client, and Git ---
apt-get update
apt-get install -y docker.io postgresql-client git
systemctl enable --now docker

# --- Enable pgvector extension (one-time) ---
until pg_isready -h "${pg_host}" -p 5432; do
  echo "Waiting for RDS PostgreSQL to be reachable..."
  sleep 5
done
psql "${pg_dsn}" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# --- Clone the COSMOS-Q repository ---
echo "Cloning codebase from ${git_repo_url}..."
mkdir -p /opt
rm -rf /opt/cosmos-q

until git clone "${git_repo_url}" /opt/cosmos-q; do
  echo "Waiting/retrying git clone of ${git_repo_url} (ensure repo is public or accessible)..."
  sleep 10
done

# --- Build the Docker image locally on instance ---
echo "Building Docker image..."
cd /opt/cosmos-q
docker build -t cosmos-q:latest .

# --- Run the MCP server container ---
echo "Running cosmos-q container..."
docker run -d --name cosmos-q --restart unless-stopped -p 8765:8765 \
  -e COSMOS_PG_DSN="${pg_dsn}" \
  -e COSMOS_QWEN_API_KEY="${qwen_api_key}" \
  cosmos-q:latest

echo "Bootstrap complete!"
