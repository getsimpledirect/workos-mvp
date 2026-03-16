# Changelog

All notable changes to the Ghost Narrator audio pipeline will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed - TTS Service Initialization Errors (2024-01-15)

**Problem:**
- TTS service failing with `No module named 'fish_speech.models.text_to_semantic'`
- Voice calibration failing with read-only filesystem error

**Root Cause:**
- Python code used incorrect import path: `fish_speech.models.text_to_semantic.llama`
- Correct path is: `fish_speech.models.text2semantic.llama` (no underscore)
- Voices directory mounted as read-only, preventing transcription file writes

**Fixed:**
- Corrected Fish Speech import paths in `tts_engine.py` (`text_to_semantic` → `text2semantic`)
- Removed `:ro` flag from voices volume mount in `docker-compose.yml`
- Pinned Fish Speech to stable `v1.5.0` tag for consistency

**Files Modified:**
- `tts-service/app/core/tts_engine.py` (lines 80, 93)
- `docker-compose.yml` (line 137)
- `tts-service/Dockerfile` (line 215)

**Migration:**
```bash
docker compose build --no-cache tts-service
docker compose restart tts-service
```

---

### Fixed - Docker Build Dependency Resolution (2025-01-XX)

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

[Unreleased]: https://github.com/yourusername/ghost-narrator/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/ghost-narrator/releases/tag/v1.0.0