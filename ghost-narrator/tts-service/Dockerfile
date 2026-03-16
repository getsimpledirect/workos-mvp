# Using modern CUDA runtime for Fish Speech v1.5
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# Pip timeout and retry settings for production stability
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=5
# Build settings to prevent resolution issues
ENV PIP_NO_DEPS=0

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    git \
    build-essential \
    python3-dev \
    portaudio19-dev \
    libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY requirements.txt .

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1: Upgrade pip and build tools
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --upgrade pip==24.3.1 setuptools==68.2.2 wheel==0.44.0

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2: Install core scientific stack (pinned versions to avoid conflicts)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    numpy==1.26.4 \
    scipy==1.13.1 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3: Install PyTorch ecosystem (already present in base, just ensure versions)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    torch==2.4.1 \
    torchaudio==2.4.1 \
    torchvision==0.19.1 \
    triton==3.0.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 4: Install ML frameworks with controlled versions
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    lightning==2.2.5 \
    pytorch-lightning==2.2.5 \
    lightning-utilities==0.11.2 \
    torchmetrics==1.4.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 5: Install transformers and HuggingFace stack
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    transformers==4.45.2 \
    tokenizers==0.20.3 \
    safetensors==0.4.5 \
    huggingface-hub==0.36.2 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 6: Install Gradio with pinned version to avoid backtracking
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    gradio==5.1.0 \
    gradio-client==1.4.0 \
    aiofiles==23.2.1 \
    ffmpy==1.0.0 \
    pandas==2.3.3 \
    tomlkit==0.12.0 \
    semantic-version==2.10.0 \
    ruff==0.5.7 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 7: Install audio processing libraries
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    llvmlite==0.43.0 \
    numba==0.60.0 \
    librosa==0.10.2 \
    soundfile==0.12.1 \
    pydub==0.25.1 \
    resampy==0.4.3 \
    audioread==3.1.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 8: Install Whisper
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary openai-whisper && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 9: Install FastAPI stack
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    pydantic==2.9.2 \
    pydantic-core==2.23.4 \
    pydantic-settings==2.5.2 \
    starlette==0.37.2 \
    python-multipart==0.0.9 \
    httpx==0.27.0 \
    httpcore==1.0.9 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 10: Install Google Cloud dependencies
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    google-cloud-storage==2.16.0 \
    google-auth==2.29.0 \
    google-crc32c==1.6.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 11: Install data processing libraries
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    datasets==2.18.0 \
    pyarrow==23.0.0 \
    dill==0.3.8 \
    xxhash==3.5.0 \
    multiprocess==0.70.16 \
    fsspec==2024.2.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 12: Install Hydra configuration framework
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    hydra-core==1.3.2 \
    omegaconf==2.3.0 \
    antlr4-python3-runtime==4.9.3 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 13: Install text processing and gruut (combined for efficiency)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    inflect==7.0.0 \
    anyascii==0.3.2 \
    tiktoken==0.8.0 \
    sentencepiece==0.2.1 \
    gruut[de,es,fr]==2.2.3 \
    bangla==0.0.2 \
    bnnumerizer==0.0.2 \
    bnunicodenormalizer==0.1.6 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 14: Install model-specific utilities
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    natsort==8.4.0 \
    einops==0.8.0 \
    einx==0.2.2 \
    vector-quantize-pytorch==1.14.24 \
    loralib==0.1.2 \
    pyrootutils==1.0.4 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 15: Install speech processing tools
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    faster-whisper==1.0.3 \
    silero-vad==5.1.2 \
    opencc-python-reimplemented==0.1.7 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 16: Install modelscope and funasr (complex dependencies)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    modelscope==1.17.1 \
    funasr==1.1.5 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 17: Install monitoring, logging, and utilities (combined)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir --prefer-binary \
    wandb==0.18.7 \
    tensorboard==2.18.0 \
    rich==14.3.3 \
    loguru==0.7.3 \
    redis==5.0.1 \
    grpcio==1.68.1 \
    cachetools==5.5.0 \
    ormsgpack==1.6.0 \
    typing-extensions==4.11.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# STAGE 18: Install Fish Speech (will use already-installed dependencies)
# ═══════════════════════════════════════════════════════════════════════════
RUN pip install --no-cache-dir \
    git+https://github.com/fishaudio/fish-speech.git@v1.5.0 && \
    rm -rf /tmp/* /root/.cache/*

# ═══════════════════════════════════════════════════════════════════════════
# Pre-download model weights (optional, speeds up first run)
# ═══════════════════════════════════════════════════════════════════════════
RUN mkdir -p /app/checkpoints && \
    (python -c "from huggingface_hub import snapshot_download; \
     snapshot_download(repo_id='fishaudio/fish-speech-1.5', \
                       local_dir='/app/checkpoints/fish-speech-1.5', \
                       resume_download=True, \
                       max_workers=4)" 2>&1 || \
     echo "⚠ Model download skipped - will download on first use") && \
    (python -c "import whisper; whisper.load_model('tiny')" 2>&1 || true) && \
    rm -rf /tmp/* /root/.cache/*

# Verify critical imports work
RUN python -c "import fish_speech, torch, transformers, fastapi, google.cloud.storage, redis, librosa" && \
    echo "✓ All critical packages validated"

# ═══════════════════════════════════════════════════════════════════════════
# Copy application code
# ═══════════════════════════════════════════════════════════════════════════
COPY app/ ./app/

# Create necessary directories
RUN mkdir -p /app/voices /app/output

# Expose the service port
EXPOSE 8020

# Health check with improved error handling
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
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
