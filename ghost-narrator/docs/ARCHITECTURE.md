# Ghost Audio Pipeline — Architecture & Setup Guide

Overview
- This document describes the architectural components, data flows, and deployment guidance for the Ghost Audio Pipeline, including the Fish Speech v1.5 TTS backend and the surrounding infrastructure (n8n, Redis, GCS, vLLM, Ghost integration).

Migration to Fish Speech v1.5
- Replaced Coqui XTTS v2 with Fish Speech v1.5 as the TTS backend.
- Tokens are stored in voices/reference_vq_tokens.npy (canonical token file accompanying reference.wav).
- DAC artifacts are preserved for debugging: voices/fake.npy.
- The original reference audio remains intact: voices/reference.wav.
- Cross-filesystem safety: if a rename crosses devices, a safe copy fallback is used to preserve sources.

Artifact details
- Reference audio: /app/voices/reference.wav (read-only for downstream processes)
- DAC artifact: /app/voices/fake.npy
- Tokens: /app/voices/reference_vq_tokens.npy

Documentation impacts
- ARCHITECTURE.md updated to reflect the new model and file paths.
- API health/docs reflect Fish Speech v1.5

Testing & Verification
- Build and run the service; verify artifacts exist in /app/voices and the engine starts without error.
- Ensure the health endpoint returns healthy and that /docs shows Fish Speech v1.5.

Build & Deployment
- TTS Service Build Architecture: built via a staged Dockerfile to improve build reliability.
- Resource requirements: CPU/GPU memory/VRAM budgets per environment.
- Deployment via init.sh: orchestrates secret sync, build, and service startup.
- Common build issues & solutions: lists typical pain points and their fixes.
- Manual build (advanced) section to debug with plain Docker builds.
- Production deployment checklist for secrets, GCS, and network access.
- Build performance and verification steps.

Component Deep Dive
- TTS Service (Fish Speech v1.5): architecture and pipeline steps (reference encoding, semantic generation, decoding, and streaming concatenation).
- Steps to prepare reference voice, create env, start services, and import n8n workflows.
- n8n credential setup and environment variable wiring for GCS and TTS endpoints.
- GCS bucket and IAM setup for storage and access control.
- Testing & Troubleshooting: typical issues and remedies.
- Cost analysis and operational considerations.

Directory structure (summary)
- ghost-narrator/...
- tts-service/ ...
- voices/ reference.wav

Data path references (summary)
- Reference WAV: /app/voices/reference.wav
- DAC token artifact: /app/voices/fake.npy (debug artifact)
- Reference tokens: /app/voices/reference_vq_tokens.npy

Versioning and references
- Fish Speech v1.5 is the current engine; ensure code paths reference:
- CLI tools: python -m tools.vqgan.inference and python -m tools.llama.generate

Notes
- This document supersedes any older embedded notes in README files. See CHANGELOG for migration entries.

End of ARCHITECTURE.md
