#!/usr/bin/env bash
set -euo pipefail

echo "╔══════════════════════════════════════════════════════════╗"
echo "║             Starting Core AI Services                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# 1. Validate environment dependencies
if ! command -v docker &> /dev/null; then
    echo "  ✗ Docker could not be found. Please ensure Docker is installed and running."
    exit 1
fi

# 2. Source existing .env variables if available
if [ -f .env ]; then
    # Safely export existing .env variables to prevent overwriting user configs
    export $(grep -v '^#' .env | xargs -d '\n' 2>/dev/null || true)
fi

# 3. Handle SEARXNG_SECRET securely
if [ -z "${SEARXNG_SECRET:-}" ]; then
    echo "▶ Fetching SEARXNG_SECRET from Secret Manager..."
    
    # Try fetching from GCP safely
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
    if [ -n "$PROJECT_ID" ]; then
        SEARXNG_SECRET=$(gcloud secrets versions access latest --secret="searxng-secret" --project="$PROJECT_ID" 2>/dev/null || echo "")
    elif command -v gcloud &> /dev/null; then
        SEARXNG_SECRET=$(gcloud secrets versions access latest --secret="searxng-secret" 2>/dev/null || echo "")
    fi

    if [ -n "$SEARXNG_SECRET" ]; then
        export SEARXNG_SECRET
        echo "  ✓ Secret securely injected from Google Cloud."
    else
        echo "  ⚠ Could not fetch 'searxng-secret' from GCP."
        echo "  ℹ Generating a completely new local persistent secret..."
        
        # Fallback generator for non-GCP deployments
        SEARXNG_SECRET=$(openssl rand -hex 32 2>/dev/null || echo "$RANDOM$RANDOM$RANDOM$RANDOM")
        export SEARXNG_SECRET
        
        # Cache fallback in .env to prevent session resets on future restarts
        echo "SEARXNG_SECRET=${SEARXNG_SECRET}" >> .env
        echo "  ✓ Saved fallback secret to local .env file."
    fi
else
    echo "  ✓ SEARXNG_SECRET loaded from local .env environment."
fi

echo ""
echo "▶ Starting Docker Compose Stack..."
docker compose up -d

echo ""
echo "✓ Services are starting! Check logs with: docker compose logs -f"
