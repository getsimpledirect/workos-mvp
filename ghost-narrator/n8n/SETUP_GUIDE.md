# Ghost Audio Pipeline: n8n Workflow Guide

This guide explains how to import and configure the two n8n workflows that power the Ghost audio narration pipeline.

## Overview of Workflows

The pipeline is split into two asynchronous workflows:

1.  **`ghost-audio-pipeline.json` (The Synthesizer)**
    *   **Trigger:** Triggered when a Ghost post is published (via `ghost-article` webhook).
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

---

## Step 2: Configure Environment Variables in n8n

The workflows rely on several environment variables defined in your `docker-compose.yml` to securely authenticate with Ghost and the TTS API without hardcoding secrets in the JSON files.

Ensure these variables are set in the `.env` file that powers your Docker Compose stack running n8n:

*   `VLLM_BASE_URL`: The URL to your vLLM API (e.g., `http://host.docker.internal:8001/v1`).
*   `VLLM_MODEL_NAME`: The model name (e.g., `Qwen/Qwen3-14B`).
*   `TTS_SERVICE_URL`: The URL to your TTS service (e.g., `http://tts-service:8020`).
*   `GHOST_KEY_SITE1`: The **Content API Key** for your first Ghost site (e.g., founderreality).
*   `GHOST_KEY_SITE2`: The **Content API Key** for your second Ghost site.
*   `GHOST_SITE1_ADMIN_API_KEY`: The **Admin API Key** for your first Ghost site (required for embedding audio).
*   `GHOST_SITE2_ADMIN_API_KEY`: The **Admin API Key** for your second Ghost site.

*Note: The workflows check the string `founderreality` in the URL to determine which site's API keys to use. If your domains differ significantly, you may need to update the JavaScript in the `"Fetch Full Article"`, `"Get Latest Post Content"`, and `"Update Ghost Post"` nodes.*

---

## Step 3: Configure Ghost Webhooks

For **each** of your Ghost websites, you must tell them to alert n8n when an article is published.

1.  Go to **Ghost Admin** → **Settings** → **Integrations**.
2.  Click on the Custom Integration you created for this pipeline (or Add a new one).
3.  Scroll down to **Webhooks** and click **Add webhook**.
4.  **Name:** `Audio Pipeline Trigger`
5.  **Event:** Select `Post published`.
6.  **Target URL:** Enter the Webhook URL from your *first* workflow.
    *   It will look something like: `http://YOUR_VM_IP:5678/webhook/ghost-article`
7.  Save the integration.

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
