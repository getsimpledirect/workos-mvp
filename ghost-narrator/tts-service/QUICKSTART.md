# TTS Service Quick Start Guide

## 🚀 Studio-Quality Narration

This service has been upgraded to **Fish Speech v1.5**, delivering professional, studio-quality narration for your Ghost articles.

**Feature**: High-fidelity zero-shot voice cloning with natural prosody and breathing.

---

## ⚡ Quick Start (3 Steps)

### Step 1: Add Your Voice Sample

Place a reference voice WAV file in the `voices` directory:

```powershell
# Windows PowerShell
cd ghost-narrator\tts-service

# Create voices directory if needed
mkdir voices

# Add your voice file (rename it to reference.wav)
# Requirements: WAV format, 22.05 kHz, mono, 45-60s
# The system will automatically transcribe this file on first boot.
```

**Convert any audio to the correct format:**

```bash
ffmpeg -i your-voice.mp3 -ar 22050 -ac 1 -c:a pcm_s16le voices/reference.wav
```

---

### Step 2: Run with Docker (Choose One)



#### Option A: Using PowerShell Script (Windows - Easiest)

```powershell
# Run in foreground (see logs in terminal)
.\run-docker.ps1

# OR run in background (detached mode)
.\run-docker.ps1 -Detached

# View logs
.\run-docker.ps1 -Logs

# Stop service
.\run-docker.ps1 -Stop
```

#### Option B: Using Docker Compose (All Platforms)

```bash
# From ghost-narrator directory
cd ..
docker-compose up tts-service --build

# OR run in background
docker-compose up -d tts-service --build
```

#### Option C: Using Bash Script (Linux/Mac)

```bash
# Make script executable
chmod +x run-docker.sh

# Run in foreground
./run-docker.sh

# OR run in background
./run-docker.sh --detached

# View logs
./run-docker.sh --logs

# Stop service
./run-docker.sh --stop
```

---

### Step 3: Verify Services are Running

Check that both TTS service and Redis are running:

```powershell
# PowerShell
docker ps

# You should see both containers:
# - tts-service
# - redis
```

Once running, the service is available at: **http://localhost:8020**

**Test the health endpoint:**

```powershell
# PowerShell
Invoke-WebRequest -Uri http://localhost:8020/health | ConvertFrom-Json

# Or use curl
curl http://localhost:8020/health
```

**Expected response:**

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
  "jobs_count": 0,
  "max_workers": 4,
  "executor_active": true,
  "gcs_client_active": true
}
```

**Note:** `job_store` should show `"redis"` (persistent storage). If it shows `"memory"`, check Redis container status.

**View API documentation:**

Open in your browser: http://localhost:8020/docs

---

## 📝 Usage Example

### Generate Audio from Text

```powershell
# PowerShell example
$body = @{
    text = "This is a test of the voice cloning system. The audio will sound like the reference voice."
    job_id = "test-001"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://localhost:8020/tts/generate" -Body $body -ContentType "application/json"
# Note: First run triggers one-time reference voice calibration (~30-60 seconds).
# Subsequent requests use the calibrated voice immediately.
```

```bash
# Bash/curl example
curl -X POST "http://localhost:8020/tts/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "This is a test of the voice cloning system.",
    "job_id": "test-001"
  }'
```

### Check Job Status

```powershell
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8020/tts/status/test-001" | ConvertFrom-Json

# Bash/curl
curl "http://localhost:8020/tts/status/test-001"
```

### Download Generated Audio

```powershell
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8020/tts/download/test-001" -OutFile "output.mp3"

# Bash/curl
curl "http://localhost:8020/tts/download/test-001" -o output.mp3
```

---

## 🎛️ Configuration

### Environment Variables (Optional)

Set these before running if you want to customize:

```powershell
# Windows PowerShell
$env:TTS_LANGUAGE = "en"           # Language code (en, es, fr, de, etc.)
$env:MAX_CHUNK_WORDS = "200"       # Max words per synthesis chunk
$env:TTS_DEVICE = "cpu"            # Use "cuda" for GPU acceleration
$env:MAX_WORKERS = "4"             # Thread pool size for parallel synthesis

# Then run
.\run-docker.ps1 -Detached
```

```bash
# Linux/Mac
export TTS_LANGUAGE="en"
export MAX_CHUNK_WORDS="200"
export TTS_DEVICE="cpu"
export MAX_WORKERS="4"

./run-docker.sh --detached
```

### Performance Configuration

**NEW: Parallel Processing for CPU Mode**

The service now supports parallel chunk synthesis for dramatically faster processing on CPU:

```powershell
# Quad-core CPU (recommended)
$env:MAX_WORKERS = "4"

# Octa-core CPU
$env:MAX_WORKERS = "8"

# High-core-count server
$env:MAX_WORKERS = "16"

.\run-docker.ps1 -Rebuild
```

**Performance Improvements:**
- 2000-word article: ~3-5 minutes → ~50-60 seconds (4 workers)
- Memory usage: Reduced by up to 80% for large articles
- Automatic streaming concatenation for files >10 chunks
- Connection pooling for faster GCS uploads and callbacks

### Google Cloud Storage (Optional)

To enable automatic upload to GCS:

```powershell
$env:GCS_BUCKET_NAME = "your-bucket-name"
$env:GCS_AUDIO_PREFIX = "audio/articles"
```

### Redis Configuration (Optional)

Redis is included by default for persistent job storage:

```powershell
# Change Redis connection (advanced)
$env:REDIS_URL = "redis://localhost:6379/0"

# Change job retention time (default: 24 hours)
$env:REDIS_JOB_TTL = "86400"  # seconds
```

**Benefits:**
- ✅ Jobs survive container restarts
- ✅ No data loss on crashes
- ✅ Can recover running jobs
- ✅ Automatic fallback to memory if Redis unavailable

---

## 🔧 Troubleshooting

### "Reference voice file not found"

```powershell
# Check if file exists
Test-Path .\voices\reference.wav

# Should return: True
```

If False, add your voice file to `voices/reference.wav`

### "Docker is not running"

Start Docker Desktop application first, then try again.

### "Port 8020 already in use"

Another service is using port 8020. Stop it or change the port:

```powershell
# Stop existing container
.\run-docker.ps1 -Stop

# Or change port in docker-compose.override.yml
# Change: "8020:8020" to "8021:8020"
```

### Slow generation (3-5 minutes per article)

This is normal for CPU mode with default settings. For faster generation:

1. **Enable parallel processing** (recommended):
   ```powershell
   # Quad-core CPU
   $env:MAX_WORKERS = "4"
   
   # Octa-core CPU
   $env:MAX_WORKERS = "8"
   
   .\run-docker.ps1 -Rebuild
   ```
   With 4 workers: ~50-60 seconds per 2000 words (vs 3-5 minutes sequential)

2. Use GPU mode (requires NVIDIA GPU with 4GB+ VRAM):
   ```powershell
   $env:TTS_DEVICE = "cuda"
   .\run-docker.ps1 -Rebuild
   ```
   GPU mode: ~20-30 seconds per 2000 words

3. Reduce chunk size for better pronunciation:
   ```powershell
   $env:MAX_CHUNK_WORDS = "150"
   ```

### First run calibration

The first synthesis request triggers a one-time reference voice calibration:
1. Whisper transcribes your reference audio (~10-20 seconds)
2. DAC codec encodes to VQ tokens (~10-20 seconds)
3. Calibration artifacts saved for all future requests

**This happens only once at startup.** Subsequent requests use the calibrated voice immediately.

### Jobs lost after restart

**This should NOT happen anymore!** Jobs are persisted to Redis.

If you still experience job loss:
- Check Redis is running: `docker ps | grep redis`
- Verify health endpoint shows `"job_store": "redis"`
- Check logs: `docker logs tts-service | grep Redis`

### View detailed logs

```powershell
# PowerShell
.\run-docker.ps1 -Logs

# Docker Compose
docker-compose logs -f tts-service

# TTS + Redis logs
docker-compose logs -f tts-service redis

# Direct Docker
docker logs -f tts-service
```

---

## 📊 Performance

| Mode | Device | Speed | Memory | Notes |
|------|--------|-------|--------|-------|
| CPU (Sequential) | Any | ~3-5 min/2000 words | 800MB RAM | 1 worker (legacy) |
| CPU (Parallel 4x) | Quad-core+ | ~50-60 sec/2000 words | 1GB RAM | **Recommended default** |
| CPU (Parallel 8x) | Octa-core+ | ~30-40 sec/2000 words | 1.2GB RAM | High performance |
| GPU | NVIDIA L4/T4 | ~20-30 sec/2000 words | 3GB VRAM + 6GB RAM | Requires GPU config |

**Default Configuration:**
- `TTS_DEVICE=cpu` (safe for all systems)
- `MAX_WORKERS=4` (parallel synthesis enabled by default)
- Streaming concatenation auto-enabled for large files (>10 chunks)

**Key Improvements:**
- ⚡ **Up to 6x faster** on CPU with parallel synthesis (4 workers)
- 💾 **80% less memory** for large articles (streaming concatenation)
- 🔗 **Faster uploads** with connection pooling (~50% improvement)
- 🎯 **Smart processing** adapts to workload automatically
- 🔄 **Persistent jobs** with Redis (survive container restarts)

---

## 🎯 Next Steps

1. **Test with your voice**: Generate a short test audio
2. **Optimize performance**: Set `MAX_WORKERS` to match your CPU cores
3. **Integrate with n8n**: Set up the callback webhook
4. **Configure GCS**: Enable automatic cloud storage
5. **Production deployment**: Review security and scaling

### Security Model

The TTS service is designed as an **internal microservice** within the Ghost Narrator pipeline:

- Runs on internal Docker network (not exposed to internet)
- Called only by n8n workflow (not directly by users)
- Protected by Docker network isolation and VM firewall

**For production:** Ensure the service is not directly exposed to the internet. Access through n8n or a reverse proxy with authentication.

For detailed documentation, see [README.md](./README.md)

---

## 💡 Key Points

✅ **No Python downgrade needed** - Docker handles version compatibility  
✅ **Zero code changes** - Your Python 3.12 system is unaffected  
✅ **First-class voice cloning** - Fish Speech v1.5 with 45-60s reference audio  
✅ **Production-ready** - Async processing, GCS upload, webhook callbacks  
✅ **High performance** - Parallel synthesis, resource pooling, streaming optimization  
✅ **Persistent storage** - Redis-backed job state, no data loss on restart

---

## 📚 Additional Resources

- **API Documentation**: http://localhost:8020/docs (when running)
- **Full Documentation**: [README.md](./README.md)
- **Fish Speech v1.5**: https://github.com/fishaudio/fish-speech
- **Docker Documentation**: https://docs.docker.com/
- **FastAPI Docs**: https://fastapi.tiangolo.com/

---

## 🆘 Getting Help

If you encounter issues:

1. Check logs: `.\run-docker.ps1 -Logs`
2. Verify Docker is running: `docker version`
3. Check health endpoint: `curl http://localhost:8020/health`
4. Review this guide's troubleshooting section
5. Check main [README.md](./README.md) for detailed information

---

**Happy voice cloning! 🎙️**