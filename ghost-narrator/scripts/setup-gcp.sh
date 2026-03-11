#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
REGION="${REGION:-us-central1}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-ghost-audio}"
VM_NAME="${VM_NAME:-workos-mvp}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
SA_NAME="ghost-audio-pipeline"
SA_DISPLAY_NAME="Ghost Audio Pipeline SA"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Ghost → Audio Pipeline — GCP Setup             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "Project : ${PROJECT_ID}"
echo "Bucket  : ${BUCKET_NAME}"
echo "VM      : ${VM_NAME} (${VM_ZONE})"
echo ""

echo "▶ Enabling required APIs..."
gcloud services enable \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    compute.googleapis.com \
    --project="${PROJECT_ID}"
echo "  ✓ APIs enabled"

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

echo "▶ Granting Storage Object Admin on gs://${BUCKET_NAME}..."
gsutil iam ch \
    "serviceAccount:${SA_EMAIL}:roles/storage.objectAdmin" \
    "gs://${BUCKET_NAME}"
echo "  ✓ Bucket-level IAM set"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None \
    --quiet
echo "  ✓ Secret Manager accessor granted"

echo "▶ Attaching Service Account to VM ${VM_NAME}..."
gcloud compute instances set-service-account "${VM_NAME}" \
    --zone="${VM_ZONE}" \
    --service-account="${SA_EMAIL}" \
    --scopes="cloud-platform" \
    --project="${PROJECT_ID}"
echo "  ✓ Service account attached to VM"
echo ""
echo "  ⚠  VM may require a restart to pick up the new SA:"
echo "     gcloud compute instances stop  ${VM_NAME} --zone=${VM_ZONE}"
echo "     gcloud compute instances start ${VM_NAME} --zone=${VM_ZONE}"
echo ""

echo "▶ Storing secrets in Secret Manager..."
echo "  (You will be prompted for each value — input is hidden)"
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
store_secret "ghost-audio-n8n-encrypt-key"  "n8n encryption key (openssl rand -hex 32)"
store_secret "ghost-audio-ghost-key-site1"  "Ghost Content API key for Site 1"
store_secret "ghost-audio-ghost-key-site2"  "Ghost Content API key for Site 2"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete ✓                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Restart the VM to activate the new Service Account"
echo "  2. Run ./scripts/init.sh on the VM to start the services"
echo "  3. Configure Ghost webhooks → http://<VM-IP>:5678/webhook/ghost-published"
echo "  4. Import n8n/workflows/ghost-audio-pipeline.json into n8n"
echo "  5. Set n8n variables: GHOST_KEY_SITE1, GHOST_KEY_SITE2"
echo ""
echo "Bucket URL : https://console.cloud.google.com/storage/browser/${BUCKET_NAME}"
echo "SA email   : ${SA_EMAIL}"
