#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Ghost Narrator — Audio Backfill Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Finds all published Ghost posts that do not yet have an <audio> player
# embedded and triggers the Ghost Narrator n8n pipeline for each one,
# paced with a configurable delay to avoid overloading the TTS service.
#
# Usage:
#   bash scripts/backfill-audio.sh
#
# Requirements:
#   curl, jq  →  sudo apt install curl jq  (or: brew install curl jq)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Temp file cleanup ───────────────────────────────────────────────────────
_CLEANUP_FILES=()
_cleanup() { rm -f "${_CLEANUP_FILES[@]}" 2>/dev/null || true; }
trap _cleanup EXIT

# ─── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}$*${NC}"; }
success() { echo -e "${GREEN}✓ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
err()     { echo -e "${RED}✗ $*${NC}"; }

# ─── Dependency check ────────────────────────────────────────────────────────
for dep in curl jq; do
    if ! command -v "$dep" &>/dev/null; then
        err "Required tool not found: $dep"
        echo "  Install with:  sudo apt install $dep   (Linux)"
        echo "             or: brew install $dep        (macOS)"
        exit 1
    fi
done

# ─── Banner ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} Ghost Narrator — Audio Backfill${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Scans your Ghost site(s) for published posts that do not yet have"
echo "an audio player embedded, then triggers the narration pipeline for"
echo "each one sequentially at a pace the TTS service can handle."
echo ""

# ─── Configuration prompts ───────────────────────────────────────────────────
echo -e "${BOLD}── Pipeline ────────────────────────────────────────────────${NC}"
echo ""

read -r -p "n8n webhook URL [http://34.130.76.88:5678/webhook/ghost-published]: " N8N_WEBHOOK
N8N_WEBHOOK="${N8N_WEBHOOK:-http://34.130.76.88:5678/webhook/ghost-published}"

echo ""
echo -e "${BOLD}── Ghost Sites ─────────────────────────────────────────────${NC}"
echo ""
read -r -p "Number of Ghost sites to process [1]: " SITE_COUNT
SITE_COUNT="${SITE_COUNT:-1}"

if ! [[ "$SITE_COUNT" =~ ^[1-9][0-9]*$ ]]; then
    err "Invalid site count: ${SITE_COUNT}"
    exit 1
fi

GHOST_URLS=()
GHOST_KEYS=()

for i in $(seq 1 "$SITE_COUNT"); do
    echo ""
    echo -e "${BOLD}  Site ${i}${NC}"
    read -r -p "    Ghost URL (e.g. https://ghost.founderreality.com): " ghost_url
    if [ -z "$ghost_url" ]; then
        err "Ghost URL cannot be empty"
        exit 1
    fi
    read -r -p "    Content API key: " ghost_key
    if [ -z "$ghost_key" ]; then
        err "Content API key cannot be empty"
        exit 1
    fi
    GHOST_URLS+=("${ghost_url%/}")
    GHOST_KEYS+=("$ghost_key")
done

echo ""
echo -e "${BOLD}── Pacing ──────────────────────────────────────────────────${NC}"
echo ""
echo "  Recommended delays by article length:"
echo "    ~1000 words  →  180s (3 min)"
echo "    ~2000 words  →  300s (5 min)  ← default"
echo "    ~4000 words  →  600s (10 min)"
echo ""
read -r -p "Delay between jobs in seconds [300]: " JOB_DELAY
JOB_DELAY="${JOB_DELAY:-300}"

if ! [[ "$JOB_DELAY" =~ ^[0-9]+$ ]] || [ "$JOB_DELAY" -lt 30 ]; then
    err "Delay must be at least 30 seconds"
    exit 1
fi

echo ""
echo -e "${BOLD}── Options ─────────────────────────────────────────────────${NC}"
echo ""
read -r -p "Dry run? List posts that need audio without triggering anything [y/N]: " DRY_RUN
DRY_RUN="${DRY_RUN:-N}"

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} Scanning posts...${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"

# ─── Counters ────────────────────────────────────────────────────────────────
GRAND_TRIGGERED=0
GRAND_ALREADY_DONE=0
GRAND_SKIPPED=0
GRAND_ERRORS=0

# ─── Per-site processing ─────────────────────────────────────────────────────
for site_idx in "${!GHOST_URLS[@]}"; do
    GHOST_URL="${GHOST_URLS[$site_idx]}"
    GHOST_KEY="${GHOST_KEYS[$site_idx]}"
    SITE_NUM=$((site_idx + 1))

    echo ""
    echo -e "${BOLD}── Site ${SITE_NUM}: ${GHOST_URL} ──${NC}"
    echo ""

    # ── Fetch all published posts (paginated) ────────────────────────────────
    info "Fetching published posts (this may take a moment for large sites)..."

    ALL_POSTS_FILE=$(mktemp)
    _CLEANUP_FILES+=("$ALL_POSTS_FILE")
    echo "[]" > "$ALL_POSTS_FILE"
    PAGE=1
    FETCH_FAILED=false

    while true; do
        API_URL="${GHOST_URL}/ghost/api/content/posts/"
        API_URL+="?key=${GHOST_KEY}"
        API_URL+="&fields=id,slug,title,html,plaintext,url,status"
        API_URL+="&limit=15"
        API_URL+="&page=${PAGE}"
        API_URL+="&filter=status:published"

        RESPONSE=$(curl -sf --max-time 20 "$API_URL" 2>/dev/null) || {
            err "Failed to fetch posts from ${GHOST_URL} (page ${PAGE})"
            echo "  Verify the Ghost URL and Content API key are correct."
            FETCH_FAILED=true
            break
        }

        # Check for API error response
        if echo "$RESPONSE" | jq -e '.errors' &>/dev/null; then
            ERR_MSG=$(echo "$RESPONSE" | jq -r '.errors[0].message // "Unknown error"')
            err "Ghost API error: ${ERR_MSG}"
            FETCH_FAILED=true
            break
        fi

        PAGE_COUNT=$(echo "$RESPONSE" | jq '.posts | length')
        if [ "$PAGE_COUNT" -eq 0 ]; then
            break
        fi

        # Append this page's posts to the accumulated array
        MERGED=$(jq -s '.[0] + .[1]' "$ALL_POSTS_FILE" <(echo "$RESPONSE" | jq '.posts'))
        echo "$MERGED" > "$ALL_POSTS_FILE"

        TOTAL_PAGES=$(echo "$RESPONSE" | jq '.meta.pagination.pages // 1')
        FETCHED_SO_FAR=$(jq 'length' "$ALL_POSTS_FILE")
        TOTAL_POSTS=$(echo "$RESPONSE" | jq '.meta.pagination.total // 0')

        printf "\r  Fetched %d / %d posts..." "$FETCHED_SO_FAR" "$TOTAL_POSTS"

        [ "$PAGE" -ge "$TOTAL_PAGES" ] && break
        PAGE=$((PAGE + 1))
    done
    echo ""

    if [ "$FETCH_FAILED" = true ]; then
        warn "Skipping site ${GHOST_URL} due to fetch error"
        rm -f "$ALL_POSTS_FILE"
        continue
    fi

    TOTAL=$(jq 'length' "$ALL_POSTS_FILE")
    success "Found ${TOTAL} published posts"

    if [ "$TOTAL" -eq 0 ]; then
        rm -f "$ALL_POSTS_FILE"
        continue
    fi

    # ── Separate posts with and without audio ────────────────────────────────
    NEEDS_FILE=$(mktemp)
    _CLEANUP_FILES+=("$NEEDS_FILE")
    jq '[.[] | select(
        .html != null and
        (.html | test("<audio[^>]*>"; "i") | not)
    )]' "$ALL_POSTS_FILE" > "$NEEDS_FILE"

    HAS_COUNT=$(jq '[.[] | select(
        .html != null and
        (.html | test("<audio[^>]*>"; "i"))
    )] | length' "$ALL_POSTS_FILE")
    NEEDS_COUNT=$(jq 'length' "$NEEDS_FILE")

    GRAND_ALREADY_DONE=$((GRAND_ALREADY_DONE + HAS_COUNT))

    if [ "$HAS_COUNT" -gt 0 ]; then
        success "${HAS_COUNT} posts already have audio — skipping"
    fi

    if [ "$NEEDS_COUNT" -eq 0 ]; then
        success "All posts have audio. Nothing to do for this site."
        rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
        continue
    fi

    warn "${NEEDS_COUNT} posts need audio narration"

    ESTIMATED_TOTAL_SEC=$((NEEDS_COUNT * JOB_DELAY))
    ESTIMATED_MIN=$((ESTIMATED_TOTAL_SEC / 60))
    echo "  Estimated processing time: ~${ESTIMATED_MIN} minutes"
    echo "  (${NEEDS_COUNT} posts × ${JOB_DELAY}s delay between each)"
    echo ""

    # ── List all posts that will be processed ────────────────────────────────
    echo -e "${BOLD}Posts queued for narration:${NC}"
    jq -r 'to_entries[] | "  \(.key + 1). \(.value.slug)"' "$NEEDS_FILE"
    echo ""

    # ── Dry run — exit early ─────────────────────────────────────────────────
    if [[ "${DRY_RUN}" =~ ^[Yy]$ ]]; then
        warn "Dry run — no jobs triggered for ${GHOST_URL}"
        GRAND_SKIPPED=$((GRAND_SKIPPED + NEEDS_COUNT))
        rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
        continue
    fi

    # ── Confirm before starting ───────────────────────────────────────────────
    read -r -p "Trigger all ${NEEDS_COUNT} jobs for ${GHOST_URL}? [Y/n]: " CONFIRM
    CONFIRM="${CONFIRM:-Y}"
    if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
        warn "Skipped ${GHOST_URL}"
        GRAND_SKIPPED=$((GRAND_SKIPPED + NEEDS_COUNT))
        rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
        continue
    fi

    # ── Process each post ─────────────────────────────────────────────────────
    SITE_TRIGGERED=0

    while IFS= read -r post; do
        SLUG=$(echo "$post"  | jq -r '.slug')
        TITLE=$(echo "$post" | jq -r '.title')
        POST_URL=$(echo "$post" | jq -r '.url')

        SITE_TRIGGERED=$((SITE_TRIGGERED + 1))
        GRAND_TRIGGERED=$((GRAND_TRIGGERED + 1))

        echo ""
        echo -e "${BOLD}[${SITE_TRIGGERED}/${NEEDS_COUNT}] ${TITLE}${NC}"
        echo "  Slug : ${SLUG}"
        echo "  URL  : ${POST_URL}"

        # Build webhook payload matching the shape Ghost sends
        PAYLOAD=$(echo "$post" | jq -c '{post: {current: .}}')

        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "$N8N_WEBHOOK" \
            -H "Content-Type: application/json" \
            --max-time 15 \
            -d "$PAYLOAD" 2>/dev/null) || HTTP_CODE="000"

        if [[ "$HTTP_CODE" =~ ^2 ]]; then
            success "Pipeline triggered (HTTP ${HTTP_CODE})"
        else
            err "Webhook returned HTTP ${HTTP_CODE} — job may not have been queued"
            GRAND_ERRORS=$((GRAND_ERRORS + 1))
        fi

        # Countdown to next job (skip after the final post)
        if [ "$SITE_TRIGGERED" -lt "$NEEDS_COUNT" ]; then
            REMAINING=$JOB_DELAY
            while [ "$REMAINING" -gt 0 ]; do
                STEP=$(( REMAINING < 10 ? REMAINING : 10 ))
                printf "\r  Next job in: %3ds — monitor at http://34.130.76.88:5678  " "$REMAINING"
                sleep "$STEP"
                REMAINING=$(( REMAINING - STEP ))
            done
            printf "\r%-70s\r" ""
        fi

    done < <(jq -c '.[]' "$NEEDS_FILE")

    rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
done

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} Summary${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo ""
success "Already had audio  : ${GRAND_ALREADY_DONE}"
success "Jobs triggered     : ${GRAND_TRIGGERED}"
[ "$GRAND_ERRORS"  -gt 0 ] && err  "Webhook errors     : ${GRAND_ERRORS}"
[ "$GRAND_SKIPPED" -gt 0 ] && warn "Skipped (dry run)  : ${GRAND_SKIPPED}"
echo ""

if [ "$GRAND_TRIGGERED" -gt 0 ]; then
    echo "Monitor progress:"
    echo "  n8n executions : http://34.130.76.88:5678"
    echo "  TTS jobs       : http://34.130.76.88:8020/docs"
    echo "  TTS logs       : docker logs -f tts-service"
    echo "  n8n logs       : docker logs -f n8n"
    echo ""
    if [ "$GRAND_ERRORS" -gt 0 ]; then
        warn "${GRAND_ERRORS} job(s) failed to reach the webhook."
        echo "  Re-run this script to retry — posts that already have audio are skipped."
        echo ""
    fi
fi
