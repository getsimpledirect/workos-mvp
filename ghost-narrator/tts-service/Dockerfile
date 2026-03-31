# Using modern CUDA runtime for Fish Speech v1.5
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies and curl for uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    git \
    build-essential \
    python3-dev \
    portaudio19-dev \
    libportaudio2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv globally for blazingly fast dependency resolution and installation
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    cp /root/.local/bin/uvx /usr/local/bin/uvx
ENV PATH="/usr/local/bin:$PATH"

WORKDIR /app

# Copy dependency files
COPY requirements.txt .

# Install dependencies using uv
RUN uv pip install --system --no-cache -r requirements.txt

# Pre-download model weights (optional, speeds up first run)
RUN mkdir -p /app/checkpoints && \
    (python -c "from huggingface_hub import snapshot_download; \
     snapshot_download(repo_id='fishaudio/fish-speech-1.5', \
                       local_dir='/app/checkpoints/fish-speech-1.5', \
                       resume_download=True, \
                       max_workers=4)" 2>&1 || \
     echo "⚠ Model download skipped - will download on first use") && \
    (python -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')" 2>&1 || \
     echo "⚠ Whisper tiny model pre-cache failed - will download on first reference voice calibration")

# Verify critical imports work
RUN python -c "import torch, transformers, fastapi, google.cloud.storage, redis, librosa" && \
    echo "✓ All critical packages validated"

# Copy application code
COPY app/ ./app/

# Create necessary directories
RUN mkdir -p /app/voices /app/output

# Create non-root user and set ownership
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose the service port
EXPOSE 8020

# Health check with improved error handling
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
    CMD python -c "\
import urllib.request; \
import urllib.error; \
try: \
    response = urllib.request.urlopen('http://localhost:8020/health', timeout=5); \
    if response.status == 200: \
        exit(0); \
    else: \
        print(f'Health check failed: status {response.status}'); \
        exit(1); \
except urllib.error.URLError as e: \
    print(f'Health check error: {e}'); \
    exit(1); \
except Exception as e: \
    print(f'Health check exception: {e}'); \
    exit(1);" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8020", \
     "--workers", "1", \
     "--timeout-keep-alive", "600", \
     "--log-level", "info"]