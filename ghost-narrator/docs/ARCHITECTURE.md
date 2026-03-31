# Ghost Narrator — Complete Architecture & Setup Guide

> **Automated voice-narrated audio from your Ghost CMS articles, powered by Fish Speech v1.5 voice cloning and parallel CPU synthesis.**

---

## Table of Contents

1. [What This Pipeline Does](#what-this-pipeline-does)
2. [Architecture Overview](#architecture-overview)
3. [Build & Deployment](#build--deployment)
4. [TTS Service Overview](#tts-service-overview)
5. [Component Deep Dive](#component-deep-dive)
6. [VRAM Budget & Resource Planning](#vram-budget--resource-planning)
7. [Directory Structure](#directory-structure)
8. [Step-by-Step Setup](#step-by-step-setup)
9. [n8n Workflow — Node-by-Node Explanation](#n8n-workflow--node-by-node-explanation)
10. [Ghost Webhook Configuration](#ghost-webhook-configuration)
11. [Voice Clone Preparation](#voice-clone-preparation)
12. [GCS Bucket & IAM Setup](#gcs-bucket--iam-setup)
13. [Testing & Troubleshooting](#testing--troubleshooting)
14. [Backfilling Audio for Existing Posts](#backfilling-audio-for-existing-posts)
15. [Cost Analysis](#cost-analysis)

---

## What This Pipeline Does

Every time you publish a post on your [Ghost](https://ghost.org/) website, this pipeline automatically:

1. **Detects** the new article via a Ghost webhook
2. **Fetches** the full article text using the Ghost Content API
3. **Rewrites** the article into podcast-style narration using your existing **Qwen3-14B** model via vLLM
4. **Synthesises** audio using **Fish Speech v1.5** with your **cloned voice** (from your 45-second sample)
   - **CPU Mode**: Parallel synthesis with configurable workers (default: 4 workers, ~50-60s for 2000 words)
   - **GPU Mode**: Sequential synthesis (~20-30s for 2000 words)
5. **Uploads** the MP3 to your **GCS bucket** at a predictable path
6. **Embeds** an HTML5 audio player back into the Ghost post (optional)

**Key Features:**
- Zero-shot voice cloning from 6-60 seconds of reference audio
- Professional audio mastering (-23 LUFS normalization, -16 LUFS final output)
- Dynamic gap insertion between chunks for natural pacing
- Streaming concatenation for memory-efficient processing of long articles (5000+ words)
- Redis-backed job persistence with automatic fallback to in-memory storage
- Async processing with webhook callbacks

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     GCP Compute Engine (L4 GPU VM)                       │
│                     4 vCPUs · 16GB RAM · 16GB VRAM · 300GB SSD          │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Docker Network                             │    │
│  │                                                                   │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │    │
│  │  │   Open WebUI │  │   vLLM API   │  │   TTS Service        │   │    │
│  │  │  (with Web   │  │  Qwen3-14B   │  │   Fish Speech v1.5   │   │    │
│  │  │   Search via │  │  :8001       │  │   :8020              │   │    │
│  │  │   SearXNG)   │  │  ~8GB VRAM   │  │   CPU: ~1GB RAM      │   │    │
│  │  │   :3000      │  │              │  │   GPU: ~3GB VRAM     │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │    │
│  │                                                                   │    │
│  │  ┌──────────────┐  ┌──────────────┐                             │    │
│  │  │    n8n       │  │  Redis       │                             │    │
│  │  │  Workflow    │  │  Job Store   │                             │    │
│  │  │  :5678       │  │  :6379       │                             │    │
│  │  └──────┬───────┘  └──────┬───────┘                             │    │
│  │         │                                                         │    │
│  └─────────┼───────────────────────────────────────────────────────┘    │
│            │                                                              │
└────────────┼──────────────────────────────────────────────────────────── ┘
             │
             │  Orchestration Flow
             │
             │  Ghost Webhook → n8n Pipeline (POST /webhook/ghost-published)
             │  n8n Pipeline → vLLM  (convert article to narration script)
             │  n8n Pipeline → TTS   (synthesize MP3 with cloned voice)
             │  TTS Service → GCS   (upload MP3)
             │  TTS Service → n8n Callback (POST /webhook/tts-callback)
             │  n8n Callback → Ghost (embed audio player in post via Admin API)
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         External Services                                 │
│                                                                           │
│  ┌──────────────────────┐       ┌──────────────────────┐                │
│  │  Ghost CMS Site 1    │       │  Ghost CMS Site 2    │                │
│  │  ghost-site-1.com  │       │  ghost-site-2.com│                │
│  │  (sends webhooks)    │       │  (sends webhooks)    │                │
│  └──────────────────────┘       └──────────────────────┘                │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  Google Cloud Storage                                          │       │
│  │  gs://YOUR_BUCKET/audio/articles/site/slug.mp3               │       │
│  └──────────────────────────────────────────────────────────────┘       │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Build & Deployment

### TTS Service Build Architecture

The TTS service uses a **modern uv-based Dockerfile** for deterministic and lightning-fast dependency resolution, eliminating the legacy `resolution-too-deep` errors that often plagued PyTorch + Transformers environments.

**Build Strategy:**
- Utilizes `uv` for rust-based, parallel dependency resolution and installation.
- Eliminates legacy O(n!) pip resolution timeouts.
- Pre-downloads Fish Speech and Whisper weights during the image build for faster cold starts.
- Integrates comprehensive health checks validating critical library imports (PyTorch, librosa).
- Total build time: 2-5 minutes (first build), <30 seconds (cached)

### Resource Requirements

**Minimum for Build:**
- **RAM**: 8GB allocated to Docker Desktop
- **Disk Space**: 20GB free (includes base images, layers, models)
- **Network**: Stable connection (~7GB download for models + packages)
- **Time**: 2-5 minutes first build, model download can add 2-3 minutes

**Runtime Resources (per docker-compose.yml):**
- **CPU Mode (Recommended)**: 1GB RAM, 4 CPU cores per worker
  - Parallel synthesis with configurable MAX_WORKERS
  - Default: 4 workers = ~50-60s for 2000-word article
  - Memory-efficient streaming concatenation for large files
- **GPU Mode**: 3GB VRAM, 6GB RAM
  - Sequential synthesis
  - ~20-30s for 2000-word article

### Deployment via init.sh

The `scripts/init.sh` script handles production deployment with:

**Features:**
- Automatic GCP secret retrieval and .env synchronization
- Docker resource validation (memory, disk space)
- Build retry logic (up to 2 attempts with cache cleanup)
- Image validation after build
- Service health monitoring with 5-minute timeout
- Detailed error messages and troubleshooting guidance

**Usage:**
```bash
cd ghost-narrator
bash scripts/init.sh
```

The script will:
1. ✓ Detect and sync GCP secrets to `.env`
2. ✓ Validate environment variables
3. ✓ Check Docker resources (memory, disk)
4. ✓ Build TTS service with retry on failure
5. ✓ Start all services (Redis → n8n → TTS)
6. ✓ Wait for health checks (up to 5 minutes)
7. ✓ Display service URLs and next steps

**Note:** The `scripts/init.sh` script is designed for Linux/Unix environments. For Windows deployment, use Docker Compose directly or WSL2.

### Common Build Issues & Solutions

#### 1. Dependency Resolution Error
```
error: resolution-too-deep
× Dependency resolution exceeded maximum depth
```

**Solution:** Already fixed in Dockerfile. If you still see this:
- Use `--no-cache` flag: `docker compose build --no-cache tts-service`
- Ensure you're using the latest Dockerfile (uv-based build)
- Verify 8GB+ RAM allocated to Docker

#### 2. Out of Memory (Build Killed)
```
Killed
exit code: 137
```

**Solution:**
- Increase Docker Desktop memory: Settings → Resources → Memory → 8GB+
- Close other applications during build
- Check available system RAM: `free -h` (Linux) or Activity Monitor (Mac)

#### 3. No Space Left on Device
```
no space left on device
write /var/lib/docker: no space left on device
```

**Solution:**
```bash
# Clean Docker system
docker system prune -a --volumes

# Check disk usage
docker system df

# Ensure 20GB+ free space
df -h
```

#### 4. Network Timeout
```
ReadTimeoutError: HTTPSConnectionPool
Could not fetch URL
```

**Solution:**
- Check internet connection stability
- The Dockerfile already sets `PIP_DEFAULT_TIMEOUT=300` and `PIP_RETRIES=5`
- If in restricted network, configure pip mirror in Dockerfile
- Retry build (network issues are often transient)

#### 5. Model Download Warnings
```
⚠ Fish Speech model download failed - will download on first use
```

**Impact:** This is a warning, not a fatal error. Models download automatically when the service starts.

**To pre-download during build:**
- Ensure stable internet connection during build
- Models are cached in Docker volume `tts_model_cache`
- Total download: ~7GB (Fish Speech v1.5 ~4GB + Whisper models ~75MB + dependencies)

### Manual Build (Advanced)

For detailed build output and debugging:

```bash
cd tts-service

# Build with full progress output
docker build --progress=plain --no-cache -t ghost-tts-service:latest .

# Test specific stage (e.g., stage 6 - Gradio installation)
docker build --target=gradio_stage -t test-build .

# Validate built image
docker run --rm ghost-tts-service:latest python -c "
import fish_speech
import torch
import fastapi
print('✓ All critical imports successful')
"
```

### Production Deployment Checklist

Before deploying to production:

- [ ] GCP secrets configured and synced to `.env`
- [ ] Voice reference file prepared (`tts-service/voices/reference.wav`)
- [ ] Docker Desktop allocated 8GB+ RAM
- [ ] 20GB+ free disk space available
- [ ] Stable internet connection for initial build
- [ ] Firewall allows ports: 5678 (n8n), 8020 (TTS), 6379 (Redis)
- [ ] Ghost webhook URLs configured in Ghost admin
- [ ] GCS bucket created with proper IAM permissions
- [ ] VLLM service running and accessible at configured URL

### Build Performance

**Measured Build Times (GCP L4 VM):**
- First build (no cache): 18-22 minutes
- Rebuild with cache (code changes only): 45-90 seconds
- Model download on first run: 5-8 minutes

**Build Stages Most Likely to Timeout:**
- Stage 6 (Gradio): Complex dependency resolution
- Stage 17 (modelscope/funasr): Large package downloads
- Stage 20 (fish-speech): GitHub clone and setup

**Optimization Tips:**
- Use `--cache-from` to leverage CI/CD build cache
- Pre-pull base image: `docker pull pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`
- Keep Docker in good health: `docker system prune` weekly

### Verifying Successful Build

After build completes, verify the installation:

```bash
# Quick validation
docker run --rm ghost-tts-service:latest python -c "import fish_speech; print('OK')"

# Full validation
docker run --rm ghost-tts-service:latest python -c "
packages = ['fish_speech', 'torch', 'transformers', 'fastapi', 'google.cloud.storage', 'redis', 'librosa']
for pkg in packages:
    __import__(pkg)
    print(f'✓ {pkg}')
print('✓ All packages validated')
"

# Check service starts
docker compose up tts-service
# Wait 2-3 minutes for startup
curl http://localhost:8020/health
```

Expected response:
```json
{"status": "healthy", "device": "cpu", "model": "fish-speech-1.5", "voice_sample": true, "model_loaded": true, "reference_audio_present": true, "reference_tokens_present": true, "tts_engine_ready": true, "job_store": "redis", "jobs_count": 0, "max_workers": 4, "executor_active": true, "gcs_client_active": true}
```

---

## TTS Service Overview

### Technology Stack
- **Engine**: Fish Speech v1.5 (state-of-the-art zero-shot TTS)
- **Framework**: FastAPI + Uvicorn
- **Audio Processing**: librosa, soundfile, pydub, pytorch
- **Storage**: Google Cloud Storage (GCS)
- **Job Queue**: Redis for async job tracking with AOF persistence
- **Synthesis Strategy**: 
  - **CPU Mode**: Parallel chunk synthesis with ThreadPoolExecutor (configurable workers)
  - **GPU Mode**: Sequential chunk synthesis (optimal for CUDA)
- **Audio Mastering**: LUFS normalization (-23 LUFS per chunk, -16 LUFS final output)

**Key Features:**
- Zero-shot voice cloning from a single reference audio file
- Async background job processing with Redis-backed status tracking
- Automatic fallback to in-memory storage if Redis is unavailable
- Parallel synthesis on CPU (configurable worker count)
- Professional audio mastering (EBU R128 loudness normalization)
- Exponential-backoff retry on GCS uploads and n8n callbacks

---

## Component Deep Dive

### 1. n8n — The Orchestrator

**Why n8n?** Visual workflow automation that's self-hosted and open-source:

- **Native webhook triggers** — Ghost POSTs to a URL, no polling needed
- **Built-in Google Cloud Storage node** — no custom code to upload files
- **Visual workflow editor** — debug, replay, and modify without touching code
- **Execution history** — see exactly what happened for every article processed
- Runs as a Docker container (2 GB RAM limit, ~200–800 MB typical usage)
- Free, open-source, self-hosted

**How it works in this pipeline:** n8n acts as the "traffic controller." It receives the webhook from Ghost, calls your vLLM API (using an HTTP Request node), calls the TTS service, and then uploads to GCS using its built-in GCS node — all wired together visually.

**Workflows:**
1. **ghost-audio-pipeline.json**: Main synthesis workflow (Ghost webhook → vLLM → TTS → GCS)
2. **ghost-audio-callback.json**: Callback embedder workflow (TTS complete → Ghost update)
3. **static-content-audio-pipeline.json**: Static content workflow (manual webhook → vLLM → TTS → GCS, no Ghost embed)

---

### 1.5 Redis — Job Persistence Layer

**Why Redis?** Job state must survive container restarts and crashes. Without persistence, a service restart means:
- All running jobs are lost
- Clients can't check job status
- Generated MP3s become orphaned (no way to know which job created them)

**Redis solves this:**
- **Persistent job state** — All job data (queued, processing, completed, failed) survives restarts
- **Fast access** — Sub-millisecond lookups for job status
- **Automatic expiration** — Jobs auto-delete after 24 hours (configurable) to prevent storage bloat
- **Crash recovery** — Running jobs can be recovered or resubmitted after service crashes
- **Graceful fallback** — If Redis is unavailable, service falls back to in-memory storage automatically

**Configuration:**
- **AOF persistence** — Append-Only File with `fsync` every second (balance of durability and performance)
- **Volume-backed** — Data persists across container restarts via Docker volume `redis_data`
- **Connection pooling** — Async Redis client with automatic reconnection
- **TTL-based cleanup** — Jobs expire after `REDIS_JOB_TTL` seconds (default: 86400 = 24 hours)

The TTS service uses a `JobStore` abstraction layer that automatically falls back to in-memory storage if Redis is unreachable, ensuring service availability even during Redis maintenance.

---

### 2. Fish Speech v1.5 — The Voice Engine

**Why Fish Speech v1.5?** State-of-the-art open-source voice cloning:

- Clones a voice from **6–60 seconds** of reference audio (your 45s sample is ideal)
- Produces **high-fidelity, natural speech** with excellent prosody
- Supports **multiple languages** out of the box (13+ languages)
- Runs on **CPU or GPU** — optimized for L4 GPU or CPU-only deployment
- Uses **CLI-based inference** for maximum stability and compatibility

**How voice cloning works:** Fish Speech v1.5 uses a three-step inference pipeline:
1. **Reference Encoding**: DAC codec encodes your voice sample into VQ (vector-quantized) tokens representing voice characteristics
2. **Semantic Generation**: Text2Semantic model converts input text to semantic tokens using the reference as conditioning
3. **Audio Decoding**: DAC decoder synthesizes final audio from semantic tokens with your cloned voice

**Implementation approach:** CLI-based inference via subprocess calls:
1. Reference audio encoded once during initialization to VQ tokens (fake.npy)
2. Each synthesis request generates semantic tokens (codes_0.npy) from text
3. Semantic tokens decoded to high-quality audio (44.1kHz WAV)
4. All file operations handled in working directory with proper cleanup

**Performance Characteristics:**
- **Initialization**: 30-60 seconds (one-time reference encoding + transcription)
- **Synthesis Time (CPU, 4 workers)**: ~50-60 seconds per 2000-word article
- **Synthesis Time (CPU, 8 workers)**: ~30-40 seconds per 2000-word article
- **Synthesis Time (GPU)**: ~20-30 seconds per 2000-word article
- **Memory Usage**: ~1GB RAM (CPU mode with streaming), ~6GB RAM (GPU mode)
- **VRAM Usage**: 0GB (CPU mode), 2-3GB (GPU mode)
- **Thread Safety**: Single synthesis lock prevents concurrent GPU conflicts

For a typical article synthesis: ~50-60 seconds total on CPU (4 workers). Reference encoding happens once at startup.

---

### 3. Qwen3-14B via vLLM — The Script Writer

You already have this running. We simply call its **OpenAI-compatible API** (`/v1/chat/completions`) with a carefully designed prompt that instructs it to:

- Convert bullet points/lists into flowing sentences
- Remove URLs and image references
- Add verbal transitions ("Now, here's the interesting part...")
- Expand abbreviations (CEO → Chief Executive Officer on first use)
- Add an engaging opening hook and closing thought

**Why does this matter?** Articles are written to be read visually. If you feed raw article text to TTS, you get things like "Click here to read more" or "See Figure 3" being read aloud. The LLM rewrite step transforms the text into something that sounds natural as speech.

---

### 4. Ghost Content API — Article Source

Ghost has a **Content API** (read-only, public key required) and an **Admin API** (write access, private key). We use:

- **Content API**: To verify/fetch full article content
- **Admin API**: To patch the post with the audio player embed (optional step)
- **Webhooks**: To trigger the pipeline when an article is published

Ghost webhooks send a POST request to your n8n URL the moment you click "Publish." The payload contains the full post object including HTML content, slug, title, and metadata.

---

### 5. GCS — Audio Storage

Audio files are stored at a predictable path:
```
gs://YOUR_BUCKET/audio/articles/site/slug.mp3
```

Public CDN URL:
```
https://storage.googleapis.com/YOUR_BUCKET/audio/articles/site/slug.mp3
```

This URL is embedded in an `<audio>` tag injected into the Ghost post. GCS is configured with CORS headers so browsers can stream the audio directly.

---

### 6. TTS Pipeline — Audio Processing Flow

The TTS service implements a sophisticated multi-stage pipeline:

**Stage 1: Text Preparation**
- Split text into chunks at sentence boundaries (MAX_CHUNK_WORDS=200)
- Preserves context and flow between chunks

**Stage 2: Parallel/Sequential Synthesis**
- **CPU Mode**: Parallel synthesis using ThreadPoolExecutor (MAX_WORKERS=4 default)
- **GPU Mode**: Sequential synthesis (optimal for CUDA memory management)
- Each chunk synthesized independently using Fish Speech v1.5

**Stage 3: LUFS Normalization**
- Each chunk normalized to -23 LUFS (broadcast standard)
- Ensures consistent volume across all chunks
- Parallel normalization for speed

**Stage 4: Dynamic Gap Insertion**
- Analyzes chunk endings to determine appropriate pause duration
- Inserts natural-sounding gaps between sentences/paragraphs
- Prevents robotic, run-together speech

**Stage 5: Streaming Concatenation**
- For large files (>10 chunks): Uses streaming to reduce memory usage by 80%
- Progressive MP3 encoding prevents OOM errors on 5000+ word articles
- Standard concatenation for small files (faster)

**Stage 6: Final Mastering**
- Target: -16 LUFS (podcast/streaming standard)
- Resample to 44.1kHz, 128kbps MP3
- Quality validation (non-fatal, logs only)

**Stage 7: Upload & Notify**
- Upload to GCS (if configured)
- Send callback webhook to n8n
- Cleanup temporary files

---

## VRAM Budget & Resource Planning

This is the most critical concern. Here's the breakdown:

| Component | VRAM Usage | RAM Usage | Notes |
|---|---|---|---|
| Qwen3-14B (AWQ 4-bit) | ~7–8 GB | ~2 GB | Already running in your vLLM setup |
| Fish Speech v1.5 (GPU mode) | ~2–3 GB | ~6 GB | CLI-based inference with DAC + text2semantic |
| Redis | 0 GB VRAM | ~50 MB | Persistent job storage |
| n8n | 0 GB VRAM | up to 2 GB | Workflow orchestration (2 GB container limit) |
| **Total (GPU mode)** | **~10–11 GB** | **~8.3 GB** | Fits in L4 with headroom |
| Fish Speech v1.5 (CPU mode) | 0 GB VRAM | ~1 GB | **Recommended - parallel synthesis** |
| **Total (CPU mode)** | **~8 GB VRAM** | **~2.3 GB** | **vLLM on GPU, TTS on CPU - optimal** |

**Recommendation:** Set `TTS_DEVICE=cpu` and `MAX_WORKERS=4` (or match your CPU core count) in your `.env`. 

**Why CPU Mode?**
- **Resource Isolation**: TTS runs on CPU, leaving full GPU for vLLM
- **Parallel Processing**: Multiple chunks synthesized simultaneously
- **Memory Efficient**: Streaming concatenation uses ~80% less memory
- **Good Performance**: ~50-60s for 2000-word article (4 workers)

**Performance Benchmarks:**
- **CPU (4 workers)**: ~50-60 seconds for 2000-word article
- **CPU (8 workers)**: ~30-40 seconds for 2000-word article  
- **GPU mode**: ~20-30 seconds for 2000-word article (sequential only)

Since this is a **background async pipeline** (not real-time), CPU mode offers the best balance of speed, resource efficiency, and system stability.

**RAM budget:** 
- n8n: ~200MB
- Redis: ~50MB
- TTS service (CPU mode): ~1GB (with streaming optimization)
- Total new services: ~1.3GB RAM

**Configuration Variables:**
- `TTS_DEVICE=cpu` — Use CPU with parallel processing (recommended)
- `TTS_DEVICE=cuda` — Use GPU with sequential processing
- `MAX_WORKERS=4` — Thread pool size for parallel synthesis (CPU mode only)
- `REDIS_URL=redis://redis:6379/0` — Redis connection URL
- `REDIS_JOB_TTL=86400` — Job retention in seconds (24 hours)

---

## Directory Structure

```
ghost-narrator/
│
├── .env.example                   # Environment variable template
├── .gitignore
├── CHANGELOG.md
├── docker-compose.yml             # Main Docker Compose for pipeline services
├── README.md                      # Project overview
│
├── docs/
│   └── ARCHITECTURE.md            # This architecture document
│
├── n8n/
│   ├── SETUP_GUIDE.md             # n8n workflow setup guide
│   └── workflows/
│       ├── ghost-audio-callback.json          # Callback embedder workflow
│       ├── ghost-audio-pipeline.json          # Main synthesis workflow
│       └── static-content-audio-pipeline.json # Static/non-Ghost content synthesis
│
├── scripts/
│   ├── init.sh                    # Production initialization script
│   ├── setup-gcp.sh               # GCP resources setup (bucket, IAM, SA)
│   ├── validate-build.sh          # Docker image validation and smoke tests
│   ├── backfill-audio.sh          # Backfill audio for existing posts (Linux/macOS)
│   └── backfill-audio.ps1         # Backfill audio for existing posts (Windows)
│
└── tts-service/
    ├── .dockerignore
    ├── Dockerfile                 # uv-based fast build for dependency management
    ├── QUICKSTART.md              # Quick start guide
    ├── README.md                  # TTS service documentation
    ├── requirements.txt           # Python dependencies
    ├── run-docker.ps1             # Windows Docker runner
    ├── run-docker.sh              # Linux/Mac Docker runner
    │
    ├── app/                       # FastAPI application
    │   ├── __init__.py
    │   ├── main.py                # App entry point & lifespan management
    │   ├── config.py              # Configuration & environment variables
    │   ├── dependencies.py        # FastAPI dependency injection
    │   │
    │   ├── api/
    │   │   └── routes/
    │   │       ├── health.py      # Health check endpoints (/health, /health/ready)
    │   │       └── tts.py         # TTS endpoints (/generate, /status, /download)
    │   │
    │   ├── core/
    │   │   ├── exceptions.py      # Custom exceptions (SynthesisError, TTSEngineError)
    │   │   └── tts_engine.py      # Fish Speech v1.5 wrapper (singleton, thread-safe)
    │   │
    │   ├── models/
    │   │   └── schemas.py         # Pydantic request/response models
    │   │
    │   ├── services/              # Business logic layer
    │   │   ├── audio.py           # WAV concatenation, LUFS normalization, mastering
    │   │   ├── job_store.py       # Redis + in-memory job storage with fallback
    │   │   ├── notification.py    # Webhook callbacks (n8n) with retry logic
    │   │   ├── storage.py         # GCS upload service
    │   │   ├── synthesis.py       # Chunk synthesis orchestration (parallel/sequential)
    │   │   └── tts_job.py         # Complete TTS pipeline runner
    │   │
    │   └── utils/
    │       └── text.py            # Text chunking at sentence boundaries
    │
    └── voices/
        └── reference.wav          # Your voice sample (not in git)
```

---

## Step-by-Step Setup

### Step 1: Clone / Copy Files to Your VM

```bash
# On your GCP VM
mkdir -p ~/ghost-narrator
cd ~/ghost-narrator

# Copy all the files from this guide into this directory
# (or git clone if you put them in a repo)
```

### Step 2: Prepare Your Reference Voice

Your 45-second voice recording needs to be in WAV format:

```bash
# If your recording is an MP3:
sudo apt-get install -y ffmpeg
ffmpeg -i your-voice-recording.mp3 \
    -ar 22050 \        # 22050 Hz sample rate (Fish Speech v1.5 native)
    -ac 1 \            # mono channel
    -c:a pcm_s16le \   # 16-bit PCM (uncompressed WAV)
    tts-service/voices/reference.wav

# Verify it looks right
ffprobe tts-service/voices/reference.wav
# Should show: Audio: pcm_s16le, 22050 Hz, mono, s16, 352 kb/s
```

**Voice quality tips:**
- Record in a quiet room with no background noise
- Speak naturally at your normal podcast/presentation pace
- Avoid music, sound effects, or multiple speakers
- Consistent microphone placement throughout the recording

### Step 3: Create Your .env File

```bash
cp .env.example .env
nano .env
# Fill in: GCS_BUCKET_NAME, GCP_SA_KEY_PATH, N8N_HOST, N8N_PASSWORD,
#          GHOST_SITE1_URL, GHOST_KEY_SITE1, etc.
```

### Step 4: Create GCP Service Account

This can be done using the `scripts/setup-gcp.sh` script or manually.

### Step 5: Start the Services

The `scripts/init.sh` script will handle building the Docker images and starting the services.

```bash
bash scripts/init.sh
```

### Step 6: Import n8n Workflow

1. Open `http://YOUR_VM_IP:5678` in your browser
2. Login with your N8N_USER/N8N_PASSWORD
3. Go to **Workflows** → **Import from File**
4. Upload `n8n/workflows/ghost-audio-pipeline.json` and `n8n/workflows/ghost-audio-callback.json`
5. The workflows will appear with all nodes connected

### Step 7: Set Up n8n Credentials

In n8n UI → **Settings** → **Credentials**:

**Google Cloud Storage credential:**
- Type: `Google Cloud Storage OAuth2 API`
- Or use Service Account: paste your JSON key contents
- Test it by running the GCS node manually

**Note on vLLM API URL:** In the "Convert to Narration" node, the URL is `http://localhost:8001/v1/chat/completions`. If your vLLM container is named differently (e.g., `vllm`), change it to `http://vllm:8001/v1/chat/completions`. Check with `docker ps` what your vLLM container is called.

### Step 8: Set Environment Variables in n8n Workflow

In the workflow, find the **"Build GCS Path"** Code node and verify these match your `.env`:
```javascript
const gcsBucket = process.env.GCS_BUCKET_NAME || 'your-audio-bucket';
const gcsFolder = process.env.GCS_FOLDER || 'podcasts';
```

n8n containers can read from environment variables set in docker-compose.

---

## n8n Workflow — Node-by-Node Explanation

### Node 1: Ghost Webhook (Trigger)

```
Type: Webhook (Trigger)
Path: /webhook/ghost-published
Method: POST
```

This is the entry point. When you publish an article in Ghost, Ghost sends a POST request to `http://YOUR_VM_IP:5678/webhook/ghost-published`. n8n receives it and starts the workflow.

**What the payload looks like:**
```json
{
  "post": {
    "current": {
      "id": "64b7f9c8a2b3d4e5f6a7b8c9",
      "slug": "exit-strategy-how-location-affects-acquisition-value",
      "title": "Exit Strategy: How Location Affects Acquisition Value",
      "html": "<p>When founders think about exit strategy...</p>",
      "plaintext": "When founders think about exit strategy...",
      "status": "published",
      "url": "https://your-ghost-site.com/blog/exit-strategy-..."
    }
  }
}
```

---

### Node 2: Parse Ghost Payload (Code)

This JavaScript node extracts the useful fields from the webhook payload and discards the rest. Key logic:

- Uses `post.plaintext` (Ghost pre-strips HTML for us) — cleaner than parsing HTML ourselves
- Checks `post.status === 'published'` — ignores drafts and scheduled posts
- Counts words for logging/monitoring purposes

```javascript
// Simplified version of what this node does:
const post = body.post.current;
if (post.status !== 'published') return [{ json: { skip: true } }];
return [{ json: {
    post_id: post.id,
    post_slug: post.slug,
    post_title: post.title,
    post_text: post.plaintext,   // Clean text, no HTML
    post_url: post.url
}}];
```

---

### Node 3: Skip if Not Published (IF)

A simple branch node. If `skip === true`, the workflow ends silently. If false, it continues to the LLM step. This prevents the pipeline from processing draft saves or unpublished test posts.

---

### Node 4: Convert to Narration — vLLM (HTTP Request)

This is where your existing Qwen3-14B model earns its keep. The node sends a POST to your vLLM's OpenAI-compatible endpoint.

**The system prompt is carefully engineered:**
```
You are a professional podcast script writer.
Rules:
- Write in warm, conversational tone
- Expand abbreviations on first use
- Replace bullet points with flowing sentences
- Remove URLs and image captions
- Add verbal transitions
- Start with an engaging hook
- End with a brief closing thought
- Output ONLY the narration text
```

**Why "Output ONLY the narration text"?** Without this, the LLM often adds things like "Here's the narration:" or "Sure, here is the script:" at the start, which would get read aloud in the audio. We strip that with the instruction.

**Timeout is set to 300,000ms (5 min)** — Qwen3-14B can take ~30–90 seconds for a short article and up to 4–5 minutes for a long one when generating a full-length narration script.

**Configuration:** The vLLM URL is passed via environment variable `VLLM_BASE_URL` (default: `http://host.docker.internal:8001/v1`) allowing easy switching between local and remote vLLM instances.

---

### Node 5: Extract Narration Script (Code)

The vLLM response is an OpenAI-format JSON:
```json
{ "choices": [{ "message": { "content": "The narration script text..." } }] }
```
This node digs into `choices[0].message.content` and passes it forward along with the post metadata (which was in a previous node).

**Why a separate node for this?** In n8n, each HTTP Request node only outputs the raw response. You need a Code node to parse and reshape the JSON into what the next node expects.

---

### Node 6: Synthesize Audio (HTTP Request)

Calls your TTS service:
```
POST http://tts-service:8020/tts/generate
Body: { "text": "..narration script..", "job_id": "site-pid-{postId}-{slug}-{timestamp}", "site_slug": "site1-com" }
```

The TTS service returns immediately with job queued status:
```json
{
  "job_id": "site-article-slug",
  "status": "queued"
}
```

**Timeout: 1,800,000ms (30 minutes)** — This seems extreme but a 10,000-word article on CPU can genuinely take 15–20 minutes to synthesise across 100+ chunks. Since the workflow is fully async, this is fine.

**Note:** The TTS service processes audio asynchronously. The n8n workflow waits for completion by polling `/tts/status/{job_id}` or waiting for the callback webhook.

### Node 7: Log Result (Code)

Logs that the job has been successfully submitted and completes the first workflow.

---

## Workflow 2: The Callback Embedder

### Node 1: TTS Job Completed (Webhook)

Listens for `POST /webhook/tts-callback` from the TTS service.

### Node 2: Check Status & Parse Job ID (Code)

Verifies the status is `completed`, extracts the generated `gcs_uri`, converts it to a public URL, and parses the Ghost Post ID out of the job_id.

### Node 3: Should Embed Audio? (IF)

If the job failed or skipped, end here.

### Node 4: Get Latest Post Content (HTTP Request)

Fetches the original article's HTML from the Ghost Admin API to prepare for injecting the audio player.

### Node 5: Prepend Audio Player (Code)

Creates an HTML `<audio>` tag targeting the public GCS URL and prepends it to the article HTML.

### Node 6: Update Ghost Post (HTTP Request)

Uses `PUT /ghost/api/admin/posts/{id}/` to update the live article on Ghost with the newly injected audio player.

─

---

## Ghost Webhook Configuration

For **each** of your Ghost websites:

1. Go to **Ghost Admin** → **Settings** → **Integrations**
2. Click **Add custom integration**
3. Name it: `Audio Pipeline`
4. Copy the **Content API key** → save to `.env` as `GHOST_KEY_SITE1`
5. Copy the **Admin API key** → save to `.env` as `GHOST_SITE1_ADMIN_API_KEY`
6. Scroll down to **Webhooks** → **Add webhook**
   - Name: `Audio Pipeline Trigger`
   - Event: **Post published**
   - Target URL: `http://YOUR_VM_IP:5678/webhook/ghost-published`
7. Save

**For both sites using the same n8n webhook:** Both Ghost sites can POST to the same URL. The `Parse Ghost Payload` node extracts the `post_url` which contains the domain, so the `Build GCS Path` node correctly separates them into different GCS folders.

---

## Voice Clone Preparation

### Requirements
- **Format**: WAV (PCM 16-bit, 22050 Hz mono)
- **Duration**: 6–60 seconds (your 45 seconds is ideal)
- **Content**: Clear speech, your natural speaking voice
- **Quality**: No background music, no echoes, minimal room noise

### Convert Your Recording
```bash
# From MP3 to correct WAV format
ffmpeg -i your_voice.mp3 \
    -ar 22050 \
    -ac 1 \
    -c:a pcm_s16le \
    voices/reference.wav

# Verify
ffprobe -v quiet -show_entries \
    stream=codec_name,sample_rate,channels \
    -of default=noprint_wrappers=1 \
    voices/reference.wav
# Expected: codec_name=pcm_s16le, sample_rate=22050, channels=1
```

### Test Voice Cloning
Before running the full pipeline, test your voice clone:
```bash
curl -X POST http://localhost:8020/tts/generate \
    -H "Content-Type: application/json" \
    -d '{
        "text": "Hello, this is a test of the voice cloning system.",
        "job_id": "test-voice-clone"
    }'
# Returns: {"job_id": "test-voice-clone", "status": "queued"}

# Poll for completion:
curl http://localhost:8020/tts/status/test-voice-clone
# Wait until status is "completed"

# Download the audio:
curl -o test-voice.mp3 http://localhost:8020/tts/download/test-voice-clone
```

---

## GCS Bucket & IAM Setup

### Create Service Account
```bash
# Create service account
gcloud iam service-accounts create ghost-audio-pipeline \
    --display-name="Ghost Audio Pipeline"

# Grant Storage permissions
PROJECT_ID=$(gcloud config get-value project)
SA_EMAIL="ghost-audio-pipeline@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator"

# Download key
gcloud iam service-accounts keys create \
    ~/gcp-keys/ghost-audio-sa.json \
    --iam-account=$SA_EMAIL
```

### Create Bucket
```bash
# Create in northamerica-northeast2 (Toronto) — choose a region close to your users
gsutil mb -p $PROJECT_ID -l northamerica-northeast2 gs://YOUR_BUCKET_NAME/

# Make objects publicly readable
gsutil iam ch allUsers:objectViewer gs://YOUR_BUCKET_NAME/

# Set CORS for browser audio streaming
cat > /tmp/cors.json << 'EOF'
[{"origin":["*"],"method":["GET","HEAD"],"responseHeader":["Content-Type","Accept-Ranges"],"maxAgeSeconds":3600}]
EOF
gsutil cors set /tmp/cors.json gs://YOUR_BUCKET_NAME/
```

---

## Testing & Troubleshooting

### Test 1: TTS Service Health
```bash
curl http://localhost:8020/health
# Expected: {"status":"healthy","device":"cpu","model":"fish-speech-1.5","voice_sample":true,"model_loaded":true,"reference_audio_present":true,"reference_tokens_present":true,"tts_engine_ready":true,"job_store":"redis","jobs_count":0,"max_workers":4,"executor_active":true,"gcs_client_active":true}

# Readiness check (engine fully initialized):
curl http://localhost:8020/health/ready
# Expected: {"ready":true}
```

### Test 2: Manual TTS Synthesis
```bash
# Submit synthesis request
curl -X POST http://localhost:8020/tts/generate \
    -H "Content-Type: application/json" \
    -d '{"text": "Testing voice synthesis.", "job_id": "manual-test"}'

# Returns: {"job_id":"manual-test","status":"queued"}

# Poll status:
curl http://localhost:8020/tts/status/manual-test
# Wait until status is "completed"

# Download when completed:
curl -o test.mp3 http://localhost:8020/tts/download/manual-test
```

### Test 3: vLLM Connection (from n8n container)
```bash
docker exec n8n wget -qO- \
    http://host.docker.internal:8001/v1/models
# Replace with your VLLM_BASE_URL if different
```

### Test 4: End-to-End Trigger
In n8n UI, open the workflow → click **"Test Workflow"** → manually trigger the webhook node with a sample Ghost payload:
```json
{
  "post": {
    "current": {
      "id": "test123",
      "slug": "test-article",
      "title": "Test Article",
      "plaintext": "This is a test article with some content to narrate.",
      "status": "published",
      "url": "https://your-ghost-site.com/blog/test-article"
    }
  }
}
```

### Common Issues

**TTS service takes too long to start:** Fish Speech v1.5 downloads ~4GB on first run. Check logs: `docker logs tts-service`
- Normal startup time: 2-5 minutes (includes model download)
- If stuck >10 minutes: Check internet connection and disk space

**n8n can't reach vLLM:** 
- Check container names with `docker ps`
- Verify `VLLM_BASE_URL` environment variable in docker-compose.yml
- Default: `http://host.docker.internal:8001/v1` (connects to host machine)
- For Docker network: `http://vllm-container:8001/v1`

**Audio quality is poor:** 
- Check reference WAV format: `ffprobe voices/reference.wav`
- Expected: Audio: pcm_s16le, 22050 Hz, mono, s16, 352 kb/s
- Ensure 45+ seconds of clear speech with no background noise
- Reduce `MAX_CHUNK_WORDS` to 150 for better pronunciation

**GCS upload fails:** 
- Verify service account has `roles/storage.objectCreator`
- Check credentials in n8n: `docker exec n8n ls /gcp/`
- Test GCS access from container: 
  ```bash
  docker exec tts-service python -c "
  from google.cloud import storage
  client = storage.Client()
  print(list(client.list_buckets()))
  "
  ```

**TTS synthesis is slow:**
- Check if parallel synthesis is active: Look for "parallel" in logs
- Increase `MAX_WORKERS` to match CPU cores (default: 4)
- For 8-core CPU: Set `MAX_WORKERS=8`
- Consider GPU mode if available (`TTS_DEVICE=cuda`)

**Jobs lost after restart:**
- This should not happen with Redis enabled
- Verify Redis is running: `docker ps | grep redis`
- Check health endpoint: `curl localhost:8020/health`
- `job_store` should be `"redis"` not `"memory"`

**Redis connection issues:**
- Service automatically falls back to in-memory storage
- Logs will show: "WARNING: Redis connection failed"
- To fix: Ensure Redis container is running and accessible
- Check `REDIS_URL` environment variable

**Out of memory errors:**
- Reduce `MAX_CHUNK_WORDS` from 200 to 150
- Reduce `MAX_WORKERS` if using many parallel workers
- Streaming concatenation automatically activates for large files (>10 chunks)
- Monitor memory usage: `docker stats tts-service`

---

## Backfilling Audio for Existing Posts

The Ghost Narrator pipeline processes articles automatically when they are published. For posts that existed before the pipeline was set up, the `scripts/backfill-audio` scripts trigger the same n8n pipeline retroactively — working through your post archive one article at a time at a controlled pace.

### When to Use This

- You just deployed the pipeline and have a back-catalogue of published articles without audio
- The pipeline was temporarily down and a batch of posts was published without being narrated
- You want to regenerate audio for posts after a voice reference update

### Prerequisites

Before running the backfill:
1. Services are running: `docker compose ps` should show `tts-service`, `redis`, and `n8n` all healthy
2. The n8n workflow is active (toggle is green in the n8n UI)
3. You have the **Content API key** for each Ghost site (read-only — found in Ghost Admin → Settings → Integrations)
4. `curl` and `jq` are installed (Linux/macOS only): `sudo apt install curl jq`

### Running the Script

**Linux / macOS:**
```bash
cd ghost-narrator
bash scripts/backfill-audio.sh
```

**Windows (PowerShell):**
```powershell
cd ghost-narrator
.\scripts\backfill-audio.ps1
```

### Interactive Prompts

The script walks you through configuration step by step:

| Prompt | Default | Notes |
|---|---|---|
| n8n webhook URL | `http://YOUR_VM_IP:5678/webhook/ghost-published` | Your VM's public IP — change if different |
| Number of Ghost sites | `1` | Enter `2` to process both sites in one run |
| Ghost URL | *(required)* | e.g. `https://ghost.your-site.com` |
| Content API key | *(required)* | From Ghost Admin → Integrations |
| Delay between jobs (seconds) | `300` | See pacing guide below |
| Dry run? | `N` | Enter `y` to preview without triggering |

### Choosing the Right Delay

The delay prevents the TTS service from being overloaded. Tune it based on your typical article length:

| Article length | Recommended delay |
|---|---|
| ~1,000 words | 180 s (3 min) |
| ~2,000 words | 300 s (5 min) — default |
| ~4,000 words | 600 s (10 min) |

If you exceed the TTS service capacity, jobs will queue in Redis and process in order — but a shorter delay risks the service accumulating a growing backlog. When in doubt, use the default 300 s.

### What Happens During Execution

1. All published posts are fetched from the Ghost Content API (paginated, all pages)
2. Posts are split into two groups:
   - **Already has audio** (`<audio>` tag present in HTML) → skipped automatically
   - **Needs audio** → queued for narration
3. The full list of posts to be processed is shown with the estimated total time
4. After confirmation, each post is submitted to the n8n pipeline as a webhook payload matching the format Ghost itself sends on publish
5. A live countdown is shown between jobs
6. A summary of triggered / skipped / errored jobs is printed at the end

### Monitoring Progress

While the script runs, monitor the pipeline in parallel:

```bash
# n8n workflow executions
open http://YOUR_VM_IP:5678

# TTS job status
curl http://YOUR_VM_IP:8020/health

# Live TTS logs
docker logs -f tts-service

# Live n8n logs
docker logs -f n8n
```

### Resuming After Interruption

The script is safe to re-run at any time. Posts that already have an `<audio>` element embedded are automatically detected and skipped, so you will never double-process an article. If the script was interrupted mid-run, simply execute it again with the same parameters — it will pick up from where it left off.

### Dry Run

Use dry-run mode to audit which posts need audio before committing to a full backfill:

```bash
# Linux/macOS
bash scripts/backfill-audio.sh
# → Answer "y" at the dry run prompt

# PowerShell
.\scripts\backfill-audio.ps1
# → Answer "y" at the dry run prompt
```

The script will list every post that needs audio along with the estimated processing time, then exit without triggering anything.

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Compute Engine (L4 GPU) | Existing | Already paying for it |
| n8n | $0 | Open source, runs in Docker |
| Fish Speech v1.5 | $0 | Open source, runs locally |
| vLLM + Qwen3-14B | $0 | Already running |
| GCS Storage | ~$0.02/GB/month | 1000 articles × 5MB avg = 5GB = $0.10/month |
| GCS Egress | ~$0.08/GB | Pay for bandwidth when people listen |
| Redis | $0 | Open source, runs in Docker |
| **Total new monthly cost** | **~$0.10–$2.00** | Depends on traffic |

Compare to alternatives:
- ElevenLabs: ~$5–22/month, no voice persistence, limited minutes
- Google Cloud TTS: ~$4 per 1 million characters, no voice cloning
- AWS Polly: similar to GCS TTS

**Your marginal cost per article is essentially $0** — the compute is sunk cost.
