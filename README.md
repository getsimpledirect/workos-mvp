# WorkOS MVP

> **AI-Powered Infrastructure Stack** — Local LLM inference, vector database, and automated content pipelines.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Components](#components)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Services](#services)
- [Ghost Narrator Pipeline](#ghost-narrator-pipeline)
- [Configuration](#configuration)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

WorkOS MVP is a comprehensive AI infrastructure stack designed for self-hosted, privacy-first AI workflows. It combines local LLM inference with workflow automation to power intelligent content pipelines.

### Key Features

- **Local LLM Inference** — Run Qwen3-14B locally with vLLM for fast, private AI processing.
- **Vector Database** — ChromaDB for semantic search and RAG applications.
- **Web UI** — Open WebUI for interactive chat with your local models.
- **Audio Pipeline** — Automated voice narration for Ghost CMS articles using voice cloning.
- **Workflow Orchestration** — n8n for visual workflow automation and integrations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        WorkOS MVP Infrastructure                         │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                     Core AI Services (docker-compose.yml)            │ │
│  │                                                                       │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  │   ChromaDB   │  │   vLLM API   │  │   SearXNG    │  │  Open WebUI  │ │
│  │  │   Vector DB  │  │  Qwen3-14B   │  │  Web Search  │  │  Interface   │ │
│  │  │   :8000      │  │  :8001       │  │  :8888       │  │  :3000       │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │               Ghost Narrator Pipeline (ghost-narrator/)              │ │
│  │                                                                       │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐       │ │
│  │  │    Redis     │  │     n8n      │  │    TTS Service       │       │ │
│  │  │  Job Store   │  │  Workflows   │  │  Fish Speech v1.5    │       │ │
│  │  │  :6379       │  │  :5678       │  │   :8020              │       │ │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### Core Stack (`docker-compose.yml`)

| Service | Port | Description |
|---------|------|-------------|
| **ChromaDB** | 8000 | Vector database for embeddings and semantic search |
| **vLLM (Qwen3-14B)** | 8001 | High-performance LLM inference with OpenAI-compatible API |
| **SearXNG** | 8888 | Locally hosted metasearch engine for live web knowledge |
| **Open WebUI** | 3000 | Modern chat interface for interacting with local models |

### Ghost Narrator Pipeline (`ghost-narrator/`)

| Service | Port | Description |
|---------|------|-------------|
| **Redis** | 6379 | Job state persistence and queue management |
| **n8n** | 5678 | Visual workflow orchestration and automation |
| **TTS Service** | 8020 | Voice-cloning TTS API using Fish Speech v1.5 |

---

## Prerequisites

### Hardware Requirements

- **GPU**: NVIDIA GPU with 16GB+ VRAM (L4, RTX 4090, or equivalent)
- **RAM**: 16GB minimum, 32GB recommended
- **Storage**: 300GB+ SSD for models and data

### Software Requirements

- **Docker** with Docker Compose V2
- **NVIDIA Container Toolkit** (for GPU support)
- **Git**

### Optional

- **Google Cloud SDK** (for GCS audio storage)
- **Ghost CMS** (for audio pipeline integration)

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/workos-mvp.git
cd workos-mvp
```

### 2. Start Core AI Services

We use a helper script to automatically retrieve credentials from GCP Secret Manager and boot the stack:

```bash
# Start ChromaDB, vLLM, SearXNG, and Open WebUI
chmod +x start-core.sh
./start-core.sh

# Check service health
docker compose ps
docker compose logs -f vllm-qwen3-14b
```

### 3. Access Services

- **Open WebUI**: http://localhost:3000
- **vLLM API**: http://localhost:8001/v1
- **ChromaDB**: http://localhost:8000

---

## Services

### ChromaDB

Persistent vector database for embeddings storage.

```bash
# Health check
curl http://localhost:8000/api/v1/heartbeat

# Use with Python
pip install chromadb
```

```python
import chromadb

client = chromadb.HttpClient(host="localhost", port=8000)
collection = client.create_collection("documents")
```

### vLLM (Qwen3-14B)

OpenAI-compatible API for local LLM inference.

```bash
# Chat completion
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-14B-AWQ",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**Configuration:**

- Model: `Qwen/Qwen3-14B-AWQ` (quantized for efficiency)
- Context Length: 28,000 tokens
- GPU Memory Utilization: 92%

### Open WebUI

Modern chat interface connected to your local vLLM instance.

- Access at http://localhost:3000
- First user registration creates admin account
- Supports multiple conversations, file uploads, and RAG
- **Web Search**: Integrated with local SearXNG instance. Click the `+` button or search icon in chat to enable real-time web search for the LLM.

---

## Ghost Narrator Pipeline

Automatically convert Ghost CMS articles into voice-narrated audio using your cloned voice.

### How It Works

1. **Ghost Webhook** triggers on article publish
2. **n8n** orchestrates the pipeline
3. **vLLM** rewrites content for narration
4. **TTS Service** synthesizes audio with cloned voice
5. **GCS** stores the final MP3 files

### Setup

```bash
cd ghost-narrator

# Create environment file
cp .env.example .env
# Edit .env with your configuration

# Add your voice sample (6-60 seconds WAV, 45+ seconds recommended)
cp /path/to/your/voice.wav tts-service/voices/reference.wav

# Initialize and start services
./scripts/init.sh
```

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `SERVER_EXTERNAL_IP` | External IP for webhook URLs |
| `N8N_USER` | n8n admin username |
| `N8N_PASSWORD` | n8n admin password |
| `N8N_ENCRYPTION_KEY` | n8n encryption key (`openssl rand -hex 32`) |
| `GCS_BUCKET_NAME` | GCS bucket for audio storage |
| `VLLM_BASE_URL` | URL to vLLM API |
| `VLLM_MODEL_NAME` | Model name for vLLM |
| `GHOST_SITE1_ADMIN_API_KEY` | Admin API key for Ghost site 1 |
| `GHOST_SITE2_ADMIN_API_KEY` | Admin API key for Ghost site 2 |
| `TTS_DEVICE` | Device to run TTS on (`cpu` or `cuda`) |
| `MAX_WORKERS` | Number of parallel workers for CPU synthesis |
| `TIMEZONE` | Timezone for the n8n container |


### GCP Setup (Optional)

For Google Cloud Storage integration:

```bash
# Configure GCP resources (bucket, service account, IAM)
./scripts/setup-gcp.sh
```

### Documentation

- [Full Architecture Guide](ghost-narrator/docs/ARCHITECTURE.md)
- [TTS Service Documentation](ghost-narrator/tts-service/README.md)
- [TTS Quick Start](ghost-narrator/tts-service/QUICKSTART.md)

---

## Configuration

### Environment Variables

Create a `.env` file in the appropriate directory:

**Root level (Core Services):**

```env
WEBUI_URL=http://localhost:3000
SEARXNG_SECRET=your-static-secret-here # Only needed if not using start-core.sh and GCP Secret Manager
```

**ghost-narrator/ (Audio Pipeline):**

```env
SERVER_EXTERNAL_IP=your-vm-external-ip
N8N_USER=admin
N8N_PASSWORD=your-secure-password
N8N_ENCRYPTION_KEY=<openssl rand -hex 32>
GCS_BUCKET_NAME=your-gcs-bucket-name
VLLM_BASE_URL=http://host.docker.internal:8000
VLLM_MODEL_NAME=Qwen/Qwen3-14B-AWQ
GHOST_SITE1_ADMIN_API_KEY=your-admin-key-1
GHOST_SITE2_ADMIN_API_KEY=your-admin-key-2
TTS_DEVICE=cpu
MAX_WORKERS=4
TIMEZONE=UTC
```

### GPU Memory Planning

| Service | VRAM Usage |
|---------|------------|
| vLLM (Qwen3-14B-AWQ) | ~8GB |
| TTS Service (Fish Speech v1.5) | ~2-3GB |
| **Total** | ~10-11GB |

---

## Usage

### Starting All Services

```bash
# Core AI services
./start-core.sh

# Ghost Narrator pipeline
cd ghost-narrator
./scripts/init.sh
```

### Stopping Services

```bash
# Core services
docker compose down

# Ghost Narrator
cd ghost-narrator
docker compose down
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f vllm-qwen3-14b
docker compose logs -f tts-service
```

### Health Checks

```bash
# ChromaDB
curl http://localhost:8000/api/v1/heartbeat

# vLLM
curl http://localhost:8001/health

# TTS Service
curl http://localhost:8020/health

# n8n
curl http://localhost:5678/healthz
```

---

## Troubleshooting

### vLLM Won't Start

**Symptoms:** Container crashes or fails health check

**Solutions:**

1. Check GPU availability: `nvidia-smi`
2. Verify NVIDIA Container Toolkit: `docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi`
3. Check logs: `docker compose logs vllm-qwen3-14b`
4. Reduce `--gpu-memory-utilization` if OOM errors

### TTS Service Slow to Start

**Symptoms:** Health check times out

**Cause:** First run downloads Fish Speech v1.5 models (~4GB)

**Solution:** Wait up to 5 minutes for initial model download

### ChromaDB Connection Issues

**Symptoms:** Can't connect to ChromaDB

**Solutions:**

1. Verify service is running: `docker compose ps`
2. Check port availability: `netstat -an | grep 8000`
3. Review logs: `docker compose logs chroma`

### n8n Workflow Errors

**Symptoms:** Workflows fail or webhooks don't trigger

**Solutions:**

1. Verify `SERVER_EXTERNAL_IP` is correct
2. Check firewall allows port 5678
3. Review n8n logs: `docker compose logs n8n`

---

## Project Structure

```
workos-mvp/
├── docker-compose.yml          # Core AI services configuration
├── README.md                   # This file
│
└── ghost-narrator/             # Audio narration pipeline
    ├── .env.example            # Environment variable template
    ├── docker-compose.yml      # Pipeline services configuration
    ├── .gitignore              # Git ignore rules
    │
    ├── docs/
    │   └── ARCHITECTURE.md     # Detailed architecture documentation
    │
    ├── n8n/
    │   └── workflows/
    │       ├── ghost-audio-pipeline.json         # Synthesizes audio from Ghost posts
    │       ├── ghost-audio-callback.json         # Embeds audio player in Ghost
    │       └── static-content-audio-pipeline.json # Synthesizes audio from static content
    │
    ├── scripts/
    │   ├── init.sh             # VM initialization script
    │   └── setup-gcp.sh        # GCP resource setup script
    │
    └── tts-service/            # Voice cloning TTS API
        ├── Dockerfile          # Container build configuration
        ├── README.md           # TTS service documentation
        ├── QUICKSTART.md       # Quick start guide
        ├── requirements.txt    # Python dependencies
        ├── run-docker.sh       # Docker run script (Linux/Mac)
        ├── run-docker.ps1      # Docker run script (Windows)
        ├── app/                # FastAPI application code
        └── voices/             # Voice samples directory
```

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

> **Note:** The Fish Speech v1.5 model weights are licensed under **CC BY-NC-SA 4.0** by Fish Audio. This license applies to the model weights only, not to the Ghost Narrator source code. Commercial use of the model weights requires a separate license from Fish Audio. See [NOTICE](NOTICE) for details.

---

## Support

For issues or questions:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review service logs
3. Consult the [Architecture Documentation](ghost-narrator/docs/ARCHITECTURE.md)