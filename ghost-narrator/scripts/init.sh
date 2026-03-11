#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "═══════════════════════════════════════════════════════"
echo " Ghost → Audio Pipeline — VM Initialisation"
echo " Working dir: ${REPO_ROOT}"
echo "═══════════════════════════════════════════════════════"

# ─── Check .env file ─────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo ""
    echo "✗ .env file not found."
    echo "  Create .env from the template and fill in your values:"
    echo ""
    echo "  Copy these lines into .env and update the values:"
    echo "  ────────────────────────────────────────────────────"
    echo "  SERVER_EXTERNAL_IP=your-vm-external-ip"
    echo "  N8N_USER=admin"
    echo "  N8N_PASSWORD=your-secure-password"
    echo "  N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)"
    echo "  GCS_BUCKET_NAME=your-gcs-bucket-name"
    echo "  VLLM_BASE_URL=http://host.docker.internal:8000"
    echo "  VLLM_MODEL_NAME=Qwen/Qwen3-14B"
    echo "  TTS_DEVICE=cpu"
    echo "  MAX_WORKERS=4"
    echo "  TIMEZONE=UTC"
    echo "  ────────────────────────────────────────────────────"
    echo ""
    exit 1
fi
echo "✓ .env found"

# ─── Validate required environment variables ─────────────────────────────────
required_vars=(
    SERVER_EXTERNAL_IP
    N8N_USER
    N8N_PASSWORD
    N8N_ENCRYPTION_KEY
    GCS_BUCKET_NAME
)
for var in "${required_vars[@]}"; do
    val=$(grep "^${var}=" .env | cut -d= -f2- || echo "")
    if [ -z "${val}" ] || [[ "${val}" == *"replace"* ]] || [[ "${val}" == *"your_"* ]] || [[ "${val}" == *"your-"* ]]; then
        echo "✗ ${var} is not set or still has placeholder value in .env"
        exit 1
    fi
done
echo "✓ Required .env variables set"

# ─── Check voice sample ──────────────────────────────────────────────────────
if [ ! -f tts-service/voices/reference.wav ]; then
    echo ""
    echo "✗ Voice sample not found at tts-service/voices/reference.wav"
    echo "  Copy your 30-60 second WAV file:"
    echo "    mkdir -p tts-service/voices"
    echo "    cp /path/to/your/voice-sample.wav tts-service/voices/reference.wav"
    echo ""
    exit 1
fi
echo "✓ Voice sample found"

# ─── Check Docker ────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "✗ Docker not found. Install Docker first."
    exit 1
fi
echo "✓ Docker found: $(docker --version | cut -d' ' -f3)"

if ! docker compose version &>/dev/null; then
    echo "✗ Docker Compose V2 not found. Update Docker or install the plugin."
    exit 1
fi
echo "✓ Docker Compose V2 found"

# ─── Check GPU availability ──────────────────────────────────────────────────
if docker info 2>/dev/null | grep -q "nvidia"; then
    echo "✓ NVIDIA container runtime detected (GPU available if needed)"
else
    echo "ℹ NVIDIA container runtime not detected — TTS will run on CPU (normal)"
fi

# ─── Create directories ──────────────────────────────────────────────────────
mkdir -p tts-service/voices tts-service/output n8n/data
echo "✓ Directories created"

# ─── Check GCS access ────────────────────────────────────────────────────────
BUCKET_NAME=$(grep "^GCS_BUCKET_NAME=" .env | cut -d= -f2- || echo "")
if [ -n "${BUCKET_NAME}" ]; then
    echo "Checking GCS access for bucket: ${BUCKET_NAME}..."
    if command -v gsutil &>/dev/null && gsutil ls "gs://${BUCKET_NAME}" &>/dev/null; then
        echo "✓ GCS bucket accessible via ADC"
    else
        echo "⚠ Cannot access gs://${BUCKET_NAME}"
        echo "  Ensure the VM's Service Account is attached and has Storage Object Admin"
        echo "  on the bucket. Run scripts/setup-gcp.sh if you haven't already."
        echo "  Continuing anyway — GCS uploads will fail until this is resolved."
    fi
else
    echo "⚠ GCS_BUCKET_NAME not set — GCS uploads will be disabled"
fi

# ─── Build TTS service ───────────────────────────────────────────────────────
echo ""
echo "▶ Building TTS service image..."
docker compose build tts-service

# ─── Start services ──────────────────────────────────────────────────────────
echo ""
echo "▶ Starting pipeline services..."
docker compose up -d redis n8n tts-service

# ─── Wait for TTS service health ─────────────────────────────────────────────
echo ""
echo "▶ Waiting for services to become healthy (up to 5 min for TTS model download)..."
TIMEOUT=300
ELAPSED=0
INTERVAL=5

while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(docker inspect --format="{{.State.Health.Status}}" tts-service 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "healthy" ]; then
        echo ""
        echo "✓ TTS service healthy"
        break
    fi
    echo -n "."
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ "$STATUS" != "healthy" ]; then
    echo ""
    echo "⚠ TTS service health check timed out after ${TIMEOUT}s"
    echo "  Check logs: docker logs tts-service --tail 50"
    echo "  The service may still be downloading the XTTS-v2 model (~1.8GB)"
fi

# ─── Display summary ─────────────────────────────────────────────────────────
SERVER_IP=$(grep "^SERVER_EXTERNAL_IP=" .env | cut -d= -f2- || echo "localhost")
N8N_USER_VAL=$(grep "^N8N_USER=" .env | cut -d= -f2- || echo "admin")

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Services started ✓"
echo "═══════════════════════════════════════════════════════"
echo ""
echo " n8n UI    → http://${SERVER_IP}:5678"
echo "   User   : ${N8N_USER_VAL}"
echo "   Pass   : (see N8N_PASSWORD in .env)"
echo ""
echo " TTS API   → http://${SERVER_IP}:8020/docs"
echo " Health    → http://${SERVER_IP}:8020/health"
echo ""
echo "Next steps:"
echo "  1. Open n8n UI and import n8n/workflows/ghost-audio-pipeline.json"
echo "     (n8n menu → Workflows → Import from file)"
echo "  2. In n8n: Settings → Variables → add:"
echo "     - GHOST_KEY_SITE1 (Ghost Content API key for site 1)"
echo "     - GHOST_KEY_SITE2 (Ghost Content API key for site 2)"
echo "  3. In n8n: Activate the workflow (toggle at top-right)"
echo "  4. In Ghost Admin (both sites):"
echo "     Settings → Integrations → Webhooks → Add webhook"
echo "     Event: Post published"
echo "     URL:   http://${SERVER_IP}:5678/webhook/ghost-published"
echo "  5. Test by publishing a post on one of your Ghost sites"
echo ""
