#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "═══════════════════════════════════════════════════════"
echo " Ghost → Audio Pipeline — VM Initialisation"
echo " Working dir: ${REPO_ROOT}"
echo "═══════════════════════════════════════════════════════"
echo ""

# ─── Helper functions ────────────────────────────────────────────────────────

prompt_value() {
    local prompt_text="$1"
    local default_value="${2:-}"
    local value=""

    if [ -n "${default_value}" ]; then
        read -r -p "${prompt_text} [${default_value}]: " value
        value="${value:-${default_value}}"
    else
        while [ -z "${value}" ]; do
            read -r -p "${prompt_text}: " value
            if [ -z "${value}" ]; then
                echo "  ✗ This field is required. Please enter a value."
            fi
        done
    fi

    echo "${value}"
}

prompt_secret() {
    local prompt_text="$1"
    local value=""

    while [ -z "${value}" ]; do
        read -r -s -p "${prompt_text}: " value
        echo ""
        if [ -z "${value}" ]; then
            echo "  ✗ This field is required. Please enter a value."
        fi
    done

    echo "${value}"
}

# ─── Check or create .env file ───────────────────────────────────────────────
if [ -f .env ]; then
    echo "✓ .env file found"

    # Validate required environment variables
    required_vars=(
        SERVER_EXTERNAL_IP
        N8N_USER
        N8N_PASSWORD
        N8N_ENCRYPTION_KEY
        GCS_BUCKET_NAME
    )

    missing_vars=()
    for var in "${required_vars[@]}"; do
        val=$(grep "^${var}=" .env | cut -d= -f2- || echo "")
        if [ -z "${val}" ] || [[ "${val}" == *"replace"* ]] || [[ "${val}" == *"your_"* ]] || [[ "${val}" == *"your-"* ]]; then
            missing_vars+=("${var}")
        fi
    done

    if [ ${#missing_vars[@]} -gt 0 ]; then
        echo ""
        echo "⚠ The following variables have placeholder or missing values:"
        for var in "${missing_vars[@]}"; do
            echo "  - ${var}"
        done
        echo ""
        read -r -p "Would you like to update these values interactively? [Y/n]: " update_confirm
        update_confirm="${update_confirm:-Y}"

        if [[ "${update_confirm}" =~ ^[Yy]$ ]]; then
            # Source existing values
            source .env 2>/dev/null || true

            echo ""
            echo "Please provide values for the missing/placeholder variables:"
            echo "─────────────────────────────────────────────────────────────"
            echo ""

            for var in "${missing_vars[@]}"; do
                case "${var}" in
                    SERVER_EXTERNAL_IP)
                        SERVER_EXTERNAL_IP=$(prompt_value "Server External IP")
                        ;;
                    N8N_USER)
                        N8N_USER=$(prompt_value "n8n Admin Username" "admin")
                        ;;
                    N8N_PASSWORD)
                        N8N_PASSWORD=$(prompt_secret "n8n Admin Password")
                        ;;
                    N8N_ENCRYPTION_KEY)
                        default_key=$(openssl rand -hex 32 2>/dev/null || echo "")
                        if [ -n "${default_key}" ]; then
                            echo "  (Generated encryption key: ${default_key})"
                            N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key" "${default_key}")
                        else
                            N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key (run: openssl rand -hex 32)")
                        fi
                        ;;
                    GCS_BUCKET_NAME)
                        GCS_BUCKET_NAME=$(prompt_value "GCS Bucket Name")
                        ;;
                esac
            done

            # Rewrite .env with updated values
            cat > .env <<EOF
# Server Configuration
SERVER_EXTERNAL_IP=${SERVER_EXTERNAL_IP:-}

# n8n Configuration
N8N_USER=${N8N_USER:-admin}
N8N_PASSWORD=${N8N_PASSWORD:-}
N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY:-}

# Google Cloud Storage
GCS_BUCKET_NAME=${GCS_BUCKET_NAME:-}

# vLLM Configuration
VLLM_BASE_URL=${VLLM_BASE_URL:-http://host.docker.internal:8000}
VLLM_MODEL_NAME=${VLLM_MODEL_NAME:-Qwen/Qwen3-14B}

# TTS Configuration
TTS_DEVICE=${TTS_DEVICE:-cpu}
MAX_WORKERS=${MAX_WORKERS:-4}

# General
TIMEZONE=${TIMEZONE:-UTC}
EOF
            echo ""
            echo "✓ .env file updated"
        else
            echo "✗ Please update .env manually and re-run this script."
            exit 1
        fi
    else
        echo "✓ Required .env variables set"
    fi
else
    echo "⚠ .env file not found. Let's create one interactively."
    echo ""
    echo "Please provide the following configuration values:"
    echo "─────────────────────────────────────────────────────────────"
    echo ""

    # Required values
    SERVER_EXTERNAL_IP=$(prompt_value "Server External IP (your VM's public IP)")

    echo ""
    echo "── n8n Configuration ──"
    N8N_USER=$(prompt_value "n8n Admin Username" "admin")
    N8N_PASSWORD=$(prompt_secret "n8n Admin Password")

    # Generate encryption key
    default_key=$(openssl rand -hex 32 2>/dev/null || echo "")
    if [ -n "${default_key}" ]; then
        echo "  (Generated encryption key: ${default_key})"
        N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key" "${default_key}")
    else
        N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key (run: openssl rand -hex 32)")
    fi

    echo ""
    echo "── Google Cloud Storage ──"
    GCS_BUCKET_NAME=$(prompt_value "GCS Bucket Name")

    echo ""
    echo "── vLLM Configuration (optional) ──"
    VLLM_BASE_URL=$(prompt_value "vLLM Base URL" "http://host.docker.internal:8000")
    VLLM_MODEL_NAME=$(prompt_value "vLLM Model Name" "Qwen/Qwen3-14B")

    echo ""
    echo "── TTS Configuration (optional) ──"
    TTS_DEVICE=$(prompt_value "TTS Device (cpu/cuda)" "cpu")
    MAX_WORKERS=$(prompt_value "Max Workers" "4")

    echo ""
    echo "── General (optional) ──"
    TIMEZONE=$(prompt_value "Timezone" "America/Toronto")

    # Write .env file
    cat > .env <<EOF
# Server Configuration
SERVER_EXTERNAL_IP=${SERVER_EXTERNAL_IP}

# n8n Configuration
N8N_USER=${N8N_USER}
N8N_PASSWORD=${N8N_PASSWORD}
N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}

# Google Cloud Storage
GCS_BUCKET_NAME=${GCS_BUCKET_NAME}

# vLLM Configuration
VLLM_BASE_URL=${VLLM_BASE_URL}
VLLM_MODEL_NAME=${VLLM_MODEL_NAME}

# TTS Configuration
TTS_DEVICE=${TTS_DEVICE}
MAX_WORKERS=${MAX_WORKERS}

# General
TIMEZONE=${TIMEZONE}
EOF

    echo ""
    echo "─────────────────────────────────────────────────────────────"
    echo "Configuration Summary:"
    echo "─────────────────────────────────────────────────────────────"
    echo "  Server IP      : ${SERVER_EXTERNAL_IP}"
    echo "  n8n User       : ${N8N_USER}"
    echo "  GCS Bucket     : ${GCS_BUCKET_NAME}"
    echo "  vLLM URL       : ${VLLM_BASE_URL}"
    echo "  vLLM Model     : ${VLLM_MODEL_NAME}"
    echo "  TTS Device     : ${TTS_DEVICE}"
    echo "  Max Workers    : ${MAX_WORKERS}"
    echo "  Timezone       : ${TIMEZONE}"
    echo "─────────────────────────────────────────────────────────────"
    echo ""
    echo "✓ .env file created"
fi

echo ""

# ─── Check voice sample ──────────────────────────────────────────────────────
if [ ! -f tts-service/voices/reference.wav ]; then
    echo "⚠ Voice sample not found at tts-service/voices/reference.wav"
    echo ""
    echo "  The TTS service requires a 30-60 second WAV file of the voice to clone."
    echo ""
    read -r -p "  Enter path to your voice sample WAV file (or press Enter to skip): " voice_path

    if [ -n "${voice_path}" ]; then
        if [ -f "${voice_path}" ]; then
            mkdir -p tts-service/voices
            cp "${voice_path}" tts-service/voices/reference.wav
            echo "  ✓ Voice sample copied to tts-service/voices/reference.wav"
        else
            echo "  ✗ File not found: ${voice_path}"
            echo "  Please copy your voice sample manually before starting services:"
            echo "    mkdir -p tts-service/voices"
            echo "    cp /path/to/your/voice-sample.wav tts-service/voices/reference.wav"
            exit 1
        fi
    else
        echo ""
        echo "  Please copy your voice sample manually before starting services:"
        echo "    mkdir -p tts-service/voices"
        echo "    cp /path/to/your/voice-sample.wav tts-service/voices/reference.wav"
        echo ""
        exit 1
    fi
else
    echo "✓ Voice sample found"
fi

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

# ─── Confirm before starting services ────────────────────────────────────────
echo ""
read -r -p "▶ Ready to build and start services. Continue? [Y/n]: " start_confirm
start_confirm="${start_confirm:-Y}"
if [[ ! "${start_confirm}" =~ ^[Yy]$ ]]; then
    echo "Setup paused. Run this script again when ready."
    exit 0
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
