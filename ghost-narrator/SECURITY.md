# Security Policy

## Supported Versions

We currently support the following versions of Ghost Narrator:

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < 1.0   | :x:                |

*The current release is v1.3.0 - see [releases](https://github.com/getsimpledirect/workos-mvp/releases) for details.*

## Reporting a Vulnerability

If you discover a security vulnerability within Ghost Narrator, please report it via **GitHub Issues**: https://github.com/getsimpledirect/workos-mvp/issues

Please mark the issue as "Security" or email the maintainer directly if it's sensitive.

Please include the following information:

- **Type** of vulnerability (e.g., XSS, SQL injection, etc.)
- **Full paths** of source file(s) related to the vulnerability
- **Location** of the affected source code (tag/branch/commit or direct URL)
- **Any** special configuration required to reproduce the issue
- **Step-by-step** instructions to reproduce the issue
- **Proof-of-concept** or exploit code (if possible)
- **Impact** of the issue, including how an attacker might exploit it

## What to Expect

- **Acknowledgment**: You should receive a response within 24 hours
- **Status Update**: We will provide updates on the progress of fixing the vulnerability
- **Disclosure**: Once the vulnerability is fixed, we will publicly disclose the vulnerability details

## Security Best Practices

When deploying Ghost Narrator:

1. **Never commit secrets** - Use `.env.example` as a template, never commit `.env`
2. **Rotate credentials regularly** - Especially n8n encryption keys and API keys
3. **Use HTTPS** - Enable TLS/SSL for all web-facing services
4. **Restrict network access** - Use firewall rules to limit access to internal services
5. **Keep dependencies updated** - Use Dependabot to receive security updates
6. **Monitor logs** - Review Docker and application logs for suspicious activity

## Architecture Security Model

Ghost Narrator uses a **defense-in-depth** approach with multiple security layers:

### Layer 1: Docker Network Isolation
The TTS service is designed to run on an internal Docker network, not exposed to the public internet. The `docker-compose.yml` configuration keeps services isolated:

- **TTS Service** (`tts-service`) - Internal only, not exposed to host
- **n8n** (`n8n`) - Exposed on port 5678 for webhook receiving
- **Redis** (`redis`) - Internal only

This means the TTS service can only be accessed by other services in the same Docker network (primarily n8n), not directly from the internet.

### Layer 2: VM Firewall
For production deployments, restrict access at the firewall level:
- Allow inbound to n8n (port 5678) only from Ghost CMS IPs
- Allow inbound to TTS service only from n8n (if needed)
- Block all other inbound access

### Layer 3: n8n Authentication
Users access the pipeline through n8n's built-in authentication, not directly to the TTS service.

### Why TTS Service Has No API Authentication

The TTS service operates as an **internal microservice** within the Ghost Narrator pipeline:
- It is called exclusively by n8n (not end users)
- It is protected by Docker network isolation
- It is further protected by VM-level firewall rules

This is a common pattern for backend services in a microservices architecture.

### For Open Source Users

If you plan to expose the TTS service directly (e.g., to build custom integrations), consider:

1. **Keep it internal** - Only expose through n8n or a reverse proxy with auth
2. **Add authentication** - Implement API key or OAuth2 at the reverse proxy level
3. **Use firewall rules** - Restrict which IPs can reach the service
4. **Consider HTTPS** - Enable TLS if the service is exposed over the network

For most use cases, the default Docker network isolation provides sufficient security without additional authentication.

## Scope

This security policy applies to:
- The Ghost Narrator codebase
- The TTS Service (Fish Speech integration)
- n8n workflows
- Shell scripts and Docker configurations

This policy does NOT apply to:
- Third-party services (vLLM, ChromaDB, SearXNG, n8n) - see their respective security policies
- External dependencies (Fish Speech, PyTorch, etc.) - report to upstream maintainers