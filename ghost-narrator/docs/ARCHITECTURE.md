# Ghost Audio Pipeline — Complete Architecture & Setup Guide

> **Automated voice-narrated audio from your Ghost CMS articles, using your existing GCP stack and a cloned voice.**

---

## Table of Contents

1. [What This Pipeline Does](#what-this-pipeline-does)
2. [Architecture Overview](#architecture-overview)
3. [Build & Deployment](#build--deployment)
4. [Component Deep Dive](#component-deep-dive)
5. [VRAM Budget & Resource Planning](#vram-budget--resource-planning)
6. [Directory Structure](#directory-structure)
7. [Step-by-Step Setup](#step-by-step-setup)
8. [n8n Workflow — Node-by-Node Explanation](#n8n-workflow--node-by-node-explanation)
9. [Ghost Webhook Configuration](#ghost-webhook-configuration)
10. [Voice Clone Preparation](#voice-clone-preparation)
11. [GCS Bucket & IAM Setup](#gcs-bucket--iam-setup)
12. [Testing & Troubleshooting](#testing--troubleshooting)
13. [Cost Analysis](#cost-analysis)

---

## What This Pipeline Does

Every time you publish a post on either of your Ghost websites, this pipeline automatically:

1. **Detects** the new article via a Ghost webhook
2. **Fetches** the full article text using the Ghost Content API
3. **Rewrites** the article into podcast-style narration using your existing **Qwen-3-14b** model
4. **Synthesises** audio using **Fish Speech v1.5** with your **cloned voice** (from your 45-second sample)
5. **Uploads** the MP3 to your **GCS bucket** at a predictable path
6. **Embeds** an HTML5 audio player back into the Ghost post (optional)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     GCP Compute Engine (L4 GPU VM)                       │
│                     4 vCPUs · 16GB RAM · 16GB VRAM · 200GB SSD          │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Docker Network                             │    │
│  │                                                                   │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │    │
│  │  │   Open WebUI │  │   vLLM API   │  │   TTS Service (NEW)  │   │    │
│  │  │  (existing)  │  │  Qwen-3-14b  │  │  Fish Speech v1.5    │   │    │
│  │  │   :3000      │  │  :8001       │  │   :8020              │   │    │
│  │  │              │  │  ~8GB VRAM   │  │   ~2-3GB VRAM/CPU    │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │    │
│  │                                                                   │    │
│  │  ┌──────────────┐  ┌──────────────┐                             │    │
│  │  │    n8n (NEW) │  │  Redis (NEW) │                             │    │
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
             │  ① Ghost Webhook → n8n Pipeline (POST /webhook/ghost-published)
             │  ② n8n Pipeline → vLLM  (convert article to narration script)
             │  ③ n8n Pipeline → TTS   (synthesise MP3 with cloned voice)
             │  ④ TTS Service → GCS   (upload MP3)
             │  ⑤ TTS Service → n8n Callback (POST /webhook/tts-callback)
             │  ⑥ n8n Callback → Ghost (embed audio player in post via Admin API)
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         External Services                                 │
│                                                                           │
│  ┌──────────────────────┐       ┌──────────────────────┐                │
│  │  Ghost CMS Site 1    │       │  Ghost CMS Site 2    │                │
│  │  │  founderreality.com  │       │  your-second-site.com│                │
│  │  │  (sends webhooks)    │       │  (sends webhooks)    │                │
│  └──────────────────────┘       └──────────────────────┘                │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  Google Cloud Storage                                          │       │
│  │  gs://ghost-narrator/audio/articles/YYYY/MM/DD/slug.mp3      │       │
│  └──────────────────────────────────────────────────────────────┘       │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Build & Deployment

### TTS Service Build Architecture

The TTS service uses a **20-stage Dockerfile** to prevent dependency resolution errors. This approach was specifically designed to solve the `resolution-too-deep` error that occurs when pip tries to resolve 50+ packages with complex version constraints simultaneously.

**Build Strategy:**
- Each stage installs 3-10 compatible packages in dependency order
- Packages are grouped by their dependency relationships
- Each stage verifies installation and cleans up temporary files
- Total build time: 15-25 minutes (first build), 1-3 minutes (cached)

**Stage Breakdown:**
1. **Stages 1-2**: Build tools, numpy, scipy (foundation)
2. **Stages 3-4**: PyTorch ecosystem, Lightning framework
3. **Stages 5-6**: Transformers, Gradio (pinned to avoid backtracking)
4. **Stages 7-9**: Audio processing (librosa, soundfile), FastAPI
5. **Stages 10-19**: Supporting libraries (GCS, Redis, Hydra, speech tools)
6. **Stage 20**: Fish Speech v1.5 (uses all pre-installed dependencies)

### Resource Requirements

**Minimum for Build:**
- **RAM**: 8GB allocated to Docker Desktop
- **Disk Space**: 20GB free (includes base images, layers, models)
- **Network**: Stable connection (~7GB download for models + packages)
- **Time**: 15-25 minutes first build, model download can add 5-10 minutes

**Runtime Resources (per docker-compose.yml):**
- **CPU Mode**: 4GB RAM, 4 CPU cores
- **GPU Mode**: 6GB RAM, 1 GPU with 2-3GB VRAM

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

### Common Build Issues & Solutions

#### 1. Dependency Resolution Error
```
error: resolution-too-deep
× Dependency resolution exceeded maximum depth
```

**Solution:** Already fixed in Dockerfile. If you still see this:
- Use `--no-cache` flag: `docker compose build --no-cache tts-service`
- Ensure you're using the latest Dockerfile (20-stage build)
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
{"status": "healthy", "service": "tts-service", "version": "1.0.0"}
```

---

## Component Deep Dive

### TTS Service (Fish Speech v1.5)

**Technology Stack:**
- **Engine**: Fish Speech v1.5 (state-of-the-art zero-shot TTS)
- **Framework**: FastAPI + Uvicorn
- **Audio Processing**: librosa, soundfile, pydub
- **Storage**: Google Cloud Storage (GCS)
- **Job Queue**: Redis for async job tracking

**Key Features:**
│  └──────────────────────┘       └──────────────────────┘                │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  Google Cloud Storage Bucket                                  │       │
│  │  gs://your-audio-bucket/podcasts/{site}/{year}/{month}/{slug}.mp3    │
│  │  Public CDN URL: https://storage.googleapis.com/...           │       │
│  └──────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component Deep Dive

### 1. n8n — The Orchestrator (NEW)

**Why n8n?** You asked about it, and yes — it's the right choice here. Here's why:

- It has **native webhook triggers** — Ghost just POSTs to a URL, no polling needed
- It has a **built-in Google Cloud Storage node** — no custom code to upload files
- **Visual workflow editor** — you can debug, replay, and modify the pipeline without touching code
- **Execution history** — see exactly what happened for every article processed
- Runs as a lightweight Docker container (~200MB RAM)
- Free, open-source, self-hosted

**How it works in this pipeline:** n8n acts as the "traffic controller." It receives the webhook from Ghost, calls your vLLM API (using an HTTP Request node), calls the TTS service, and then uploads to GCS using its built-in GCS node — all wired together visually.

---

### 1.5 Redis — Job Persistence Layer (NEW)

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

**Job lifecycle in Redis:**
```
job:article-slug-123 → {
  "status": "processing",
  "started_at": 1704067200,
  "gcs_uri": null,
  "local_path": "/app/output/article-slug-123.mp3",
  "created_at": 1704067100
}
```

The TTS service uses a `JobStore` abstraction layer that automatically falls back to in-memory storage if Redis is unreachable, ensuring service availability even during Redis maintenance.

---

### 2. Fish Speech v1.5 — The Voice Engine

**Why Fish Speech v1.5?** It's a state-of-the-art open-source voice cloning model:

- Clones a voice from **6–60 seconds** of reference audio (your 45s sample is ideal)
- Produces **high-fidelity, natural speech** with excellent prosody
- Supports **multiple languages** out of the box (13+ languages)
- Runs on **CPU or GPU** — optimized for L4 GPU or CPU-only deployment
- Uses **CLI-based inference** for maximum stability and compatibility

**How voice cloning works:** Fish Speech v1.5 uses a three-step inference pipeline:
1. **Reference Encoding**: DAC codec encodes your voice sample into VQ (vector-quantized) tokens representing voice characteristics
2. **Semantic Generation**: Text2Semantic model converts input text to semantic tokens using the reference as conditioning
3. **Audio Decoding**: DAC decoder synthesizes final audio from semantic tokens with your cloned voice

**Implementation approach:** Fish Speech v1.5 uses CLI-based inference via subprocess calls:
1. Reference audio encoded once during initialization to VQ tokens (fake.npy)
2. Each synthesis request generates semantic tokens (codes_0.npy) from text
3. Semantic tokens decoded to high-quality audio (44.1kHz WAV)
4. All file operations handled in working directory with proper cleanup

**Performance Characteristics:**
- **Initialization**: 30-60 seconds (one-time reference encoding + transcription)
- **Synthesis Time**: 10-30 seconds per request (device-dependent)
- **Memory Usage**: 4-6GB RAM (GPU mode), 8-16GB RAM (CPU mode)
- **VRAM Usage**: 2-3GB when using GPU acceleration
- **Thread Safety**: Single synthesis lock prevents concurrent GPU conflicts

For a typical article synthesis: ~10-30 seconds total. Reference encoding happens once at startup.

---

### 3. Qwen-3-14b via vLLM — The Script Writer (EXISTING)

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
gs://YOUR_BUCKET/audio/articles/site/exit-strategy-article.mp3
```

Public CDN URL:
```
https://storage.googleapis.com/YOUR_BUCKET/audio/articles/site/exit-strategy-article.mp3
```

This URL is embedded in an `<audio>` tag injected into the Ghost post. GCS is configured with CORS headers so browsers can stream the audio directly.

### 6. Redis — Persistent Job Storage

Redis stores all TTS job state with the following guarantees:
- **Durability**: AOF persistence with fsync every second
- **Availability**: Automatic reconnection and fallback to memory
- **Cleanup**: Automatic expiration after 24 hours
- **Performance**: Sub-millisecond job status lookups

---

## VRAM Budget & Resource Planning

This is the most critical concern. Here's the breakdown:

| Component | VRAM Usage | RAM Usage | Notes |
|---|---|---|---|
| Qwen-3-14b (AWQ 4-bit) | ~7–8 GB | ~2 GB | Already running in your vLLM setup |
| Fish Speech v1.5 (GPU mode) | ~2–3 GB | ~4-6 GB | CLI-based inference with DAC + text2semantic |
| Redis | 0 GB VRAM | ~50 MB | Persistent job storage |
| n8n | 0 GB VRAM | ~200 MB | Workflow orchestration |
| **Total (GPU mode)** | **~10–11 GB** | **~6.3 GB** | Fits in L4 with 5GB headroom |
| Fish Speech v1.5 (CPU mode) | 0 GB VRAM | ~8-16 GB | **Recommended for resource isolation** |
| **Total (CPU mode)** | **~8 GB VRAM** | **~10.3 GB** | **vLLM on GPU, TTS on CPU - optimal** |
</text>


**Recommendation:** Set `DEVICE=cpu` and `MAX_WORKERS=4` (or match your CPU core count) in your `.env`. 

**Performance with new optimizations:**
- **CPU (4 workers)**: ~50-60 seconds for 2000-word article (vs ~3-5 minutes sequential)
- **CPU (8 workers)**: ~30-40 seconds for 2000-word article
- **GPU mode**: ~20-30 seconds for 2000-word article (sequential only)

Since this is a **background async pipeline** (not real-time), CPU parallel mode offers the best balance of speed and resource efficiency.

**RAM budget:** Your machine has 16GB RAM with ~10GB free (buff/cache). With optimizations:
- n8n: ~200MB
- Redis: ~50MB
- TTS service (CPU parallel): ~800MB-1.2GB (reduced from ~5GB)
- Streaming concatenation prevents OOM on large articles (5000+ words)

**New Configuration Variables:**
- `MAX_WORKERS=4` — Thread pool size for parallel synthesis (CPU mode only)
- `DEVICE=cpu` — Use CPU with parallel processing (recommended)
- `DEVICE=cuda` — Use GPU with sequential processing
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
├── docker-compose.yml             # Main Docker Compose file for all services
├── README.md
│
├── docs/
│   └── ARCHITECTURE.md            # This file
│
├── n8n/
│   ├── SETUP_GUIDE.md             # Guide to setting up the n8n workflows
│   └── workflows/
│       ├── ghost-audio-callback.json
│       └── ghost-audio-pipeline.json
│
├── scripts/
│   ├── init.sh                    # Initializes and starts the services
│   ├── setup-gcp.sh               # Sets up GCP resources
│   └── validate-build.sh          # Validates the Docker build
│
├── tts-service/
│   ├── .dockerignore
│   ├── Dockerfile                 # Multi-stage Dockerfile for the TTS service
│   ├── QUICKSTART.md
│   ├── README.md
│   ├── requirements.txt           # Python dependencies
│   ├── run-docker.ps1             # PowerShell script to run the service
│   ├── run-docker.sh              # Shell script to run the service
│   │
│   ├── app/                       # Main application folder
│   │   ├── __init__.py
│   │   ├── config.py              # Configuration loading
│   │   ├── dependencies.py        # FastAPI dependencies
│   │   ├── main.py                # FastAPI app entry point
│   │   │
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── health.py      # Health check endpoint
│   │   │       └── tts.py         # TTS generation endpoint
│   │   │
│   │   ├── core/
│   │   │   ├── exceptions.py      # Custom exceptions
│   │   │   └── tts_engine.py      # Core TTS logic
│   │   │
│   │   ├── models/
│   │   │   └── schemas.py         # Pydantic schemas
│   │   │
│   │   ├── services/              # Business logic services
│   │   │   ├── audio.py
│   │   │   ├── job_store.py
│   │   │   ├── notification.py
│   │   │   ├── storage.py
│   │   │   ├── synthesis.py
│   │   │   └── tts_job.py
│   │   │
│   │   └── utils/
│   │       └── text.py
│   │
│   └── voices/
│       └── .gitkeep               # Placeholder for voice samples
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
#          GHOST_SITE1_URL, GHOST_SITE1_CONTENT_API_KEY, etc.
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
Path: /webhook/ghost-article
Method: POST
```

This is the entry point. When you publish an article in Ghost, Ghost sends a POST request to `http://YOUR_VM_IP:5678/webhook/ghost-article`. n8n receives it and starts the workflow.

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
      "url": "https://founderreality.com/blog/exit-strategy-..."
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

This is where your existing Qwen-3-14b model earns its keep. The node sends a POST to your vLLM's OpenAI-compatible endpoint.

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

**Timeout is set to 120,000ms (2 min)** — Qwen-3-14b can take ~30–90 seconds for a long article rewrite.

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
Body: { "text": "..narration script..", "job_id": "site-slug", "site_slug": "site" }
```

The TTS service returns:
```json
{
  "job_id": "site-article-slug",
  "status": "queued"
}
```

The job runs asynchronously. Poll `/tts/status/{job_id}` until status is `completed`.

**Timeout: 1,800,000ms (30 minutes)** — This seems extreme but a 10,000-word article on CPU can genuinely take 15–20 minutes to synthesise across 100+ chunks. Since the workflow is fully async, this is fine.

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

For **each** of your 2 Ghost websites:

1. Go to **Ghost Admin** → **Settings** → **Integrations**
2. Click **Add custom integration**
3. Name it: `Audio Pipeline`
4. Copy the **Content API key** → save to `.env` as `GHOST_SITE1_CONTENT_API_KEY`
5. Copy the **Admin API key** → save to `.env` as `GHOST_SITE1_ADMIN_API_KEY`
6. Scroll down to **Webhooks** → **Add webhook**
   - Name: `Audio Pipeline Trigger`
   - Event: **Post published**
   - Target URL: `http://YOUR_VM_IP:5678/webhook/ghost-article`
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
import sys, json
data = json.load(sys.stdin)
print('File ready at:', data['download_url'])
print('Duration:', data['duration_estimate_seconds'], 'seconds')
"
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
# Create in asia-south1 (Mumbai — close to India, low latency)
gsutil mb -p $PROJECT_ID -l asia-south1 gs://YOUR_BUCKET_NAME/

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
# Expected: {"status":"healthy","device":"cpu","model":"fish-speech-1.5","voice_sample":true,"model_loaded":true,...}

# Readiness check:
curl http://localhost:8020/health/ready
# Expected: {"ready":true}
```

### Test 2: Manual TTS Synthesis
```bash
curl -X POST http://localhost:8020/tts/generate \
    -H "Content-Type: application/json" \
    -d '{"text": "Testing voice synthesis.", "job_id": "manual-test"}'

# Then poll status:
curl http://localhost:8020/tts/status/manual-test

# And download when completed:
curl -o test.mp3 http://localhost:8020/tts/download/manual-test
```

### Test 3: vLLM Connection (from n8n container)
```bash
docker exec n8n wget -qO- \
    http://vllm:8001/v1/models     # Replace 'vllm' with your container name
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
      "url": "https://founderreality.com/blog/test-article"
    }
  }
}
```

### Common Issues

**TTS service takes too long to start:** Fish Speech v1.5 downloads ~7GB on first run. Check logs: `docker logs tts-service`

**n8n can't reach vLLM:** Check container names with `docker ps`. Both must be on the same Docker network. Update the vLLM URL in the "Convert to Narration" node to use the container name instead of `localhost`.

**Audio quality is poor:** Check your reference WAV format. Run `ffprobe voices/reference.wav` — sample rate should be 22050 Hz, codec pcm_s16le.

**GCS upload fails:** Verify service account has `roles/storage.objectCreator`. Check GCP_SA_KEY_PATH in n8n container: `docker exec n8n ls /gcp/`

---

## Cost Analysis

| Component | Cost | Notes |
|---|---|---|
| Compute Engine (L4 GPU) | Existing | Already paying for it |
| n8n | $0 | Open source, runs in Docker |
| Fish Speech v1.5 | $0 | Open source, runs locally |
| vLLM + Qwen-3-14b | $0 | Already running |
| GCS Storage | ~$0.02/GB/month | 1000 articles × 5MB avg = 5GB = $0.10/month |
| GCS Egress | ~$0.08/GB | Pay for bandwidth when people listen |
| Redis | $0 | Open source, runs in Docker |
| **Total new monthly cost** | **~$0.10–$2.00** | Depends on traffic |

Compare to alternatives:
- ElevenLabs: ~$5–22/month, no voice persistence, limited minutes
- Google Cloud TTS: ~$4 per 1 million characters, no voice cloning
- AWS Polly: similar to GCS TTS

**Your marginal cost per article is essentially $0** — the compute is sunk cost.
