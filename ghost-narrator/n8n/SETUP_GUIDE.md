# Ghost Audio Pipeline: n8n Workflow Guide

This guide explains how to import and configure the three n8n workflows that power the Ghost audio narration pipeline.

## Overview of Workflows

The pipeline is split into asynchronous workflows:

1.  **`ghost-audio-pipeline.json` (The Synthesizer)**
    *   **Trigger:** Triggered when a Ghost post is published or updated (via `ghost-published` webhook).
    *   **Action:** Fetches the article text, rewrites it into a podcast narration script using vLLM (Qwen3-14B), and submits a text-to-speech job to the TTS service.
2.  **`ghost-audio-callback.json` (The Embedder)**
    *   **Trigger:** Triggered by the TTS service when it finishes generating the audio and uploading it to Google Cloud Storage (via `tts-callback` webhook).
    *   **Action:** Receives the GCS audio URL, fetches the original Ghost article HTML, prepends an HTML5 audio player to the top, and updates the live post with the Ghost Admin API.
3.  **`static-content-audio-pipeline.json` (The Static Synthesizer)**
    *   **Trigger:** Triggered manually or programmatically via the `static-content-audio` webhook.
    *   **Action:** Accepts pre-extracted plain text (for books, series pages, or non-Ghost content), rewrites it via vLLM, and submits a TTS job with a custom GCS output path. The TTS callback then handles uploading directly — no Ghost embed step.

---

## Step 1: Import the Workflows

1.  Open your n8n UI (e.g., `http://YOUR_VM_IP:5678`) and log in.
2.  Click **Workflows** in the left sidebar.
3.  Click the **Add Workflow** button (or **+**).
4.  Opening the top-right menu (the `...` or settings gear depending on n8n version), select **Import from File**.
5.  Select `ghost-audio-pipeline.json` from the `n8n/workflows/` directory.
6.  Ensure no nodes show red errors. Save the workflow.
7.  Activate the workflow using the toggle in the top right.
8.  Repeat steps 3-7 for `ghost-audio-callback.json`.
9.  Optionally, repeat for `static-content-audio-pipeline.json` if you need to generate audio for static/non-Ghost content.

> **Note:** In the `ghost-audio-callback` workflow, the **"Create Ghost JWT"** node may show a red linting error for `require('crypto')`. This is a visual editor quirk — the code executes correctly because docker-compose sets `NODE_FUNCTION_ALLOW_BUILTIN=crypto` in the n8n container.

---

## Step 2: Configure Environment Variables

### n8n Docker Prerequisites

The following settings are pre-configured in `docker-compose.yml` and are required for the workflows to function. You do not need to set them manually — just be aware of why they exist:

| Variable | Value | Why it's needed |
|---|---|---|
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `false` | Allows workflow code nodes to read `$env.*` variables |
| `NODE_FUNCTION_ALLOW_BUILTIN` | `crypto` | Required for JWT token generation in the callback workflow |
| `N8N_PAYLOAD_SIZE_MAX` | `50` (MB) | Raises the default 16MB limit for large articles |
| `N8N_CONCURRENCY_PRODUCTION_LIMIT` | `10` | Caps concurrent workflow executions |

### Credentials: Two Approaches

You can provide Ghost API keys via either approach — both are supported:

**Option A — Docker `.env` file (recommended):**
Add keys to your `.env` file. They are passed into the n8n container as environment variables and read via `$env.*` in workflow code nodes.

**Option B — n8n UI Variables:**
Go to **Settings → Variables** in the n8n UI and add them there. The workflows fall back to this if the `.env` variable is empty.

> The workflows check `$env.*` first, then fall back to `$vars.*`. If you stored keys in n8n Variables during initial setup, they will continue to work even if `.env` is missing those keys.

### Required Variables

**Core Services:**
*   `VLLM_BASE_URL`: URL to your vLLM API. Match this to your actual vLLM server — the path matters:
    - If vLLM serves at the root: `http://host.docker.internal:8001`
    - If vLLM serves under `/v1`: `http://host.docker.internal:8001/v1`
*   `VLLM_MODEL_NAME`: Model name (e.g., `Qwen/Qwen3-14B`).
*   `TTS_SERVICE_URL`: URL to TTS service (e.g., `http://tts-service:8020`). *Pre-configured in docker-compose.yml.*

**Ghost Site 1:**
*   `GHOST_KEY_SITE1`: **Content API Key** (read-only, used to fetch article text).
*   `GHOST_SITE1_ADMIN_API_KEY`: **Admin API Key** (used to embed the audio player).

**Ghost Site 2:**
*   `GHOST_KEY_SITE2`: **Content API Key**.
*   `GHOST_SITE2_ADMIN_API_KEY`: **Admin API Key**.

### How to Get Ghost API Keys

**For Each Site:**

1.  Login to Ghost Admin:
    - Site 1: https://ghost.your-site-1.com/ghost/
    - Site 2: https://ghost.your-site-2.com/ghost/

2.  Go to **Settings** → **Integrations**

3.  Click **+ Add custom integration**

4.  Name it: `n8n Audio Pipeline`

5.  Copy **both** keys:
    - **Content API Key** → Use for `GHOST_KEY_SITE1` or `GHOST_KEY_SITE2`
    - **Admin API Key** → Use for `GHOST_SITE1_ADMIN_API_KEY` or `GHOST_SITE2_ADMIN_API_KEY`

⚠️ **CRITICAL: Admin API Key Format**

The Admin API key MUST be in this exact format:
```
key_id:secret
```

Example: `a7b8c9d0e1f2g3h4i5j6k7l8m9n0o1p2:q3r4s5t6u7v8w9x0y1z2a3b4c5d6e7f8...`

**DO NOT**:
- ❌ Use only the secret part (without the key_id)
- ❌ Add spaces around the colon
- ❌ Include extra characters or newlines

**The workflow WILL FAIL with "Invalid token" error if the format is wrong.**

### Multi-Site Detection

The workflow automatically detects which Ghost site to use by matching the post's URL hostname against your configured `GHOST_SITE1_URL` and `GHOST_SITE2_URL` environment variables.

**How it works:**
1. Extract the hostname from the incoming webhook's post URL (e.g., `ghost.mysite.com`)
2. Compare against the hostnames derived from `GHOST_SITE1_URL` and `GHOST_SITE2_URL`
3. Automatically select the matching site's credentials

**Required configuration in `.env`:**
```env
GHOST_SITE1_URL=https://ghost.site1.com
GHOST_SITE2_URL=https://ghost.site2.com
GHOST_KEY_SITE1=<content-api-key-1>
GHOST_KEY_SITE2=<content-api-key-2>
GHOST_SITE1_ADMIN_API_KEY=<admin-key-1>
GHOST_SITE2_ADMIN_API_KEY=<admin-key-2>
```

No manual adjustment needed - just configure your URLs!

---

## Step 3: Configure Ghost Webhooks

For **each** of your Ghost websites, you must tell them to alert n8n when an article is published or updated.

1.  Go to **Ghost Admin** → **Settings** → **Integrations**.
2.  Click on the Custom Integration you created for this pipeline (or Add a new one).
3.  Scroll down to **Webhooks** and click **Add webhook**.
4.  **Name:** `Audio Pipeline Trigger - Published`
5.  **Event:** Select `Post published`.
6.  **Target URL:** Enter the Webhook URL from your *first* workflow.
    *   It will look something like: `http://YOUR_VM_IP:5678/webhook/ghost-published`
7.  Save the integration.
8.  Click **Add webhook** again.
9.  **Name:** `Audio Pipeline Trigger - Updated`
10. **Event:** Select `Post updated`.
11. **Target URL:** Enter the EXACT SAME Webhook URL as above.
12. Save the integration.

**You do not need to configure a webhook in Ghost for the second workflow (`tts-callback`).** The TTS service itself automatically triggers the second workflow via `http://n8n:5678/webhook/tts-callback` (pre-configured in docker-compose.yml).

---

## Step 4: Testing the End-to-End Pipeline

To test the entire flow:

1.  Create a new post in Ghost with a few paragraphs of text.
2.  Publish the post.
3.  Open n8n and go to **Executions** (in the left sidebar).
4.  You should see an execution log for **Ghost Article → Audio Pipeline**. Wait for it to show `Success`.
5.  Wait around 30 to 60 seconds (depending on article length and TTS generation time).

    **Typical Processing Times:**
    - CPU mode (4 workers): ~50-60 seconds for 2000-word article
    - CPU mode (8 workers): ~30-40 seconds for 2000-word article
    - GPU mode: ~20-30 seconds for 2000-word article

6.  Refresh the Executions page. You should now see a new execution for **Ghost Audio Callback & Embed** showing `Success`.
7.  Refresh your live Ghost article. You should see an audio controls widget at the top of the post!

### Troubleshooting Executions

If the audio isn't appearing:
*   Check the n8n **Executions** tab. If either workflow failed, click into the execution log to see exactly which node failed and the error message (e.g., `401 Unauthorized` means your Ghost API keys are incorrect or missing).
*   Check the TTS service logs (`docker compose logs tts-service`) to ensure it successfully synthesized the audio and uploaded it to GCS. If the TTS service failed, it might not send the callback, or it will send a callback with `status: failed` (which the second workflow is configured to ignore).
*   HTTP requests in the workflow have built-in retry logic: Ghost content fetches retry 3 times (5s apart), TTS job submissions retry 3 times (10s apart). A failure shown in Executions means all retries were exhausted.

---

## Common Issues & Solutions

### "Invalid token" / "INVALID_JWT" Error

**Symptoms:** Callback workflow fails at "Get Post Content" or "Update Post" node with this error.

**Cause:** Ghost Admin API requires JWT tokens, but the token generation failed.

**Solution:**
1. Verify Admin API keys are set (in `.env` or n8n Variables) with correct format: `key_id:hex_secret`
2. Check that both parts are present (split by `:` should give 2 parts)
3. Restart n8n to ensure environment variables are loaded: `docker compose restart n8n`
4. The workflow automatically generates JWT tokens with:
   - Proper header including `kid` (key ID)
   - 5-minute expiry time
   - HMAC-SHA256 signature using hex-decoded secret

---

### "Could not extract post ID from job ID"

**Symptoms:** Callback workflow skips embedding with this reason.

**Cause:** Job ID doesn't contain a recognizable post ID.

**Expected Format:**
```
{siteSlug}-pid-{postId}-{slug}-{timestamp}
```

Example:
```
site1-com-pid-69a9a6c97a9d08bae126a199-my-article-title-1234567890
                        ^^^^^^^^^^^^^^^^^^^^^^^^
                        This is the post ID (24 hex chars)
```

**Solution:**
1. Ensure you're testing with a real published article (not a test payload with fake IDs)
2. Check the job ID in the TTS callback matches the format above
3. The post ID must be exactly 24 hexadecimal characters

---

### One Site Works, Other Doesn't

**Symptoms:** Audio embeds on site1.com but not on site2.com (or vice versa).

**Cause:** Missing or incorrect API key for the non-working site.

**Solution:**
1. Verify all 4 keys are set (in `.env` or n8n Variables):
   ```env
   GHOST_KEY_SITE1=<Content API Key for Site 1>
   GHOST_SITE1_ADMIN_API_KEY=<Admin API Key for Site 1>
   GHOST_KEY_SITE2=<Content API Key for Site 2>
   GHOST_SITE2_ADMIN_API_KEY=<Admin API Key for Site 2>
   ```
2. Test each site's Admin API key independently:
   ```bash
   # Get a post from Site 1
   curl -H "Authorization: Ghost YOUR_ADMIN_KEY_SITE1" \
     https://ghost.your-site-1.com/ghost/api/admin/posts/latest/

   # Get a post from Site 2
   curl -H "Authorization: Ghost YOUR_ADMIN_KEY_SITE2" \
     https://ghost.your-site-2.com/ghost/api/admin/posts/latest/
   ```
3. Both should return JSON with post data. If one fails, regenerate that site's Admin API key.

---

### "403 Forbidden" Error

**Symptoms:** Workflow fails when trying to fetch or update post.

**Cause:** Using Content API key instead of Admin API key, or key lacks permissions.

**Solution:**
- Content API keys (read-only) cannot update posts
- You MUST use Admin API keys for embedding audio
- Admin API keys are longer and include both `key_id:secret`
- Regenerate the Admin API key in Ghost Admin → Settings → Integrations

---

### Adding a Third Site

To support additional Ghost sites:

1. **Add environment variables** (in `.env` or n8n Variables):
   ```env
   GHOST_KEY_SITE3=<Content API Key>
   GHOST_SITE3_ADMIN_API_KEY=<Admin API Key>
   GHOST_SITE3_URL=https://ghost.yoursite.com
   ```

2. **Update workflow detection logic** in both `ghost-audio-pipeline.json` and `ghost-audio-callback.json`:
    - Add additional conditions for your third domain using the same hostname matching pattern
    - Update URL mappings to include your third site's URL

Example (for adding Site 3):
```javascript
const postHostname = new URL(postUrl).hostname;
const site3Url = $env.GHOST_SITE3_URL || '';
const site3Hostname = site3Url ? new URL(site3Url).hostname : '';
const isSite3 = postHostname.includes(site3Hostname);

const adminApiKey = isSite1 ? adminApiKey1 : isSite2 ? adminApiKey2 : isSite3 ? adminApiKey3 : null;
const ghostUrl = isSite1 ? site1Url : isSite2 ? site2Url : isSite3 ? site3Url : null;
```

Then add these to your `.env`:
```env
GHOST_SITE3_URL=https://ghost.site3.com
GHOST_KEY_SITE3=<content-api-key-3>
GHOST_SITE3_ADMIN_API_KEY=<admin-key-3>
```

---

### Using the Static Content Workflow

To generate audio for content that isn't a Ghost post (e.g., book chapters, series pages):

**POST** `http://YOUR_VM_IP:5678/webhook/static-content-audio`

```json
{
  "plain_text": "The full article text goes here...",
  "job_id": "my-book-chapter-1",
  "gcs_path": "audio/books/my-book/chapter-1.wav",
  "chapter_title": "Chapter 1: Introduction"
}
```

- `plain_text` must be at least 50 words
- `gcs_path` controls where the output audio is stored in GCS
- `chapter_title` is optional — used in the LLM narration prompt only, not sent to the TTS service
- The TTS callback will fire when complete, but no Ghost embed step runs — the audio is simply uploaded to the specified GCS path
