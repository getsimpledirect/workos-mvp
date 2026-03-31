# TTS Service — Studio-Quality Narration API

A FastAPI service wrapping **Fish Speech v1.5** for high-fidelity voice cloning and professional narration.

## ⚠️ Python Version Compatibility

**IMPORTANT**: This service requires Python 3.9-3.11 due to TTS library constraints.

If you have Python 3.12+ on your host system, **DO NOT install dependencies locally**.
Instead, use Docker (recommended) which handles the correct Python version automatically.

## 🏗️ Build Information

**First build time**: 2-5 minutes (downloads ~4GB of models)  
**Cached rebuild**: 1-3 minutes  
**Docker resources required**: 8GB RAM, 20GB disk space

**Runtime Resources:**
- **CPU Mode (Default)**: ~1GB RAM, configurable parallel workers
- **GPU Mode**: ~3GB VRAM + ~6GB RAM

The Dockerfile uses **uv** (by Astral) for blazingly fast and deterministic dependency resolution, completely replacing legacy pip installations.

## Quick Start (Docker - Recommended)

### Option 1: Run with Docker Compose (Easiest)

```bash
# From the ghost-narrator directory
cd ghost-narrator
docker-compose up tts-service --build
```

The service will be available at `http://localhost:8020`

### Option 2: Run Standalone Docker Container

```bash
# Build the image
cd ghost-narrator/tts-service
docker build -t ghost-tts-service:latest .

# Run the container
docker run -d \
  --name tts-service \
  -p 8020:8020 \
  -v $(pwd)/voices:/app/voices:ro \
  -v tts_output:/app/output \
  -v tts_model_cache:/root/.local/share/tts \
  -e VOICE_SAMPLE_PATH=/app/voices/reference.wav \
  -e TTS_LANGUAGE=en \
  -e MAX_CHUNK_WORDS=200 \
  -e DEVICE=cpu \
  ghost-tts-service:latest
```

## 🔧 Build Troubleshooting

### Common Build Errors

#### 1. Dependency Resolution Error

**Symptom:**
```
error: resolution-too-deep
× Dependency resolution exceeded maximum depth
```

**Cause:** Pip cannot resolve the complex dependency graph when installing 50+ packages simultaneously.

**Solution:** This is already fixed by using uv in the latest Dockerfile. If you still see this:
- Ensure you're building with `--no-cache` flag
- Check you're using the latest Dockerfile
- Verify Docker has 8GB+ RAM allocated

#### 2. Out of Memory During Build

**Symptom:**
```
Killed
The command '/bin/sh -c pip install...' returned a non-zero code: 137
```

**Solution:**
1. Increase Docker Desktop memory allocation:
   - **Windows/Mac**: Docker Desktop → Settings → Resources → Memory → 8GB+
   - **Linux**: Edit `/etc/docker/daemon.json` and add `"default-runtime": "runc"`
2. Close other applications during build
3. If problem persists, build on a machine with more RAM

#### 3. Disk Space Error

**Symptom:**
```
no space left on device
write /var/lib/docker: no space left on device
```

**Solution:**
1. Clean Docker system:
   ```bash
   docker system prune -a --volumes
   ```
2. Ensure at least 20GB free disk space
3. Check Docker Desktop disk image size limit (Settings → Resources → Disk)

#### 4. Network Timeout

**Symptom:**
```
Could not fetch URL
ReadTimeoutError: HTTPSConnectionPool
```

**Solution:**
1. Check internet connection
2. Retry the build (timeout settings are already configured in Dockerfile)
3. If in restricted network, configure pip mirror in Dockerfile:
   ```dockerfile
   ENV PIP_INDEX_URL=https://pypi.org/simple
   ```

#### 5. fish-speech Installation Fails

**Symptom:**
```
ERROR: Could not find a version that satisfies the requirement fish-speech
fatal: unable to access 'https://github.com/fishaudio/fish-speech.git/'
```

**Solution:**
1. Verify GitHub access: `git ls-remote https://github.com/fishaudio/fish-speech.git`
2. Check all previous build stages completed successfully
3. If GitHub is blocked, use a specific commit hash instead of tag in Dockerfile

#### 6. Model Download Fails

**Symptom:**
```
Warning: Could not download Fish Speech model
```

**Solution:**
This is a warning, not an error. Models will download on first API call. To pre-download during build:
1. Ensure stable internet connection during build
2. The build continues successfully even if model download fails
3. Models download automatically on container startup

### Manual Build (Detailed Output)

To see detailed build output for debugging:

```bash
cd tts-service
docker build --progress=plain --no-cache -t ghost-tts-service:latest .
```

### Build Architecture

The Dockerfile uses **uv** to provide a fast and deterministic build process:

1. **System Dependencies**: Installs ffmpeg and build essentials.
2. **uv Package Manager**: Installs uv for blazingly fast dependency resolution.
3. **Requirement Resolution**: Resolves and installs all PyTorch and ML packages from `requirements.txt`.
4. **Model Pre-download**: Downloads Fish Speech and Whisper weights during build (optional).
5. **Validation**: Verifies critical imports (torch, transformers, fastapi) work correctly.

This approach ensures builds are reliable, predictable, and complete in a fraction of the time compared to standard pip.

## Local Development (Only if you have Python 3.11)

If you specifically have Python 3.11 installed and want to run locally:

```bash
# Create virtual environment with Python 3.11
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies using uv
uv pip install -r requirements.txt

# Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

### Environment Variables (Local Development)

Create a `.env` file:

```env
VOICE_SAMPLE_PATH=./voices/reference.wav
TTS_LANGUAGE=en
MAX_CHUNK_WORDS=200
DEVICE=cpu
GCS_BUCKET_NAME=your-bucket-name
GCS_AUDIO_PREFIX=audio/articles
N8N_CALLBACK_URL=http://localhost:5678/webhook/tts-callback
```

## Architecture

### How It Works

1. **POST /tts/generate** - Submit text for TTS generation
2. Background processing:
   - Automatically transcribes reference audio if needed (Whisper tiny)
   - Generates semantic tokens using Fish Speech LLaMA model
   - Decodes high-fidelity audio using Firefly VQ-GAN
   - Concatenates chunks into single MP3 file
   - Uploads to Google Cloud Storage
   - Notifies n8n via callback webhook
3. **GET /tts/status/{job_id}** - Poll job status
4. **GET /tts/download/{job_id}** - Download generated audio

### Key Features

- **Studio-quality voice cloning**: Zero-shot cloning with expressive prosody
- **Expressive Narration**: Captures natural breathing and human-like emphasis
- **Automatic chunking**: Handles long texts by splitting at sentence boundaries
- **GPU acceleration**: Optional CUDA support for faster generation
- **Cloud storage**: Automatic upload to Google Cloud Storage
- **Async processing**: Non-blocking background jobs with status polling

## API Endpoints

### Generate Audio

```bash
POST /tts/generate
Content-Type: application/json

{
  "text": "Your long article text here...",
  "job_id": "optional-custom-id",
  "article_slug": "my-article",
  "callback_url": "https://your-webhook.com/callback"
}
```

### Check Status

```bash
GET /tts/status/{job_id}

Response:
{
  "job_id": "abc123",
  "status": "processing|completed|failed",
  "gcs_uri": "gs://bucket/audio/articles/abc123.mp3",
  "error": null
}
```

### Download Audio

```bash
GET /tts/download/{job_id}

Returns: MP3 file (audio/mpeg)
```

### Health Check

```bash
GET /health

Response:
{
  "status": "healthy",
  "device": "cpu",
  "model": "fish-speech-1.5",
  "voice_sample": true,
  "model_loaded": true,
  "reference_audio_present": true,
  "reference_tokens_present": true,
  "tts_engine_ready": true,
  "job_store": "redis",
  "jobs_count": 0,
  "max_workers": 4,
  "executor_active": true,
  "gcs_client_active": true
}
```

### Additional Health Endpoints

```bash
GET /health/ready    # Kubernetes readiness probe — returns {"ready": true} when engine is fully initialized
GET /health/live     # Kubernetes liveness probe — returns {"alive": true} if service is responsive
GET /health/detailed # Component-level breakdown for debugging
```

### Job Management

```bash
POST /tts/pause/{job_id}    # Pause an active job
POST /tts/resume/{job_id}   # Resume a paused job
DELETE /tts/{job_id}        # Delete a job and clean up its files
GET /tts/jobs               # List all jobs
```

## Voice Sample Requirements

Place your reference voice WAV file in `./voices/reference.wav`:

- **Duration**: 45-60 seconds (minimum 6 seconds, optimal 45+)
- **Format**: WAV, 22.05 kHz, mono, 16-bit PCM
- **Quality**: Clear speech, no background noise
- **Content**: Natural speaking, varied intonation
- **Language**: Must match `TTS_LANGUAGE` setting

### Creating a Good Voice Sample

```bash
# Convert any audio to proper format with ffmpeg
ffmpeg -i input.mp3 -ar 22050 -ac 1 -c:a pcm_s16le voices/reference.wav

# Trim to 45 seconds starting at 10 seconds
ffmpeg -i input.wav -ss 10 -t 45 -ar 22050 -ac 1 -c:a pcm_s16le voices/reference.wav

# Verify format
ffprobe -v quiet -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 voices/reference.wav
# Expected: codec_name=pcm_s16le, sample_rate=22050, channels=1
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE_SAMPLE_PATH` | `/app/voices/reference.wav` | Path to reference voice WAV |
| `TTS_LANGUAGE` | `en` | BCP-47 language code |
| `MAX_CHUNK_WORDS` | `200` | Max words per synthesis chunk |
| `DEVICE` | `cpu` | PyTorch device: `cpu` or `cuda` |
| `MAX_WORKERS` | `4` | Thread pool size for parallel synthesis (CPU mode) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL for job persistence |
| `REDIS_JOB_TTL` | `86400` | Job retention time in seconds (24 hours) |
| `GCS_BUCKET_NAME` | - | Google Cloud Storage bucket name |
| `GCS_AUDIO_PREFIX` | `audio/articles` | GCS path prefix for uploads |
| `N8N_CALLBACK_URL` | - | Webhook URL for job completion |

### Performance Tuning

#### CPU Mode (Default)
- Safe for all systems
- **Parallel Processing**: Synthesizes multiple chunks simultaneously
- Generation time: 
  - Sequential (1 worker): ~3-5 minutes per 2000-word article
  - Parallel (4 workers): ~50-60 seconds per 2000-word article
  - Parallel (8 workers): ~30-40 seconds per 2000-word article
- Memory: ~800 MB - 1.2 GB RAM (optimized with streaming concatenation)
- Recommended for: Most deployments, shared GPU systems

**Optimize CPU Performance:**
```bash
# Quad-core CPU
MAX_WORKERS=4

# Octa-core CPU
MAX_WORKERS=8

# High-core-count server (16+ cores)
MAX_WORKERS=16
```

#### GPU Mode (CUDA)
- Requires NVIDIA GPU with 4+ GB VRAM
- Generation time: ~20-40 seconds per 2000-word article
- Memory: ~3 GB VRAM + 6 GB RAM
- **VRAM Harmony**: Works alongside vLLM. Optimized for NVIDIA L4 (24GB).
- **GPU Rebalancing**: If using vLLM, ensure `gpu_memory_utilization` is set to `0.7` to provide headroom for the Studio TTS models.

```yaml
# In docker-compose.override.yml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

## Redis Job Persistence

**NEW: Jobs are now persisted to Redis by default!**

### Why Redis?

- **No data loss**: Jobs survive container restarts
- **Persistent state**: Running jobs can be recovered after crashes
- **Scalability**: Ready for horizontal scaling (future)
- **Automatic fallback**: If Redis is unavailable, falls back to in-memory storage

### How It Works

1. All job state (queued, processing, completed, failed) is stored in Redis
2. Jobs are kept for 24 hours by default (configurable with `REDIS_JOB_TTL`)
3. If Redis connection fails, service automatically uses in-memory storage
4. Redis uses AOF (Append-Only File) persistence with `fsync` every second

### Configuration

```yaml
# In docker-compose.override.yml (already configured)
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --appendfsync everysec
    volumes:
      - redis_data:/data

  tts-service:
    environment:
      - REDIS_URL=redis://redis:6379/0
      - REDIS_JOB_TTL=86400  # 24 hours
```

### Recovery After Restart

When the TTS service restarts:
1. Existing jobs in Redis are immediately available
2. Jobs in "processing" state can be manually recovered or resubmitted
3. Completed jobs can still be downloaded (if MP3 file still exists)
4. Failed jobs are preserved for debugging

### Monitoring

The `/health` endpoint shows storage status:

```json
{
  "status": "healthy",
  "device": "cpu",
  "model": "fish-speech-1.5",
  "voice_sample": true,
  "model_loaded": true,
  "reference_audio_present": true,
  "reference_tokens_present": true,
  "tts_engine_ready": true,
  "job_store": "redis",
  "jobs_count": 5,
  "max_workers": 4,
  "executor_active": true,
  "gcs_client_active": true
}
```

- `job_store`: `"redis"` (persistent) or `"memory"` (ephemeral)
- `jobs_count`: Total jobs in storage

## Performance Optimizations

The service includes several performance enhancements:

### 1. Parallel Chunk Synthesis (CPU Mode)
- Multiple chunks processed simultaneously using ThreadPoolExecutor
- Up to **4x faster** on CPU with default 4 workers
- Automatically enabled for CPU mode with multiple chunks
- Configure with `MAX_WORKERS` environment variable

### 2. Resource Reuse
- **GCS Client**: Single reusable instance (~200-500ms saved per upload)
- **HTTP Client**: Connection pooling with keepalive (~50-100ms saved per callback)
- Initialized at startup, shared across all requests

### 3. Streaming Concatenation
- Automatic for large files (>10 chunks)
- **Up to 80% memory reduction** for long articles
- Prevents OOM errors on 5000+ word articles
- Progressive MP3 encoding reduces peak memory

### 4. Smart Processing Strategy
- CPU mode + multiple chunks → Parallel synthesis
- GPU mode → Sequential processing (optimal for CUDA)
- Large files → Streaming concatenation
- Small files → Standard concatenation (faster)

### Performance Benchmarks

**Typical 2000-word Article:**

| Configuration | Time | Improvement |
|--------------|------|-------------|
| CPU (1 worker) | 180s | Baseline |
| CPU (4 workers) | 50s | **72% faster** |
| CPU (8 workers) | 30s | **83% faster** |
| CUDA | 23s | 87% faster |

**Memory Usage:**

| Scenario | Memory | Notes |
|----------|--------|-------|
| 2000 words | 800 MB | Standard |
| 5000 words | 1.1 GB | Streaming enabled |
| 10000 words | 1.8 GB | Previously OOM |

### Monitoring

The `/health` endpoint includes performance metrics:

```json
{
  "status": "healthy",
  "device": "cpu",
  "model": "fish-speech-1.5",
  "voice_sample": true,
  "model_loaded": true,
  "job_store": "redis",
  "jobs_count": 3,
  "max_workers": 4
}
```

- `job_store`: Storage backend (`"redis"` or `"memory"`)
- `jobs_count`: Number of jobs in storage

## Troubleshooting

### "Could not find a version that satisfies the requirement TTS>=0.22.0"

This means you're trying to install on Python 3.12+. Solution:
- ✅ Use Docker (recommended)
- ✅ Use Python 3.11 virtual environment
- ❌ Do NOT downgrade system Python

### Model download fails

First run downloads ~4 GB of Fish Speech v1.5 weights. If it fails:

```bash
# Pre-download inside container
docker exec -it tts-service python -m tools.vqgan.inference --help
```

### Out of memory errors

If CPU crashes with OOM:
- Reduce `MAX_CHUNK_WORDS` to 150
- Increase system swap space
- Use GPU mode if available

### Poor audio quality

- Ensure reference WAV is high quality (no noise, 22 kHz)
- Use 45+ seconds of reference audio (minimum 6 seconds)
- Reduce `MAX_CHUNK_WORDS` for better pronunciation
- Ensure language matches reference voice

### High memory usage

- Reduce `MAX_CHUNK_WORDS` from 200 to 150
- Lower `MAX_WORKERS` to reduce concurrent processing
- Streaming concatenation automatically activates for large files

### Slow processing on CPU

- Increase `MAX_WORKERS` to match your CPU core count
- Check logs to verify parallel synthesis is active
- Consider GPU mode if available

### Jobs lost after restart

This should no longer happen with Redis enabled. If it does:

- Check Redis is running: `docker ps | grep redis`
- Check Redis connection in logs: `docker logs tts-service | grep Redis`
- Verify Redis volume: `docker volume ls | grep redis_data`
- Check health endpoint for `job_store` value (should be `"redis"`)

### Redis connection issues

If Redis fails, the service automatically falls back to in-memory storage:

```
WARNING: Redis connection failed: Connection refused. Using in-memory storage
```

To fix:
1. Ensure Redis container is running
2. Check `REDIS_URL` environment variable
3. Verify network connectivity between containers

### GCS upload fails

Check authentication:

```bash
# Inside container, verify service account
docker exec -it tts-service gcloud auth list

# Test GCS access
docker exec -it tts-service python -c "
from google.cloud import storage
client = storage.Client()
buckets = list(client.list_buckets())
print(f'Found {len(buckets)} buckets')
"
```

## Development

### Project Structure

```
tts-service/
├── app/                        # Application package
│   ├── __init__.py            # Package initialization
│   ├── main.py                # FastAPI application entry point
│   ├── config.py              # Configuration and environment variables
│   ├── dependencies.py        # FastAPI dependency injection
│   │
│   ├── api/                   # API layer
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── tts.py         # TTS endpoints (generate, status, download)
│   │       └── health.py      # Health check endpoints
│   │
│   ├── core/                  # Core functionality
│   │   ├── __init__.py
│   │   ├── exceptions.py      # Custom exception classes
│   │   └── tts_engine.py      # Fish Speech v1.5 engine wrapper
│   │
│   ├── models/                # Pydantic schemas
│   │   ├── __init__.py
│   │   └── schemas.py         # Request/response models
│   │
│   ├── services/              # Business logic services
│   │   ├── __init__.py
│   │   ├── audio.py           # Audio concatenation and processing
│   │   ├── job_store.py       # Redis/in-memory job storage
│   │   ├── notification.py    # Webhook notifications (n8n)
│   │   ├── storage.py         # GCS upload service
│   │   ├── synthesis.py       # TTS synthesis orchestration
│   │   └── tts_job.py         # Background job runner
│   │
│   └── utils/                 # Utility functions
│       ├── __init__.py
│       └── text.py            # Text chunking utilities
│
├── voices/                    # Voice samples directory
│   └── reference.wav          # Your voice sample (not in git)
│
├── Dockerfile                 # Container image definition
├── requirements.txt           # Python dependencies
├── run-docker.ps1             # Windows Docker runner script
├── run-docker.sh              # Linux/macOS Docker runner script
├── QUICKSTART.md              # Quick start guide
└── README.md                  # This file
```

### Module Responsibilities

| Module | Description |
|--------|-------------|
| `app/main.py` | FastAPI app initialization, lifecycle management |
| `app/config.py` | Centralized configuration from environment variables |
| `app/core/tts_engine.py` | Thread-safe Fish Speech v1.5 wrapper with singleton pattern |
| `app/core/exceptions.py` | Domain-specific exception hierarchy |
| `app/services/job_store.py` | Job persistence with Redis + in-memory fallback |
| `app/services/synthesis.py` | Parallel/sequential chunk synthesis |
| `app/services/audio.py` | WAV concatenation with streaming for large files |
| `app/services/storage.py` | Google Cloud Storage upload |
| `app/services/notification.py` | Webhook callbacks with retry logic |
| `app/services/tts_job.py` | Complete TTS pipeline orchestration |
| `app/utils/text.py` | Sentence-boundary text chunking |

### Running the Service

```bash
# With Docker (recommended)
./run-docker.sh --detached

# Or run directly (requires Python 3.11)
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/
```

### Code Style

This project follows PEP 8 conventions enforced by ruff:
- Max line length: 120 characters
- Use type hints for all function signatures
- Follow PEP 8 naming conventions
- Document all public functions with docstrings

## License

Part of the Ghost Narrator project. See main repository LICENSE.

## Support

For issues specific to:
- **TTS service**: Open issue in this repository
- **Fish Speech model**: See [Fish Speech GitHub](https://github.com/fishaudio/fish-speech)
- **Voice cloning quality**: Check reference WAV quality first

## Credits

Built with:
- [Fish Speech v1.5](https://github.com/fishaudio/fish-speech) - Voice cloning model
- [FastAPI](https://fastapi.tiangolo.com/) - API framework
- [pydub](https://github.com/jiaaro/pydub) - Audio processing
- [Google Cloud Storage](https://cloud.google.com/storage) - Audio hosting
 
