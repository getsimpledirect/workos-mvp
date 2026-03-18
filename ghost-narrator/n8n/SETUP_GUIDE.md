# Ghost Audio Pipeline: n8n Workflow Guide

This guide explains how to import and configure the two n8n workflows that power the Ghost audio narration pipeline.

## Overview of Workflows

The pipeline is split into two asynchronous workflows:

1.  **`ghost-audio-pipeline.json` (The Synthesizer)**
    *   **Trigger:** Triggered when a Ghost post is published (via `ghost-published` webhook).
    *   **Action:** Fetches the article text, rewrites it into a podcast narration script using vLLM (Qwen3-14B), and submits a text-to-speech job to the TTS service.
2.  **`ghost-audio-callback.json` (The Embedder)**
    *   **Trigger:** Triggered by the TTS service when it finishes generating the audio and uploading it to Google Cloud Storage (via `tts-callback` webhook).
    *   **Action:** Receives the GCS audio URL, fetches the original Ghost article HTML, prepends an HTML5 audio player to the top, and updates the live post with the Ghost Admin API.

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

> **Note:** In the `ghost-audio-callback` workflow, the **"Create Ghost JWT"** node may show a red linting error for `require('crypto')`. This is a visual editor quirk; the code will execute correctly as long as the environment is configured as described below.

---

## Step 2: Configure Environment Variables

The workflows are designed to be flexible. You can provide credentials via:
1.  **Docker `.env` file** (Recommended for automation)
2.  **n8n UI Variables** (Go to Settings -> Variables)

The workflow checks the `.env` value first, then falls back to the n8n Variable.

### Required Variables

**Core Services:**
*   `VLLM_BASE_URL`: URL to your vLLM API (e.g., `http://host.docker.internal:8001/v1`).
*   `VLLM_MODEL_NAME`: Model name (e.g., `Qwen/Qwen3-14B`).
*   `TTS_SERVICE_URL`: URL to TTS service (e.g., `http://tts-service:8020`). *Note: This is pre-configured in docker-compose.yml.*

**Ghost Site 1 (founderreality.com):**
*   `GHOST_KEY_SITE1`: **Content API Key** (read-only).
*   `GHOST_SITE1_ADMIN_API_KEY`: **Admin API Key** (for embedding audio).

**Ghost Site 2 (getsimpledirect.com):**
*   `GHOST_KEY_SITE2`: **Content API Key**.
*   `GHOST_SITE2_ADMIN_API_KEY`: **Admin API Key**.

### How to Get Ghost API Keys

**For Each Site:**

1.  Login to Ghost Admin:
    - Site 1: https://ghost.founderreality.com/ghost/
    - Site 2: https://ghost.getsimpledirect.com/ghost/

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

The workflow automatically detects which site by checking the hostname:
- Contains `founderreality` → Uses Site 1 credentials
- Otherwise → Uses Site 2 credentials

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

**You do not need to configure a webhook in Ghost for the second workflow (`tts-callback`).** The TTS service itself automatically triggers the second workflow.

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

---

## Common Issues & Solutions

### "Invalid token" / "INVALID_JWT" Error

**Symptoms:** Callback workflow fails at "Get Post Content" or "Update Post" node with this error.

**Cause:** Ghost Admin API requires JWT tokens, but the token generation failed.

**Solution:**
1. Verify Admin API keys are in `.env` file with correct format: `key_id:hex_secret`
2. Check that both parts are present (split by `:` should give 2 parts)
3. Restart n8n to ensure environment variables are loaded: `docker compose restart n8n`
4. The workflow automatically generates JWT tokens with:
   - Proper header including `kid` (key ID)
   - 5-minute expiry time
   - HMAC-SHA256 signature using hex-decoded secret

---

### "Could not extract post ID from job ID"

**Symptoms:** Callback workflow skips embedding with this reason.

**Cause:** Job ID doesn't contain a valid 24-character hexadecimal post ID.

**Expected Format:**
```
ghost-founderreality-com-69a9a6c97a9d08bae126a199-article-slug
                               ^^^^^^^^^^^^^^^^^^^^^^^^
                               This is the post ID (24 hex chars)
```

**Solution:**
1. Ensure you're testing with a real published article (not a test payload with fake IDs)
2. Check the job ID in the TTS callback matches the format above
3. The post ID must be exactly 24 hexadecimal characters

---

### One Site Works, Other Doesn't

**Symptoms:** Audio embeds on founderreality.com but not on getsimpledirect.com (or vice versa).

**Cause:** Missing or incorrect API key for the non-working site.

**Solution:**
1. Verify `.env` has all 4 keys:
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
     https://ghost.founderreality.com/ghost/api/admin/posts/latest/
   
   # Get a post from Site 2  
   curl -H "Authorization: Ghost YOUR_ADMIN_KEY_SITE2" \
     https://ghost.getsimpledirect.com/ghost/api/admin/posts/latest/
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

1. **Add environment variables:**
   ```env
   GHOST_KEY_SITE3=<Content API Key>
   GHOST_SITE3_ADMIN_API_KEY=<Admin API Key>
   ```

2. **Update workflow detection logic** in both workflows:
   - Find nodes that check `includes('founderreality')`
   - Add additional condition for your third domain
   - Update URL mappings to include your third site's URL

Example:
```javascript
const apiKey = $json.siteSlug.includes('founderreality') 
  ? $env.GHOST_SITE1_ADMIN_API_KEY 
  : $json.siteSlug.includes('getsimpledirect')
    ? $env.GHOST_SITE2_ADMIN_API_KEY
    : $env.GHOST_SITE3_ADMIN_API_KEY;
```
