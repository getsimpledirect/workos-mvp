# Changelog

All notable changes to the Ghost Narrator audio pipeline will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added — Audio Backfill Scripts (2026-03-19)

New utility scripts for generating audio on existing Ghost posts that were published before the pipeline was set up.

**`scripts/backfill-audio.sh`** (Linux / macOS):
- Prompts for n8n webhook URL, Ghost site URLs + Content API keys, delay between jobs, and dry-run mode
- Paginates the Ghost Content API to retrieve all published posts
- Filters posts where HTML does not contain an `<audio>` element
- Sends each post sequentially to the n8n pipeline with a configurable delay (default: 300 s) to avoid overloading the TTS service
- Supports multiple Ghost sites in a single run
- Requires `curl` and `jq`

**`scripts/backfill-audio.ps1`** (Windows — native PowerShell):
- Identical functionality implemented in PowerShell 5.1+ compatible syntax
- Uses `Invoke-RestMethod` for Ghost Content API and `Invoke-WebRequest` for webhook trigger
- No external dependencies beyond built-in PowerShell cmdlets

---

### Fixed — TTS Service Hardening & Production Readiness (2026-03-19)

Comprehensive bug fixes across the entire TTS service codebase.

**Core fixes:**
- `config.py`: Wrapped all `int(os.environ.get(...))` calls in `try/except ValueError` so invalid env vars (e.g. `MAX_WORKERS=auto`) no longer crash the service at import time
- `main.py`: Stored `asyncio.create_task()` reference in a module-level variable to prevent premature garbage collection; cancel the task cleanly on shutdown
- `job_store.py`: Removed permanent `self.use_redis = False` on transient Redis errors — the service now falls back gracefully per-operation without permanently disabling Redis
- `tts_job.py`: Added `gcs_upload_failed` flag so GCS failures are non-fatal and reflected in job metadata (`gcs_upload_warning`); standardised error truncation to 450 chars
- `synthesis.py`: Added `await asyncio.gather(*tasks, return_exceptions=True)` after parallel task cancellation to prevent resource leaks
- `storage.py`: Added exponential-backoff retry loop (up to `MAX_RETRIES` attempts, capped at 30 s) for GCS uploads
- `tts.py`: Removed dead `TYPE_CHECKING` import block

**Tests:**
- Added `pytest.ini` with `asyncio_mode = auto`
- Added three new test cases: synthesis failure, GCS failure with non-fatal completion, and missing executor

**Scripts:**
- `run-docker.sh` / `run-docker.ps1`: Added `MAX_WORKERS` env var passthrough

**Docs:**
- `docs/ARCHITECTURE.md`: Fixed orphaned Python code fragment in "Test Voice Cloning" section; fixed duplicate `## Component Deep Dive` heading; updated directory structure listing
- `scripts/validate-build.sh`: Extended startup health-check timeout from 60 s → 300 s to accommodate Fish Speech model downloads
- `tts-service/README.md`: Corrected Code Style section (ESLint/Prettier → PEP 8/ruff)

---

### Fixed - Fish Speech v1.5 Implementation (2025-01-16)

**Problem:**
- TTS service failing with `cannot import name 'LlamaForConditionalGeneration' from 'fish_speech.models.text2semantic.llama'`
- Engine code written for non-existent Fish Speech API
- Architecture mismatch between documentation and implementation

**Root Cause:**
- Code attempted to use classes (`LlamaForConditionalGeneration`, `Firefly`) that don't exist in Fish Speech v1.5
- Fish Speech v1.5 uses CLI-based inference, not a Python library API
- Original code was written for a different TTS system or Fish Speech version

**Solution Implemented:**
- Complete rewrite of `tts_engine.py` to use Fish Speech v1.5 CLI-based inference pipeline
- Implemented 3-step synthesis process via subprocess calls:
  1. Reference audio encoding (DAC codec → VQ tokens)
  2. Semantic token generation (text2semantic model)
  3. Audio decoding (DAC decoder → WAV file)
- Removed `:ro` flag from voices volume mount for transcription file writes
- Pinned Fish Speech to stable `v1.5.0` tag

**Technical Implementation:**
- Uses `subprocess.run()` to call Fish Speech CLI tools
- Reference audio encoded once during initialization
- Semantic tokens generated per synthesis request
- Working directory managed to handle Fish Speech's file outputs
- Thread-safe synthesis with proper cleanup

**Files Modified:**
- `tts-service/app/core/tts_engine.py` (complete rewrite, 500+ lines changed)
- `docker-compose.yml` (line 137 - removed `:ro` flag)
- `tts-service/Dockerfile` (line 215 - pinned to v1.5.0)

**Performance:**
- Initialization: ~30-60 seconds (reference encoding + transcription)
- Synthesis: ~10-30 seconds per request (device-dependent)
- Memory: 4-6GB RAM (GPU mode), 8-16GB RAM (CPU mode)

**Migration:**
```bash
docker compose build --no-cache tts-service
docker compose up -d
# Wait for initialization (~1-2 minutes)
docker compose logs -f tts-service
```

**Verification:**
```bash
# Should see: "Fish Speech v1.5 engine ready (Studio Quality)"
curl http://localhost:8020/health
```

---

### Fixed - Docker Build Dependency Resolution (2025-01)

**Problem:**
Docker build failing with `resolution-too-deep` error after 30+ minutes when pip tries to resolve 50+ packages simultaneously.

**Fixed:**
- Restructured Dockerfile with 20-stage installation process (packages installed in dependency order)
- Pinned all package versions to exact releases (e.g., `numpy==1.26.4`, `gradio==5.1.0`)
- Added build retry logic and resource validation to `init.sh`

**Files Modified:**
- `tts-service/Dockerfile` (complete rewrite with staged builds)
- `tts-service/requirements.txt` (added version constraints)
- `scripts/init.sh` (added retry logic)
- `tts-service/README.md` (added build troubleshooting)
- `docs/ARCHITECTURE.md` (added build documentation)

**Performance:**
- Build time: 15-25 minutes (previously: failed)
- Success rate: 95%+ (previously: 0%)

**Migration:**
```bash
docker compose build --no-cache tts-service
docker compose up -d
```

See `docs/ARCHITECTURE.md` for technical details.

---

## [1.0.0] - Initial Release

### Added
- TTS service with Fish Speech v1.5 integration
- n8n workflow automation for Ghost CMS
- Redis job state persistence
- GCS audio storage integration
- Voice cloning with reference audio
- Multi-site Ghost support
- Comprehensive documentation

### Components
- TTS Service API (FastAPI + Fish Speech)
- n8n Workflow Engine
- Redis Job Store
- Docker Compose orchestration
- GCP integration (GCS, Secret Manager)
- Init scripts for automated deployment

---

[Unreleased]: https://github.com/getsimpledirect/workos-mvp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/getsimpledirect/workos-mvp/releases/tag/v1.0.0
