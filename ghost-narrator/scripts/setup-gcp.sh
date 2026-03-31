#!/usr/bin/env bash
# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

set -euo pipefail

echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Ghost → Audio Pipeline — GCP Setup             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Interactive prompts for configuration ───────────────────────────────────

prompt_value() {
    local var_name="$1"
    local prompt_text="$2"
    local default_value="${3:-}"
    local value=""

    if [ -n "${default_value}" ]; then
        read -r -p "${prompt_text} [${default_value}]: " value
        value="${value:-${default_value}}"
    else
        while [ -z "${value}" ]; do
            read -r -p "${prompt_text}: " value
            if [ -z "${value}" ]; then
                echo "  ✗ This field is required. Please enter a value."
            fi
        done
    fi

    echo "${value}"
}

prompt_secret() {
    local prompt_text="$1"
    local value=""

    while [ -z "${value}" ]; do
        read -r -s -p "${prompt_text}: " value
        echo ""
        if [ -z "${value}" ]; then
            echo "  ✗ This field is required. Please enter a value."
        fi
    done

    echo "${value}"
}

echo "Please provide the following configuration values:"
echo "─────────────────────────────────────────────────────────────"
echo ""

# Required values
PROJECT_ID=$(prompt_value "PROJECT_ID" "GCP Project ID")
REGION=$(prompt_value "REGION" "GCP Region" "us-central1")
BUCKET_NAME=$(prompt_value "BUCKET_NAME" "GCS Bucket Name" "${PROJECT_ID}-ghost-audio")
VM_NAME=$(prompt_value "VM_NAME" "Compute Engine VM Name" "workos-mvp")
VM_ZONE=$(prompt_value "VM_ZONE" "VM Zone" "${REGION}-a")

SA_NAME="ghost-audio-pipeline"
SA_DISPLAY_NAME="Ghost Audio Pipeline SA"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo ""
echo "─────────────────────────────────────────────────────────────"
echo "Configuration Summary:"
echo "─────────────────────────────────────────────────────────────"
echo "  Project ID : ${PROJECT_ID}"
echo "  Region     : ${REGION}"
echo "  Bucket     : ${BUCKET_NAME}"
echo "  VM Name    : ${VM_NAME}"
echo "  VM Zone    : ${VM_ZONE}"
echo "  SA Email   : ${SA_EMAIL}"
echo "─────────────────────────────────────────────────────────────"
echo ""

read -r -p "Proceed with this configuration? [Y/n]: " confirm
confirm="${confirm:-Y}"
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 0
fi

echo ""

# ─── Enable required APIs ────────────────────────────────────────────────────

echo "▶ Enabling required APIs..."
gcloud services enable \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    compute.googleapis.com \
    --project="${PROJECT_ID}"
echo "  ✓ APIs enabled"

# ─── Create GCS bucket ───────────────────────────────────────────────────────

echo "▶ Creating GCS bucket gs://${BUCKET_NAME}..."
if gsutil ls -b "gs://${BUCKET_NAME}" &>/dev/null; then
    echo "  ℹ Bucket already exists — skipping creation"
else
    gsutil mb \
        -p "${PROJECT_ID}" \
        -l "${REGION}" \
        -b on \
        "gs://${BUCKET_NAME}"
    echo "  ✓ Bucket created"
fi

cat > /tmp/lifecycle.json <<'LIFECYCLE'
{
  "lifecycle": {
    "rule": [{
      "action": { "type": "Delete" },
      "condition": {
        "age": 7,
        "matchesPrefix": ["audio/tmp/"]
      }
    }]
  }
}
LIFECYCLE
gsutil lifecycle set /tmp/lifecycle.json "gs://${BUCKET_NAME}"
echo "  ✓ Lifecycle policy set (tmp/ deleted after 7 days)"

# ─── Create Service Account ──────────────────────────────────────────────────

echo "▶ Creating Service Account ${SA_EMAIL}..."
if gcloud iam service-accounts describe "${SA_EMAIL}" \
        --project="${PROJECT_ID}" &>/dev/null; then
    echo "  ℹ Service account already exists — skipping"
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="${SA_DISPLAY_NAME}" \
        --project="${PROJECT_ID}"
    echo "  ✓ Service account created"
fi

# ─── Grant IAM permissions ───────────────────────────────────────────────────

echo "▶ Granting Storage Object Admin on gs://${BUCKET_NAME}..."
gsutil iam ch \
    "serviceAccount:${SA_EMAIL}:roles/storage.objectAdmin" \
    "gs://${BUCKET_NAME}"
echo "  ✓ Bucket-level IAM set"

echo "▶ Making bucket objects publicly readable..."
gsutil iam ch allUsers:objectViewer "gs://${BUCKET_NAME}"
echo "  ✓ Bucket is now public (read-only)"

# ─── Set CORS configuration ──────────────────────────────────────────────────

cat > /tmp/cors.json <<'CORS'
[
  {
    "origin": ["*"],
    "method": ["GET"],
    "responseHeader": ["Content-Type"],
    "maxAgeSeconds": 3600
  }
]
CORS
echo "▶ Setting CORS policy on gs://${BUCKET_NAME}..."
gsutil cors set /tmp/cors.json "gs://${BUCKET_NAME}"
echo "  ✓ CORS policy set"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet
echo "  ✓ Secret Manager accessor granted"

# ─── Attach Service Account to VM ────────────────────────────────────────────

echo "▶ Checking VM ${VM_NAME} status..."

# Check if VM exists
if ! gcloud compute instances describe "${VM_NAME}" \
        --zone="${VM_ZONE}" \
        --project="${PROJECT_ID}" &>/dev/null; then
    echo "  ⚠ VM ${VM_NAME} not found in zone ${VM_ZONE}"
    echo "  Skipping service account attachment."
    echo "  You can manually attach the service account later when the VM exists."
else
    # Get VM status
    VM_STATUS=$(gcloud compute instances describe "${VM_NAME}" \
        --zone="${VM_ZONE}" \
        --project="${PROJECT_ID}" \
        --format="value(status)")

    echo "  VM Status: ${VM_STATUS}"

    if [ "${VM_STATUS}" = "RUNNING" ]; then
        echo ""
        echo "  ⚠ The VM must be stopped to change its service account."
        read -r -p "  Stop the VM, attach service account, and restart? [Y/n]: " stop_confirm
        stop_confirm="${stop_confirm:-Y}"

        if [[ "${stop_confirm}" =~ ^[Yy]$ ]]; then
            echo "  ▶ Stopping VM ${VM_NAME}..."
            gcloud compute instances stop "${VM_NAME}" \
                --zone="${VM_ZONE}" \
                --project="${PROJECT_ID}" \
                --quiet
            echo "  ✓ VM stopped"

            echo "  ▶ Attaching Service Account to VM..."
            gcloud compute instances set-service-account "${VM_NAME}" \
                --zone="${VM_ZONE}" \
                --service-account="${SA_EMAIL}" \
                --scopes="cloud-platform" \
                --project="${PROJECT_ID}"
            echo "  ✓ Service account attached"

            echo "  ▶ Starting VM ${VM_NAME}..."
            gcloud compute instances start "${VM_NAME}" \
                --zone="${VM_ZONE}" \
                --project="${PROJECT_ID}" \
                --quiet
            echo "  ✓ VM started"
        else
            echo "  Skipping service account attachment."
            echo "  You can manually attach it later by running:"
            echo ""
            echo "    gcloud compute instances stop ${VM_NAME} --zone=${VM_ZONE} --project=${PROJECT_ID}"
            echo "    gcloud compute instances set-service-account ${VM_NAME} \\"
            echo "        --zone=${VM_ZONE} \\"
            echo "        --service-account=${SA_EMAIL} \\"
            echo "        --scopes=cloud-platform \\"
            echo "        --project=${PROJECT_ID}"
            echo "    gcloud compute instances start ${VM_NAME} --zone=${VM_ZONE} --project=${PROJECT_ID}"
        fi
    elif [ "${VM_STATUS}" = "TERMINATED" ] || [ "${VM_STATUS}" = "STOPPED" ]; then
        echo "  ▶ Attaching Service Account to VM ${VM_NAME}..."
        gcloud compute instances set-service-account "${VM_NAME}" \
            --zone="${VM_ZONE}" \
            --service-account="${SA_EMAIL}" \
            --scopes="cloud-platform" \
            --project="${PROJECT_ID}"
        echo "  ✓ Service account attached"

        read -r -p "  Start the VM now? [Y/n]: " start_confirm
        start_confirm="${start_confirm:-Y}"
        if [[ "${start_confirm}" =~ ^[Yy]$ ]]; then
            echo "  ▶ Starting VM ${VM_NAME}..."
            gcloud compute instances start "${VM_NAME}" \
                --zone="${VM_ZONE}" \
                --project="${PROJECT_ID}" \
                --quiet
            echo "  ✓ VM started"
        fi
    else
        echo "  ⚠ VM is in state '${VM_STATUS}'. Cannot attach service account now."
        echo "  Please wait for the VM to reach a stable state and try again."
    fi
fi

echo ""

# ─── Store secrets in Secret Manager ─────────────────────────────────────────

echo "▶ Storing secrets in Secret Manager..."
echo "  (Input is hidden for security)"
echo ""

store_secret() {
    local secret_name="$1"
    local prompt="$2"

    if gcloud secrets describe "${secret_name}" \
            --project="${PROJECT_ID}" &>/dev/null; then
        read -r -s -p "  Update ${prompt} (leave blank to keep existing): " secret_val
        echo ""
        if [ -n "${secret_val}" ]; then
            echo -n "${secret_val}" | gcloud secrets versions add "${secret_name}" \
                --data-file=- \
                --project="${PROJECT_ID}"
            echo "  ✓ ${secret_name} updated"
        else
            echo "  ℹ ${secret_name} unchanged"
        fi
    else
        read -r -s -p "  Enter ${prompt}: " secret_val
        echo ""
        if [ -z "${secret_val}" ]; then
            echo "  ⚠ Skipping ${secret_name} (no value provided)"
            return
        fi
        gcloud secrets create "${secret_name}" \
            --replication-policy="automatic" \
            --project="${PROJECT_ID}"
        echo -n "${secret_val}" | gcloud secrets versions add "${secret_name}" \
            --data-file=- \
            --project="${PROJECT_ID}"
        echo "  ✓ ${secret_name} created"
    fi
}

store_secret "ghost-audio-n8n-password"     "n8n admin password"
store_secret "ghost-audio-n8n-encrypt-key"  "n8n encryption key (run: openssl rand -hex 32)"
store_secret "ghost-audio-ghost-url-site1"  "Ghost URL for Site 1 (e.g., https://ghost.site1.com)"
store_secret "ghost-audio-ghost-url-site2"  "Ghost URL for Site 2 (e.g., https://ghost.site2.com)"
store_secret "ghost-audio-ghost-key-site1"  "Ghost Content API key for Site 1"
store_secret "ghost-audio-ghost-key-site2"  "Ghost Content API key for Site 2"
store_secret "ghost-audio-ghost-admin-key-site1" "Ghost Admin API key for Site 1"
store_secret "ghost-audio-ghost-admin-key-site2" "Ghost Admin API key for Site 2"
store_secret "searxng-secret" "SearXNG secret key (run: openssl rand -hex 32)"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete ✓                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration used:"
echo "  Project  : ${PROJECT_ID}"
echo "  Bucket   : gs://${BUCKET_NAME}"
echo "  VM       : ${VM_NAME} (${VM_ZONE})"
echo "  SA Email : ${SA_EMAIL}"
echo ""
echo "Next steps:"
echo "  1. SSH into the VM: gcloud compute ssh ${VM_NAME} --zone=${VM_ZONE} --project=${PROJECT_ID}"
echo "  2. Run ./scripts/init.sh on the VM to start the services"
echo "  3. Configure Ghost webhooks → http://<VM-IP>:5678/webhook/ghost-published"
echo "  4. Import n8n/workflows/ghost-audio-pipeline.json into n8n"
echo "  5. Set n8n variables: GHOST_KEY_SITE1, GHOST_KEY_SITE2"
echo ""
echo "Useful links:"
echo "  Bucket   : https://console.cloud.google.com/storage/browser/${BUCKET_NAME}"
echo "  Secrets  : https://console.cloud.google.com/security/secret-manager?project=${PROJECT_ID}"
echo "  VM       : https://console.cloud.google.com/compute/instances?project=${PROJECT_ID}"
echo ""
