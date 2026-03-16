# Using modern CUDA runtime for Fish Speech v1.5
FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

# prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_CONSTRAINT=/app/constraints.txt
ENV PIP_BUILD_CONSTRAINT=/app/constraints.txt

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

# Copy and install Python dependencies
COPY constraints.txt .
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip "setuptools==68.2.2" wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# Pre-download model weights for Fish Speech and Whisper
RUN python -c "from huggingface_hub import snapshot_download; \
    snapshot_download(repo_id='fishaudio/fish-speech-1.5', local_dir='/app/checkpoints/fish-speech-1.5'); \
    import whisper; whisper.load_model('tiny')"

# Copy the application package
COPY app/ ./app/

# Create necessary directories
RUN mkdir -p /app/voices /app/output

# Expose the service port
EXPOSE 8020

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8020/health')" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8020", \
     "--workers", "1", \
     "--timeout-keep-alive", "600", \
     "--log-level", "info"]
