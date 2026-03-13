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

fetch_secret() {
    local secret_name="$1"
    local project_id="$2"
    local value=""

    if command -v gcloud &>/dev/null; then
        value=$(gcloud secrets versions access latest \
            --secret="${secret_name}" \
            --project="${project_id}" 2>/dev/null || echo "")
    fi

    echo "${value}"
}

# Update a single variable in .env file (or add if not exists)
update_env_var() {
    local var_name="$1"
    local var_value="$2"
    local env_file="${3:-.env}"

    if grep -q "^${var_name}=" "${env_file}" 2>/dev/null; then
        # Variable exists - update it (using | as delimiter to handle special chars)
        sed -i "s|^${var_name}=.*|${var_name}=${var_value}|" "${env_file}"
    else
        # Variable doesn't exist - append it
        echo "${var_name}=${var_value}" >> "${env_file}"
    fi
}

# Get a variable value from .env file
get_env_var() {
    local var_name="$1"
    local env_file="${2:-.env}"
    local value=""

    if [ -f "${env_file}" ]; then
        value=$(grep "^${var_name}=" "${env_file}" 2>/dev/null | cut -d= -f2- || echo "")
    fi

    echo "${value}"
}

# ─── Detect GCP Project ID ───────────────────────────────────────────────────
echo "▶ Detecting GCP configuration..."

GCP_PROJECT_ID=""
if command -v gcloud &>/dev/null; then
    GCP_PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
fi

if [ -z "${GCP_PROJECT_ID}" ]; then
    echo "  ⚠ Could not detect GCP project ID."
    read -r -p "  Enter your GCP Project ID (or press Enter to skip Secret Manager): " GCP_PROJECT_ID
fi

if [ -n "${GCP_PROJECT_ID}" ]; then
    echo "  ✓ GCP Project: ${GCP_PROJECT_ID}"
else
    echo "  ℹ Skipping Secret Manager integration."
fi

# ─── Fetch secrets from GCP Secret Manager ───────────────────────────────────
USE_SECRET_MANAGER=false
N8N_PASSWORD_FROM_SM=""
N8N_ENCRYPTION_KEY_FROM_SM=""
GHOST_KEY_SITE1_FROM_SM=""
GHOST_KEY_SITE2_FROM_SM=""

if [ -n "${GCP_PROJECT_ID}" ]; then
    echo ""
    echo "▶ Checking GCP Secret Manager for stored secrets..."

    # Try to fetch secrets
    N8N_PASSWORD_FROM_SM=$(fetch_secret "ghost-audio-n8n-password" "${GCP_PROJECT_ID}")
    N8N_ENCRYPTION_KEY_FROM_SM=$(fetch_secret "ghost-audio-n8n-encrypt-key" "${GCP_PROJECT_ID}")
    GHOST_KEY_SITE1_FROM_SM=$(fetch_secret "ghost-audio-ghost-key-site1" "${GCP_PROJECT_ID}")
    GHOST_KEY_SITE2_FROM_SM=$(fetch_secret "ghost-audio-ghost-key-site2" "${GCP_PROJECT_ID}")

    # Check if we got any secrets
    secrets_found=0
    [ -n "${N8N_PASSWORD_FROM_SM}" ] && secrets_found=$((secrets_found + 1)) && echo "  ✓ Found: ghost-audio-n8n-password"
    [ -n "${N8N_ENCRYPTION_KEY_FROM_SM}" ] && secrets_found=$((secrets_found + 1)) && echo "  ✓ Found: ghost-audio-n8n-encrypt-key"
    [ -n "${GHOST_KEY_SITE1_FROM_SM}" ] && secrets_found=$((secrets_found + 1)) && echo "  ✓ Found: ghost-audio-ghost-key-site1"
    [ -n "${GHOST_KEY_SITE2_FROM_SM}" ] && secrets_found=$((secrets_found + 1)) && echo "  ✓ Found: ghost-audio-ghost-key-site2"

    if [ $secrets_found -gt 0 ]; then
        USE_SECRET_MANAGER=true
        echo "  ✓ Retrieved ${secrets_found} secret(s) from Secret Manager"
    else
        echo "  ℹ No secrets found in Secret Manager. Will prompt for values."
    fi
fi

# ─── Auto-detect external IP ─────────────────────────────────────────────────
DETECTED_IP=""
DETECTED_IP=$(curl -s -m 5 http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H "Metadata-Flavor: Google" 2>/dev/null || echo "")

# ─── Check or create .env file ───────────────────────────────────────────────
echo ""

if [ -f .env ]; then
    echo "✓ .env file found"
    echo ""

    # Load existing values
    source .env 2>/dev/null || true

    # Check if we should merge with Secret Manager values
    if [ "${USE_SECRET_MANAGER}" = true ]; then
        echo "▶ Comparing .env with Secret Manager values..."
        echo ""

        changes_available=false
        changes_summary=""

        # Check each secret and show what would change
        current_password=$(get_env_var "N8N_PASSWORD")
        if [ -n "${N8N_PASSWORD_FROM_SM}" ] && [ "${current_password}" != "${N8N_PASSWORD_FROM_SM}" ]; then
            changes_available=true
            if [ -z "${current_password}" ]; then
                changes_summary+="  + N8N_PASSWORD (will be added from Secret Manager)\n"
            else
                changes_summary+="  ~ N8N_PASSWORD (will be updated from Secret Manager)\n"
            fi
        fi

        current_encrypt_key=$(get_env_var "N8N_ENCRYPTION_KEY")
        if [ -n "${N8N_ENCRYPTION_KEY_FROM_SM}" ] && [ "${current_encrypt_key}" != "${N8N_ENCRYPTION_KEY_FROM_SM}" ]; then
            changes_available=true
            if [ -z "${current_encrypt_key}" ]; then
                changes_summary+="  + N8N_ENCRYPTION_KEY (will be added from Secret Manager)\n"
            else
                changes_summary+="  ~ N8N_ENCRYPTION_KEY (will be updated from Secret Manager)\n"
            fi
        fi

        current_ghost_key1=$(get_env_var "GHOST_KEY_SITE1")
        if [ -n "${GHOST_KEY_SITE1_FROM_SM}" ] && [ "${current_ghost_key1}" != "${GHOST_KEY_SITE1_FROM_SM}" ]; then
            changes_available=true
            if [ -z "${current_ghost_key1}" ]; then
                changes_summary+="  + GHOST_KEY_SITE1 (will be added from Secret Manager)\n"
            else
                changes_summary+="  ~ GHOST_KEY_SITE1 (will be updated from Secret Manager)\n"
            fi
        fi

        current_ghost_key2=$(get_env_var "GHOST_KEY_SITE2")
        if [ -n "${GHOST_KEY_SITE2_FROM_SM}" ] && [ "${current_ghost_key2}" != "${GHOST_KEY_SITE2_FROM_SM}" ]; then
            changes_available=true
            if [ -z "${current_ghost_key2}" ]; then
                changes_summary+="  + GHOST_KEY_SITE2 (will be added from Secret Manager)\n"
            else
                changes_summary+="  ~ GHOST_KEY_SITE2 (will be updated from Secret Manager)\n"
            fi
        fi

        if [ "${changes_available}" = true ]; then
            echo "The following changes are available from Secret Manager:"
            echo "─────────────────────────────────────────────────────────────"
            echo -e "${changes_summary}"
            echo "─────────────────────────────────────────────────────────────"
            echo "  (+ = add new value, ~ = update existing value)"
            echo ""
            read -r -p "Apply these changes to .env? [Y/n]: " apply_changes
            apply_changes="${apply_changes:-Y}"

            if [[ "${apply_changes}" =~ ^[Yy]$ ]]; then
                # Merge secrets into existing .env (only update specific fields)
                [ -n "${N8N_PASSWORD_FROM_SM}" ] && update_env_var "N8N_PASSWORD" "${N8N_PASSWORD_FROM_SM}"
                [ -n "${N8N_ENCRYPTION_KEY_FROM_SM}" ] && update_env_var "N8N_ENCRYPTION_KEY" "${N8N_ENCRYPTION_KEY_FROM_SM}"
                [ -n "${GHOST_KEY_SITE1_FROM_SM}" ] && update_env_var "GHOST_KEY_SITE1" "${GHOST_KEY_SITE1_FROM_SM}"
                [ -n "${GHOST_KEY_SITE2_FROM_SM}" ] && update_env_var "GHOST_KEY_SITE2" "${GHOST_KEY_SITE2_FROM_SM}"

                chmod 600 .env
                echo "✓ Merged Secret Manager values into .env (other values preserved)"

                # Reload updated values
                source .env 2>/dev/null || true
            else
                echo "ℹ Keeping existing .env values"
            fi
        else
            echo "✓ .env is already in sync with Secret Manager"
        fi
        echo ""
    fi

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
        val="${!var:-}"
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
            echo ""
            echo "Please provide values for the missing/placeholder variables:"
            echo "─────────────────────────────────────────────────────────────"
            echo ""

            for var in "${missing_vars[@]}"; do
                case "${var}" in
                    SERVER_EXTERNAL_IP)
                        if [ -n "${DETECTED_IP}" ]; then
                            echo "  (Detected external IP: ${DETECTED_IP})"
                            new_value=$(prompt_value "Server External IP" "${DETECTED_IP}")
                        else
                            new_value=$(prompt_value "Server External IP")
                        fi
                        update_env_var "SERVER_EXTERNAL_IP" "${new_value}"
                        ;;
                    N8N_USER)
                        new_value=$(prompt_value "n8n Admin Username" "admin")
                        update_env_var "N8N_USER" "${new_value}"
                        ;;
                    N8N_PASSWORD)
                        if [ -n "${N8N_PASSWORD_FROM_SM}" ]; then
                            echo "  (Using password from Secret Manager)"
                            update_env_var "N8N_PASSWORD" "${N8N_PASSWORD_FROM_SM}"
                        else
                            new_value=$(prompt_secret "n8n Admin Password")
                            update_env_var "N8N_PASSWORD" "${new_value}"
                        fi
                        ;;
                    N8N_ENCRYPTION_KEY)
                        if [ -n "${N8N_ENCRYPTION_KEY_FROM_SM}" ]; then
                            echo "  (Using encryption key from Secret Manager)"
                            update_env_var "N8N_ENCRYPTION_KEY" "${N8N_ENCRYPTION_KEY_FROM_SM}"
                        else
                            default_key=$(openssl rand -hex 32 2>/dev/null || echo "")
                            if [ -n "${default_key}" ]; then
                                echo "  (Generated encryption key: ${default_key})"
                                new_value=$(prompt_value "n8n Encryption Key" "${default_key}")
                            else
                                new_value=$(prompt_value "n8n Encryption Key (run: openssl rand -hex 32)")
                            fi
                            update_env_var "N8N_ENCRYPTION_KEY" "${new_value}"
                        fi
                        ;;
                    GCS_BUCKET_NAME)
                        new_value=$(prompt_value "GCS Bucket Name")
                        update_env_var "GCS_BUCKET_NAME" "${new_value}"
                        ;;
                esac
            done

            chmod 600 .env
            echo ""
            echo "✓ .env file updated (other values preserved)"
        else
            echo "✗ Please update .env manually and re-run this script."
            exit 1
        fi
    else
        echo "✓ Required .env variables set"
    fi
else
    echo "▶ Creating .env file..."
    echo ""

    echo "Please provide the following configuration values:"
    echo "─────────────────────────────────────────────────────────────"
    echo ""

    # Server IP
    if [ -n "${DETECTED_IP}" ]; then
        echo "  (Detected external IP: ${DETECTED_IP})"
        SERVER_EXTERNAL_IP=$(prompt_value "Server External IP" "${DETECTED_IP}")
    else
        SERVER_EXTERNAL_IP=$(prompt_value "Server External IP (your VM's public IP)")
    fi

    echo ""
    echo "── n8n Configuration ──"
    N8N_USER=$(prompt_value "n8n Admin Username" "admin")

    # Use Secret Manager value or prompt
    if [ -n "${N8N_PASSWORD_FROM_SM}" ]; then
        echo "  (Using password from Secret Manager)"
        N8N_PASSWORD="${N8N_PASSWORD_FROM_SM}"
    else
        N8N_PASSWORD=$(prompt_secret "n8n Admin Password")
    fi

    # Use Secret Manager value or generate/prompt
    if [ -n "${N8N_ENCRYPTION_KEY_FROM_SM}" ]; then
        echo "  (Using encryption key from Secret Manager)"
        N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY_FROM_SM}"
    else
        default_key=$(openssl rand -hex 32 2>/dev/null || echo "")
        if [ -n "${default_key}" ]; then
            echo "  (Generated encryption key: ${default_key})"
            N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key" "${default_key}")
        else
            N8N_ENCRYPTION_KEY=$(prompt_value "n8n Encryption Key (run: openssl rand -hex 32)")
        fi
    fi

    echo ""
    echo "── Google Cloud Storage ──"
    GCS_BUCKET_NAME=$(prompt_value "GCS Bucket Name")

    echo ""
    echo "── vLLM Configuration (optional) ──"
    VLLM_BASE_URL=$(prompt_value "vLLM Base URL" "http://host.docker.internal:8001/v1")
    VLLM_MODEL_NAME=$(prompt_value "vLLM Model Name" "Qwen/Qwen3-14B-AWQ")

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

# Ghost API Keys
GHOST_KEY_SITE1=${GHOST_KEY_SITE1_FROM_SM:-}
GHOST_KEY_SITE2=${GHOST_KEY_SITE2_FROM_SM:-}

# vLLM Configuration
VLLM_BASE_URL=${VLLM_BASE_URL}
VLLM_MODEL_NAME=${VLLM_MODEL_NAME}

# TTS Configuration
TTS_DEVICE=${TTS_DEVICE}
MAX_WORKERS=${MAX_WORKERS}

# General
TIMEZONE=${TIMEZONE}
EOF

    # Secure the .env file
    chmod 600 .env

    echo ""
    echo "─────────────────────────────────────────────────────────────"
    echo "Configuration Summary:"
    echo "─────────────────────────────────────────────────────────────"
    echo "  Server IP      : ${SERVER_EXTERNAL_IP}"
    echo "  n8n User       : ${N8N_USER}"
    if [ -n "${N8N_PASSWORD_FROM_SM}" ]; then
        echo "  n8n Password   : (from Secret Manager)"
    else
        echo "  n8n Password   : (manually entered)"
    fi
    echo "  GCS Bucket     : ${GCS_BUCKET_NAME}"
    echo "  vLLM URL       : ${VLLM_BASE_URL}"
    echo "  vLLM Model     : ${VLLM_MODEL_NAME}"
    echo "  TTS Device     : ${TTS_DEVICE}"
    echo "  Max Workers    : ${MAX_WORKERS}"
    echo "  Timezone       : ${TIMEZONE}"
    [ -n "${GHOST_KEY_SITE1_FROM_SM}" ] && echo "  Ghost Site 1   : (from Secret Manager)"
    [ -n "${GHOST_KEY_SITE2_FROM_SM}" ] && echo "  Ghost Site 2   : (from Secret Manager)"
    echo "─────────────────────────────────────────────────────────────"
    echo ""
    echo "✓ .env file created (permissions: 600)"
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
BUCKET_NAME=$(get_env_var "GCS_BUCKET_NAME")
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
SERVER_IP=$(get_env_var "SERVER_EXTERNAL_IP")
SERVER_IP="${SERVER_IP:-localhost}"
N8N_USER_VAL=$(get_env_var "N8N_USER")
N8N_USER_VAL="${N8N_USER_VAL:-admin}"
GHOST_KEY_SITE1_VAL=$(get_env_var "GHOST_KEY_SITE1")
GHOST_KEY_SITE2_VAL=$(get_env_var "GHOST_KEY_SITE2")

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Services started ✓"
echo "═══════════════════════════════════════════════════════"
echo ""
echo " n8n UI    → http://${SERVER_IP}:5678"
echo "   User   : ${N8N_USER_VAL}"
echo "   Pass   : (from .env or Secret Manager)"
echo ""
echo " TTS API   → http://${SERVER_IP}:8020/docs"
echo " Health    → http://${SERVER_IP}:8020/health"
echo ""
echo "Next steps:"
echo "  1. Open n8n UI and import n8n/workflows/ghost-audio-pipeline.json"
echo "     (n8n menu → Workflows → Import from file)"
if [ -z "${GHOST_KEY_SITE1_VAL}" ] || [ -z "${GHOST_KEY_SITE2_VAL}" ]; then
    echo "  2. In n8n: Settings → Variables → add:"
    [ -z "${GHOST_KEY_SITE1_VAL}" ] && echo "     - GHOST_KEY_SITE1 (Ghost Content API key for site 1)"
    [ -z "${GHOST_KEY_SITE2_VAL}" ] && echo "     - GHOST_KEY_SITE2 (Ghost Content API key for site 2)"
else
    echo "  2. Ghost API keys were loaded from Secret Manager ✓"
fi
echo "  3. In n8n: Activate the workflow (toggle at top-right)"
echo "  4. In Ghost Admin (both sites):"
echo "     Settings → Integrations → Webhooks → Add webhook"
echo "     Event: Post published"
echo "     URL:   http://${SERVER_IP}:5678/webhook/ghost-published"
echo "  5. Test by publishing a post on one of your Ghost sites"
echo ""
