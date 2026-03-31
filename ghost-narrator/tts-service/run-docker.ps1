#!/usr/bin/env pwsh
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

param(
    [switch]$Detached,
    [switch]$Stop,
    [switch]$Logs,
    [switch]$Rebuild,
    [switch]$Clean,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$CONTAINER_NAME = "tts-service"
$IMAGE_NAME = "ghost-tts-service:latest"
$HOST_PORT = 8020
$CONTAINER_PORT = 8020


function Write-Info { Write-Host $args -ForegroundColor Cyan }
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host $args -ForegroundColor Red }
function Write-Warning { Write-Host $args -ForegroundColor Yellow }


if ($Help) {
    Write-Info "═══════════════════════════════════════════════════════════════"
    Write-Info "TTS Service - Docker Runner"
    Write-Info "═══════════════════════════════════════════════════════════════"
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\run-docker.ps1              Build and run in foreground"
    Write-Host "  .\run-docker.ps1 -Detached    Build and run in background"
    Write-Host "  .\run-docker.ps1 -Stop        Stop the running container"
    Write-Host "  .\run-docker.ps1 -Logs        View container logs"
    Write-Host "  .\run-docker.ps1 -Rebuild     Force rebuild image"
    Write-Host "  .\run-docker.ps1 -Clean       Deep clean Docker (prune unused)"
    Write-Host "  .\run-docker.ps1 -Help        Show this help"
    Write-Host ""
    Write-Host "Environment Variables:"
    Write-Host "  TTS_DEVICE        cpu or cuda (default: cpu)"
    Write-Host "  TTS_LANGUAGE      Language code (default: en)"
    Write-Host "  MAX_CHUNK_WORDS   Max words per chunk (default: 200)"
    Write-Host "  MAX_WORKERS       Thread pool size for parallel synthesis (default: 4)"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  # Run in background"
    Write-Host "  .\run-docker.ps1 -Detached"
    Write-Host ""
    Write-Host "  # Use GPU acceleration"
    Write-Host "  `$env:TTS_DEVICE='cuda'; .\run-docker.ps1"
    Write-Host ""
    Write-Host "  # View logs"
    Write-Host "  .\run-docker.ps1 -Logs"
    Write-Host ""
    Write-Host "  # Stop service"
    Write-Host "  .\run-docker.ps1 -Stop"
    Write-Host ""
    exit 0
}


function Test-Docker {
    try {
        docker version | Out-Null
        return $true
    }
    catch {
        Write-Error "ERROR: Docker is not running or not installed."
        Write-Host ""
        Write-Host "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
        Write-Host "Or start Docker Desktop if already installed."
        exit 1
    }
}


if ($Stop) {
    Write-Info "Stopping TTS service container..."

    if (docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$") {
        docker stop $CONTAINER_NAME
        docker rm $CONTAINER_NAME
        Write-Success "✓ Container stopped and removed."
    }
    else {
        Write-Warning "Container '$CONTAINER_NAME' is not running."
    }
    exit 0
}


if ($Logs) {
    Write-Info "Showing logs for TTS service (Ctrl+C to exit)..."
    Write-Host ""

    if (docker ps --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$") {
        docker logs -f $CONTAINER_NAME
    }
    else {
        Write-Error "ERROR: Container '$CONTAINER_NAME' is not running."
        Write-Host "Start it with: .\run-docker.ps1"
        exit 1
    }
    exit 0
}


Write-Info "═══════════════════════════════════════════════════════════════"
Write-Info "TTS Service - Docker Setup"
Write-Info "═══════════════════════════════════════════════════════════════"
Write-Host ""


Test-Docker
 
if ($Clean) {
    Write-Info "Performing deep Docker cleanup..."
    if (docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$") {
        Write-Info "Stopping and removing container..."
        docker stop $CONTAINER_NAME | Out-Null
        docker rm $CONTAINER_NAME | Out-Null
    }
    if (docker images -q $IMAGE_NAME) {
        Write-Info "Removing image $IMAGE_NAME..."
        docker rmi $IMAGE_NAME -f | Out-Null
    }
    Write-Info "Pruning unused Docker networks and cache..."
    docker network prune -f | Out-Null
    docker system prune -f --filter "label=com.docker.compose.project=tts-service" | Out-Null
    # Note: We don't prune volumes by default to keep model cache, 
    # but user can run 'docker volume prune' if needed.
    Write-Success "✓ Docker environment cleaned."
}


$isRunning = docker ps --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$"

if ($isRunning -and -not $Rebuild) {
    Write-Warning "Container '$CONTAINER_NAME' is already running."
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  View logs:        .\run-docker.ps1 -Logs"
    Write-Host "  Stop service:     .\run-docker.ps1 -Stop"
    Write-Host "  Restart:          .\run-docker.ps1 -Stop; .\run-docker.ps1"
    Write-Host "  Force rebuild:    .\run-docker.ps1 -Rebuild"
    Write-Host ""
    Write-Info "Service is running at: http://localhost:$HOST_PORT"
    Write-Info "Health check: http://localhost:$HOST_PORT/health"
    Write-Info "API docs: http://localhost:$HOST_PORT/docs"
    exit 0
}


if ($Rebuild -and $isRunning) {
    Write-Info "Stopping existing container for rebuild..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
}


$isStopped = docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$"
if ($isStopped) {
    Write-Info "Removing stopped container..."
    docker rm $CONTAINER_NAME
}


if (-not (Test-Path ".\voices")) {
    Write-Info "Creating voices directory..."
    New-Item -ItemType Directory -Path ".\voices" | Out-Null
}


if (-not (Test-Path ".\voices\reference.wav")) {
    Write-Warning "WARNING: Reference voice file not found!"
    Write-Host ""
    Write-Host "Please add your reference voice WAV file to:"
    Write-Host "  .\voices\reference.wav"
    Write-Host ""
    Write-Host "Requirements:"
    Write-Host "  - Format: WAV, 22.05 kHz, mono"
    Write-Host "  - Duration: 45-60 seconds (minimum 6 seconds)"
    Write-Host "  - Quality: Clear speech, no background noise"
    Write-Host ""
    Write-Host "To convert audio:"
    Write-Host "  ffmpeg -i input.mp3 -ar 22050 -ac 1 .\voices\reference.wav"
    Write-Host ""
    Write-Error "Cannot continue without reference voice file."
    exit 1
}

Write-Success "✓ Reference voice file found."
Write-Host ""


Write-Info "Building Docker image (this may take a few minutes on first run)..."
Write-Host ""

$buildArgs = @("build", "-t", $IMAGE_NAME, ".")

if ($Rebuild) {
    $buildArgs += "--no-cache"
}

docker @buildArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "ERROR: Docker build failed."
    exit 1
}

Write-Success "✓ Image built successfully."
Write-Host ""


$TTS_LANG = if ($env:TTS_LANGUAGE) { $env:TTS_LANGUAGE } else { 'en' }
$MAX_WORDS = if ($env:MAX_CHUNK_WORDS) { $env:MAX_CHUNK_WORDS } else { '200' }
$DEVICE_TYPE = if ($env:TTS_DEVICE) { $env:TTS_DEVICE } else { 'cpu' }
$WORKERS = if ($env:MAX_WORKERS) { $env:MAX_WORKERS } else { '4' }

$envVars = @(
    "-e", "VOICE_SAMPLE_PATH=/app/voices/reference.wav",
    "-e", "TTS_LANGUAGE=$TTS_LANG",
    "-e", "MAX_CHUNK_WORDS=$MAX_WORDS",
    "-e", "DEVICE=$DEVICE_TYPE",
    "-e", "MAX_WORKERS=$WORKERS"
)


if ($env:GCS_BUCKET_NAME) {
    $envVars += "-e", "GCS_BUCKET_NAME=$env:GCS_BUCKET_NAME"
}
if ($env:GCS_AUDIO_PREFIX) {
    $envVars += "-e", "GCS_AUDIO_PREFIX=$env:GCS_AUDIO_PREFIX"
}
if ($env:N8N_CALLBACK_URL) {
    $envVars += "-e", "N8N_CALLBACK_URL=$env:N8N_CALLBACK_URL"
}


Write-Info "Setting up Docker volumes..."
docker volume create tts_output | Out-Null
docker volume create tts_model_cache | Out-Null


Write-Info "Starting TTS service container..."
Write-Host ""

$runArgs = @(
    "run",
    "--name", $CONTAINER_NAME,
    "--restart", "unless-stopped",
    "-p", "${HOST_PORT}:${CONTAINER_PORT}",
    "-v", "$PWD\voices:/app/voices:ro",
    "-v", "tts_output:/app/output",
    "-v", "tts_model_cache:/root/.local/share/tts"
) + $envVars

if ($Detached) {
    $runArgs += "-d"
    docker @runArgs $IMAGE_NAME

    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERROR: Failed to start container."
        exit 1
    }

    Write-Success "✓ TTS service started successfully in background!"
    Write-Host ""
    Write-Info "Service is running at: http://localhost:$HOST_PORT"
    Write-Info "Health check: http://localhost:$HOST_PORT/health"
    Write-Info "API docs: http://localhost:$HOST_PORT/docs"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  View logs:     .\run-docker.ps1 -Logs"
    Write-Host "  Stop service:  .\run-docker.ps1 -Stop"
    Write-Host ""
    Write-Info "Note: First run will download ~4GB Fish Speech v1.5 models (cached for future runs)."
}
else {
    $runArgs += "-it"
    Write-Info "Starting in foreground mode (Ctrl+C to stop)..."
    Write-Host ""
    Write-Info "Service will be available at: http://localhost:$HOST_PORT"
    Write-Host ""

    docker @runArgs $IMAGE_NAME
}
