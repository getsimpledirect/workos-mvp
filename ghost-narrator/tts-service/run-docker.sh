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

set -e

CONTAINER_NAME="tts-service"
IMAGE_NAME="ghost-tts-service:latest"
HOST_PORT=8020
CONTAINER_PORT=8020

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}$*${NC}"; }
success() { echo -e "${GREEN}$*${NC}"; }
error() { echo -e "${RED}$*${NC}"; }
warning() { echo -e "${YELLOW}$*${NC}"; }

DETACHED=false
STOP=false
LOGS=false
REBUILD=false
CLEAN=false
HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--detached) DETACHED=true; shift ;;
        -s|--stop) STOP=true; shift ;;
        -l|--logs) LOGS=true; shift ;;
        -r|--rebuild) REBUILD=true; shift ;;
        -c|--clean) CLEAN=true; shift ;;
        -h|--help) HELP=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ "$HELP" = true ]; then
    info "═══════════════════════════════════════════════════════════════"
    info "TTS Service - Docker Runner"
    info "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Usage:"
    echo "  ./run-docker.sh              Build and run in foreground"
    echo "  ./run-docker.sh --detached   Build and run in background"
    echo "  ./run-docker.sh --stop       Stop the running container"
    echo "  ./run-docker.sh --logs       View container logs"
    echo "  ./run-docker.sh --rebuild    Force rebuild image"
    echo "  ./run-docker.sh --clean      Deep clean Docker (prune unused)"
    echo "  ./run-docker.sh --help       Show this help"
    echo ""
    echo "Environment Variables:"
    echo "  TTS_DEVICE        cpu or cuda (default: cpu)"
    echo "  TTS_LANGUAGE      Language code (default: en)"
    echo "  MAX_CHUNK_WORDS   Max words per chunk (default: 200)"
    echo "  MAX_WORKERS       Thread pool size for parallel synthesis (default: 4)"
    echo ""
    echo "Examples:"
    echo "  # Run in background"
    echo "  ./run-docker.sh --detached"
    echo ""
    echo "  # Use GPU acceleration"
    echo "  TTS_DEVICE=cuda ./run-docker.sh"
    echo ""
    echo "  # View logs"
    echo "  ./run-docker.sh --logs"
    echo ""
    echo "  # Stop service"
    echo "  ./run-docker.sh --stop"
    echo ""
    exit 0
fi

check_docker() {
    if ! command -v docker &> /dev/null; then
        error "ERROR: Docker is not installed."
        echo ""
        echo "Please install Docker from: https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        error "ERROR: Docker is not running."
        echo ""
        echo "Please start Docker and try again."
        exit 1
    fi
}

if [ "$STOP" = true ]; then
    info "Stopping TTS service container..."

    if docker ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        docker stop "$CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
        success "✓ Container stopped and removed."
    else
        warning "Container '$CONTAINER_NAME' is not running."
    fi
    exit 0
fi

if [ "$LOGS" = true ]; then
    info "Showing logs for TTS service (Ctrl+C to exit)..."
    echo ""

    if docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        docker logs -f "$CONTAINER_NAME"
    else
        error "ERROR: Container '$CONTAINER_NAME' is not running."
        echo "Start it with: ./run-docker.sh"
        exit 1
    fi
    exit 0
fi

info "═══════════════════════════════════════════════════════════════"
info "TTS Service - Docker Setup"
info "═══════════════════════════════════════════════════════════════"
echo ""

check_docker
 
if [ "$CLEAN" = true ]; then
    info "Performing deep Docker cleanup..."
    if docker ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        info "Stopping and removing container..."
        docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
        docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
    fi
    if [ -n "$(docker images -q "$IMAGE_NAME")" ]; then
        info "Removing image $IMAGE_NAME..."
        docker rmi "$IMAGE_NAME" -f > /dev/null 2>&1 || true
    fi
    info "Pruning unused Docker systems..."
    docker system prune -f --filter "label=com.docker.compose.project=tts-service" > /dev/null 2>&1 || true
    success "✓ Docker environment cleaned."
fi

if docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    if [ "$REBUILD" = false ]; then
        warning "Container '$CONTAINER_NAME' is already running."
        echo ""
        echo "Options:"
        echo "  View logs:        ./run-docker.sh --logs"
        echo "  Stop service:     ./run-docker.sh --stop"
        echo "  Restart:          ./run-docker.sh --stop && ./run-docker.sh"
        echo "  Force rebuild:    ./run-docker.sh --rebuild"
        echo ""
        info "Service is running at: http://localhost:$HOST_PORT"
        info "Health check: http://localhost:$HOST_PORT/health"
        info "API docs: http://localhost:$HOST_PORT/docs"
        exit 0
    fi
fi

if [ "$REBUILD" = true ]; then
    if docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        info "Stopping existing container for rebuild..."
        docker stop "$CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
    fi
fi

if docker ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    info "Removing stopped container..."
    docker rm "$CONTAINER_NAME"
fi

if [ ! -d "./voices" ]; then
    info "Creating voices directory..."
    mkdir -p ./voices
fi

if [ ! -f "./voices/reference.wav" ]; then
    warning "WARNING: Reference voice file not found!"
    echo ""
    echo "Please add your reference voice WAV file to:"
    echo "  ./voices/reference.wav"
    echo ""
    echo "Requirements:"
    echo "  - Format: WAV, 22.05 kHz, mono"
    echo "  - Duration: 45-60 seconds (minimum 6 seconds)"
    echo "  - Quality: Clear speech, no background noise"
    echo ""
    echo "To convert audio:"
    echo "  ffmpeg -i input.mp3 -ar 22050 -ac 1 ./voices/reference.wav"
    echo ""
    error "Cannot continue without reference voice file."
    exit 1
fi

success "✓ Reference voice file found."
echo ""

info "Building Docker image (this may take a few minutes on first run)..."
echo ""

BUILD_ARGS="build -t $IMAGE_NAME ."
if [ "$REBUILD" = true ]; then
    BUILD_ARGS="build --no-cache -t $IMAGE_NAME ."
fi

docker $BUILD_ARGS

if [ $? -ne 0 ]; then
    error "ERROR: Docker build failed."
    exit 1
fi

success "✓ Image built successfully."
echo ""

TTS_LANG="${TTS_LANGUAGE:-en}"
MAX_WORDS="${MAX_CHUNK_WORDS:-200}"
DEVICE_TYPE="${TTS_DEVICE:-cpu}"
WORKERS="${MAX_WORKERS:-4}"

ENV_VARS=(
    "-e" "VOICE_SAMPLE_PATH=/app/voices/reference.wav"
    "-e" "TTS_LANGUAGE=$TTS_LANG"
    "-e" "MAX_CHUNK_WORDS=$MAX_WORDS"
    "-e" "DEVICE=$DEVICE_TYPE"
    "-e" "MAX_WORKERS=$WORKERS"
)

if [ -n "$GCS_BUCKET_NAME" ]; then
    ENV_VARS+=("-e" "GCS_BUCKET_NAME=$GCS_BUCKET_NAME")
fi
if [ -n "$GCS_AUDIO_PREFIX" ]; then
    ENV_VARS+=("-e" "GCS_AUDIO_PREFIX=$GCS_AUDIO_PREFIX")
fi
if [ -n "$N8N_CALLBACK_URL" ]; then
    ENV_VARS+=("-e" "N8N_CALLBACK_URL=$N8N_CALLBACK_URL")
fi

info "Setting up Docker volumes..."
docker volume create tts_output > /dev/null
docker volume create tts_model_cache > /dev/null

info "Starting TTS service container..."
echo ""

RUN_ARGS=(
    "run"
    "--name" "$CONTAINER_NAME"
    "--restart" "unless-stopped"
    "-p" "${HOST_PORT}:${CONTAINER_PORT}"
    "-v" "$(pwd)/voices:/app/voices:ro"
    "-v" "tts_output:/app/output"
    "-v" "tts_model_cache:/root/.local/share/tts"
)

RUN_ARGS+=("${ENV_VARS[@]}")

if [ "$DETACHED" = true ]; then
    RUN_ARGS+=("-d")
    docker "${RUN_ARGS[@]}" "$IMAGE_NAME"

    if [ $? -ne 0 ]; then
        error "ERROR: Failed to start container."
        exit 1
    fi

    success "✓ TTS service started successfully in background!"
    echo ""
    info "Service is running at: http://localhost:$HOST_PORT"
    info "Health check: http://localhost:$HOST_PORT/health"
    info "API docs: http://localhost:$HOST_PORT/docs"
    echo ""
    echo "Commands:"
    echo "  View logs:     ./run-docker.sh --logs"
    echo "  Stop service:  ./run-docker.sh --stop"
    echo ""
    info "Note: First run will download ~4GB Fish Speech v1.5 models (cached for future runs)."
else
    RUN_ARGS+=("-it")
    info "Starting in foreground mode (Ctrl+C to stop)..."
    echo ""
    info "Service will be available at: http://localhost:$HOST_PORT"
    echo ""

    docker "${RUN_ARGS[@]}" "$IMAGE_NAME"
fi
