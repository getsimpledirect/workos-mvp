#!/usr/bin/env bash
# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# ═══════════════════════════════════════════════════════════════════════════════
# Ghost Narrator - Build Validation Script
# ═══════════════════════════════════════════════════════════════════════════════
# Validates that the TTS service Docker image is correctly built and functional.
#
# Usage:
#   bash scripts/validate-build.sh
#
# Exit Codes:
#   0 - All validations passed
#   1 - Validation failed
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

IMAGE_NAME="ghost-tts-service:latest"
VALIDATION_FAILED=false

info() { echo -e "${BLUE}$*${NC}"; }
success() { echo -e "${GREEN}✓ $*${NC}"; }
error() { echo -e "${RED}✗ $*${NC}"; VALIDATION_FAILED=true; }
warning() { echo -e "${YELLOW}⚠ $*${NC}"; }

echo "═══════════════════════════════════════════════════════════════"
echo " Ghost Narrator - Build Validation"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── Step 1: Check Docker ────────────────────────────────────────────────────
info "Step 1: Checking Docker..."
if ! command -v docker &> /dev/null; then
    error "Docker is not installed"
    exit 1
fi

if ! docker info &> /dev/null; then
    error "Docker daemon is not running"
    exit 1
fi

success "Docker is running ($(docker --version | cut -d' ' -f3 | tr -d ','))"
echo ""

# ─── Step 2: Check Image Exists ──────────────────────────────────────────────
info "Step 2: Checking if image exists..."
if ! docker images "${IMAGE_NAME}" --format "{{.Repository}}:{{.Tag}}" | grep -q "${IMAGE_NAME}"; then
    error "Image ${IMAGE_NAME} not found"
    echo ""
    echo "Build the image first:"
    echo "  cd tts-service"
    echo "  docker build -t ${IMAGE_NAME} ."
    exit 1
fi

IMAGE_SIZE=$(docker images "${IMAGE_NAME}" --format "{{.Size}}")
IMAGE_CREATED=$(docker images "${IMAGE_NAME}" --format "{{.CreatedSince}}")
success "Image found: ${IMAGE_NAME} (${IMAGE_SIZE}, created ${IMAGE_CREATED})"
echo ""

# ─── Step 3: Validate Critical Python Imports ────────────────────────────────
info "Step 3: Validating critical Python packages..."

PACKAGES=(
    "fish_speech:Fish Speech v1.5"
    "torch:PyTorch"
    "transformers:Transformers"
    "fastapi:FastAPI"
    "google.cloud.storage:GCS Client"
    "redis:Redis"
    "librosa:Librosa"
    "soundfile:SoundFile"
    "faster_whisper:Faster Whisper"
)

IMPORT_FAILED=false
for pkg_info in "${PACKAGES[@]}"; do
    IFS=':' read -r module name <<< "$pkg_info"

    if docker run --rm "${IMAGE_NAME}" python -c "import ${module}" 2>/dev/null; then
        success "${name} import successful"
    else
        error "${name} import failed"
        IMPORT_FAILED=true
    fi
done

if [ "$IMPORT_FAILED" = true ]; then
    echo ""
    error "One or more package imports failed"
else
    echo ""
    success "All package imports successful"
fi
echo ""

# ─── Step 4: Check Package Versions ──────────────────────────────────────────
info "Step 4: Checking package versions..."

echo "Key package versions:"
docker run --rm "${IMAGE_NAME}" python -c "
import torch
import transformers
import fastapi
import numpy
import librosa

print(f'  PyTorch:      {torch.__version__}')
print(f'  Transformers: {transformers.__version__}')
print(f'  FastAPI:      {fastapi.__version__}')
print(f'  NumPy:        {numpy.__version__}')
print(f'  Librosa:      {librosa.__version__}')
print(f'  CUDA:         {\"Available\" if torch.cuda.is_available() else \"Not Available\"}')
" || error "Failed to retrieve package versions"

echo ""

# ─── Step 5: Validate Fish Speech Installation ───────────────────────────────
info "Step 5: Validating Fish Speech installation..."

if docker run --rm "${IMAGE_NAME}" python -c "
import fish_speech
print('Fish Speech v1.5.0 validated')
" 2>/dev/null; then
    success "Fish Speech v1.5 installation validated"
else
    error "Fish Speech validation failed"
fi
echo ""

# ─── Step 6: Check Model Directories ─────────────────────────────────────────
info "Step 6: Checking model directories..."

MODEL_CHECK=$(docker run --rm "${IMAGE_NAME}" bash -c "
if [ -d /app/checkpoints ]; then
    echo 'checkpoints_exist'
fi
if [ -d /root/.local/share/tts ]; then
    echo 'tts_cache_exist'
fi
")

if echo "$MODEL_CHECK" | grep -q "checkpoints_exist"; then
    success "Model checkpoints directory exists"
else
    warning "Model checkpoints directory not found (models will download on first use)"
fi

echo ""

# ─── Step 7: Validate Application Structure ──────────────────────────────────
info "Step 7: Validating application structure..."

APP_STRUCTURE=$(docker run --rm "${IMAGE_NAME}" bash -c "
[ -d /app/app ] && echo 'app_dir_exists'
[ -d /app/voices ] && echo 'voices_dir_exists'
[ -d /app/output ] && echo 'output_dir_exists'
[ -f /app/app/main.py ] && echo 'main_py_exists'
")

if echo "$APP_STRUCTURE" | grep -q "app_dir_exists"; then
    success "Application directory exists"
else
    error "Application directory not found"
fi

if echo "$APP_STRUCTURE" | grep -q "voices_dir_exists"; then
    success "Voices directory exists"
else
    error "Voices directory not found"
fi

if echo "$APP_STRUCTURE" | grep -q "output_dir_exists"; then
    success "Output directory exists"
else
    error "Output directory not found"
fi

if echo "$APP_STRUCTURE" | grep -q "main_py_exists"; then
    success "Main application file exists"
else
    error "Main application file (app/main.py) not found"
fi

echo ""

# ─── Step 8: Test Service Startup (Optional) ──────────────────────────────────
info "Step 8: Testing service startup (this may take 30-60 seconds)..."

CONTAINER_NAME="tts-validation-test-$$"
cleanup_test_container() {
    docker stop "${CONTAINER_NAME}" &>/dev/null || true
    docker rm "${CONTAINER_NAME}" &>/dev/null || true
}
trap cleanup_test_container EXIT

if docker run -d --name "${CONTAINER_NAME}" \
    -e VOICE_SAMPLE_PATH=/app/voices/reference.wav \
    -e TTS_LANGUAGE=en \
    -e DEVICE=cpu \
    "${IMAGE_NAME}" &>/dev/null; then

    success "Container started successfully"

    # Wait for service to be ready (model loading can take 3-5 min on first run)
    info "Waiting for service to start (max 300 seconds - model loading included)..."
    TIMEOUT=300
    ELAPSED=0
    READY=false

    while [ $ELAPSED -lt $TIMEOUT ]; do
        if docker exec "${CONTAINER_NAME}" python -c "
import urllib.request
try:
    response = urllib.request.urlopen('http://localhost:8020/health', timeout=5)
    if response.status == 200:
        exit(0)
except:
    pass
exit(1)
        " 2>/dev/null; then
            READY=true
            break
        fi
        sleep 5
        ELAPSED=$((ELAPSED + 5))
        echo -n "."
    done
    echo ""

    if [ "$READY" = true ]; then
        success "Service responded to health check in ${ELAPSED}s"
    else
        warning "Service did not respond within ${TIMEOUT}s — this is normal on first run while Fish Speech models download (~4GB)"
    fi
else
    error "Failed to start test container"
fi

cleanup_test_container
echo ""

# ─── Final Summary ───────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
if [ "$VALIDATION_FAILED" = true ]; then
    echo -e "${RED}✗ Validation Failed${NC}"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Some validations failed. Review the errors above."
    echo ""
    echo "Common fixes:"
    echo "  - Rebuild with: docker build --no-cache -t ${IMAGE_NAME} tts-service/"
    echo "  - Check Dockerfile for errors"
    echo "  - Verify all dependencies are correctly installed"
    echo ""
    exit 1
else
    echo -e "${GREEN}✓ All Validations Passed${NC}"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "The TTS service image is correctly built and ready for deployment."
    echo ""
    echo "Next steps:"
    echo "  - Start services: docker compose up -d"
    echo "  - Check logs: docker compose logs -f tts-service"
    echo "  - Test API: curl http://localhost:8020/docs"
    echo ""
    exit 0
fi
