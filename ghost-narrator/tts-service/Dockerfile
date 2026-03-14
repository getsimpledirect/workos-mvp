# Using CUDA runtime image for GPU acceleration
FROM pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime

# prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

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
