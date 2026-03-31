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

# ═══════════════════════════════════════════════════════════════════════════════
# Ghost Narrator — Audio Backfill Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Finds all published Ghost posts that do not yet have an <audio> player
# embedded and triggers the Ghost Narrator n8n pipeline for each one,
# polling the TTS service for job completion before moving to the next article.
#
# Usage:
#   bash scripts/backfill-audio.sh              # interactive foreground run
#   bash scripts/backfill-audio.sh --background # collect inputs, then run in background
#   bash scripts/backfill-audio.sh --status     # show background run status + log tail
#   bash scripts/backfill-audio.sh --logs       # live-tail the background log
#   bash scripts/backfill-audio.sh --stop       # stop a running background job
#
# Requirements:
#   curl, jq  →  sudo apt install curl jq  (or: brew install curl jq)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─── Paths & constants ───────────────────────────────────────────────────────
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
PID_FILE="/tmp/ghost-backfill.pid"
LOG_FILE="/tmp/ghost-backfill.log"
POLL_INTERVAL=15    # seconds between TTS status polls
N8N_TIMEOUT=600     # seconds to wait for n8n to submit TTS job (covers LLM rewrite time)
MAX_WAIT=1800       # seconds max per article before giving up (30 min)

# ─── Temp file cleanup ───────────────────────────────────────────────────────
_CLEANUP_FILES=()
_cleanup() { rm -f "${_CLEANUP_FILES[@]}" 2>/dev/null || true; }
trap _cleanup EXIT

# ─── Colours & helpers ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}$*${NC}"; }
success() { echo -e "${GREEN}✓ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
err()     { echo -e "${RED}✗ $*${NC}"; }

# ═══════════════════════════════════════════════════════════════════════════════
# SUBCOMMANDS  (--status / --logs / --stop / --config)
# ═══════════════════════════════════════════════════════════════════════════════

if [ "${1:-}" = "--status" ]; then
    echo ""
    echo -e "${BOLD}── Ghost Backfill Status ───────────────────────────────────${NC}"
    echo ""
    if [ -f "$PID_FILE" ]; then
        BG_PID=$(cat "$PID_FILE")
        if kill -0 "$BG_PID" 2>/dev/null; then
            success "Running  (PID $BG_PID)"
        else
            warn "Process $BG_PID is no longer running"
            rm -f "$PID_FILE"
        fi
    else
        info "No background backfill is currently running"
    fi
    echo ""
    if [ -f "$LOG_FILE" ]; then
        echo -e "${BOLD}── Last 25 log lines ($LOG_FILE) ───────────────────────────${NC}"
        echo ""
        tail -25 "$LOG_FILE"
    else
        info "No log file found at $LOG_FILE"
    fi
    echo ""
    exit 0
fi

if [ "${1:-}" = "--logs" ]; then
    if [ ! -f "$LOG_FILE" ]; then
        err "No log file found at $LOG_FILE"
        exit 1
    fi
    echo -e "${BOLD}Tailing $LOG_FILE — press Ctrl+C to stop${NC}"
    echo ""
    tail -f "$LOG_FILE"
    exit 0
fi

if [ "${1:-}" = "--stop" ]; then
    if [ ! -f "$PID_FILE" ]; then
        warn "No background backfill PID file found at $PID_FILE"
        exit 0
    fi
    BG_PID=$(cat "$PID_FILE")
    if kill -0 "$BG_PID" 2>/dev/null; then
        kill -- -"$BG_PID" 2>/dev/null || kill "$BG_PID"
        rm -f "$PID_FILE"
        success "Stopped background backfill (PID $BG_PID)"
    else
        warn "Process $BG_PID is not running"
        rm -f "$PID_FILE"
    fi
    exit 0
fi

# ─── Config-file mode (used internally by background re-invocation) ──────────
BACKGROUND=false
CONFIG_FILE=""

if [ "${1:-}" = "--config" ]; then
    CONFIG_FILE="${2:-}"
    if [ ! -f "$CONFIG_FILE" ]; then
        err "Config file not found: $CONFIG_FILE"
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
    # Rebuild arrays from indexed variables
    GHOST_URLS=(); GHOST_KEYS=()
    for i in $(seq 0 $((BACKFILL_SITE_COUNT - 1))); do
        url_var="BACKFILL_GHOST_URL_${i}"
        key_var="BACKFILL_GHOST_KEY_${i}"
        GHOST_URLS+=("${!url_var}")
        GHOST_KEYS+=("${!key_var}")
    done
    SITE_COUNT="$BACKFILL_SITE_COUNT"
    N8N_WEBHOOK="$BACKFILL_N8N_WEBHOOK"
    TTS_SERVICE_URL="$BACKFILL_TTS_SERVICE_URL"
    DRY_RUN="$BACKFILL_DRY_RUN"
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} Ghost Narrator — Audio Backfill (background)${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo ""
fi

# ─── Dependency check ────────────────────────────────────────────────────────
for dep in curl jq; do
    if ! command -v "$dep" &>/dev/null; then
        err "Required tool not found: $dep"
        echo "  Install with:  sudo apt install $dep   (Linux)"
        echo "             or: brew install $dep        (macOS)"
        exit 1
    fi
done

# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE CONFIGURATION  (skipped in --config mode)
# ═══════════════════════════════════════════════════════════════════════════════

if [ "${1:-}" != "--config" ]; then

    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD} Ghost Narrator — Audio Backfill${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Scans your Ghost site(s) for published posts that do not yet have"
    echo "an audio player embedded, then triggers the narration pipeline for"
    echo "each one, polling the TTS service for completion before proceeding."
    echo ""

    echo -e "${BOLD}── Pipeline ────────────────────────────────────────────────${NC}"
    echo ""

    _default_webhook="http://localhost:5678/webhook/ghost-published"
    read -r -p "n8n webhook URL [$_default_webhook]: " _input
    N8N_WEBHOOK="${_input:-$_default_webhook}"

    echo ""
    _default_tts="http://localhost:8020"
    read -r -p "TTS service URL [$_default_tts]: " _input
    TTS_SERVICE_URL="${_input:-$_default_tts}"

    echo ""
    echo -e "${BOLD}── Ghost Sites ─────────────────────────────────────────────${NC}"
    echo ""
    read -r -p "Number of Ghost sites to process [1]: " _input
    SITE_COUNT="${_input:-1}"

    if ! [[ "$SITE_COUNT" =~ ^[1-9][0-9]*$ ]]; then
        err "Invalid site count: ${SITE_COUNT}"
        exit 1
    fi

    GHOST_URLS=(); GHOST_KEYS=()
    for i in $(seq 1 "$SITE_COUNT"); do
        echo ""
        echo -e "${BOLD}  Site ${i}${NC}"
        read -r -p "    Ghost URL (e.g. https://ghost.your-site.com): " ghost_url
        if [ -z "$ghost_url" ]; then err "Ghost URL cannot be empty"; exit 1; fi
        read -r -p "    Content API key: " ghost_key
        if [ -z "$ghost_key" ]; then err "Content API key cannot be empty"; exit 1; fi
        GHOST_URLS+=("${ghost_url%/}")
        GHOST_KEYS+=("$ghost_key")
    done

    echo ""
    echo -e "${BOLD}── Options ─────────────────────────────────────────────────${NC}"
    echo ""
    read -r -p "Dry run? List posts that need audio without triggering anything [y/N]: " _input
    DRY_RUN="${_input:-N}"

    echo ""
    read -r -p "Run in background? Frees your terminal while processing continues [y/N]: " _input
    if [[ "${_input:-N}" =~ ^[Yy]$ ]]; then
        BACKGROUND=true
    fi

fi  # end interactive block

# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════

if [ "$BACKGROUND" = true ]; then
    # Check if a backfill is already running
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        err "A background backfill is already running (PID $(cat "$PID_FILE"))"
        echo "  Run:  bash $0 --status   to check it"
        echo "  Run:  bash $0 --stop     to stop it"
        exit 1
    fi

    # Write config file for re-invocation
    CFG_FILE=$(mktemp /tmp/ghost-backfill-cfg-XXXXXX.sh)
    _CLEANUP_FILES+=("$CFG_FILE")
    {
        echo "BACKFILL_N8N_WEBHOOK=$(printf '%q' "$N8N_WEBHOOK")"
        echo "BACKFILL_TTS_SERVICE_URL=$(printf '%q' "$TTS_SERVICE_URL")"
        echo "BACKFILL_SITE_COUNT=$SITE_COUNT"
        echo "BACKFILL_DRY_RUN=$(printf '%q' "$DRY_RUN")"
        for i in "${!GHOST_URLS[@]}"; do
            echo "BACKFILL_GHOST_URL_${i}=$(printf '%q' "${GHOST_URLS[$i]}")"
            echo "BACKFILL_GHOST_KEY_${i}=$(printf '%q' "${GHOST_KEYS[$i]}")"
        done
    } > "$CFG_FILE"

    # Launch in background in its own process group so --stop can kill all children
    echo "" > "$LOG_FILE"
    if command -v setsid &>/dev/null; then
        setsid bash "$SCRIPT_PATH" --config "$CFG_FILE" >> "$LOG_FILE" 2>&1 &
    else
        nohup bash "$SCRIPT_PATH" --config "$CFG_FILE" >> "$LOG_FILE" 2>&1 &
    fi
    BG_PID=$!
    echo "$BG_PID" > "$PID_FILE"
    # Prevent EXIT trap from deleting CFG_FILE — the background process needs it
    _CLEANUP_FILES=()

    echo ""
    success "Backfill started in background (PID $BG_PID)"
    echo ""
    echo "  Log file : $LOG_FILE"
    echo ""
    echo "  Check status : bash $0 --status"
    echo "  Live logs    : bash $0 --logs"
    echo "  Stop         : bash $0 --stop"
    echo ""
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

# Fetch all published posts from a Ghost site (paginated)
get_all_posts() {
    local ghost_url="$1" ghost_key="$2"
    local all_posts_file="$3"
    local page=1

    echo "[]" > "$all_posts_file"

    while true; do
        local api_url="${ghost_url}/ghost/api/content/posts/"
        api_url+="?key=${ghost_key}"
        api_url+="&fields=id,slug,title,html,plaintext,url,status"
        api_url+="&limit=15&page=${page}&filter=status:published"

        local response
        response=$(curl -sf --max-time 20 "$api_url" 2>/dev/null) || {
            err "Failed to fetch posts from ${ghost_url} (page ${page})"
            return 1
        }

        if echo "$response" | jq -e '.errors' &>/dev/null; then
            local err_msg
            err_msg=$(echo "$response" | jq -r '.errors[0].message // "Unknown error"')
            err "Ghost API error: ${err_msg}"
            return 1
        fi

        local page_count
        page_count=$(echo "$response" | jq '.posts | length')
        [ "$page_count" -eq 0 ] && break

        local merged
        merged=$(jq -s '.[0] + .[1]' "$all_posts_file" <(echo "$response" | jq '.posts'))
        echo "$merged" > "$all_posts_file"

        local total_pages total_posts fetched
        total_pages=$(echo "$response" | jq '.meta.pagination.pages // 1')
        total_posts=$(echo "$response" | jq '.meta.pagination.total // 0')
        fetched=$(jq 'length' "$all_posts_file")
        printf "\r  Fetched %d / %d posts..." "$fetched" "$total_posts"

        [ "$page" -ge "$total_pages" ] && break
        page=$((page + 1))
    done
    echo ""
}

# Poll TTS service until job completes, fails, or times out
# Returns 0 on success, 1 on failure/timeout
poll_tts_job() {
    local job_id="$1"
    local elapsed=0
    local phase="waiting_for_n8n"  # waiting_for_n8n → tts_active → done

    while [ $elapsed -lt $MAX_WAIT ]; do
        local http_code status_json status_val
        http_code=$(curl -s -o /tmp/ghost-backfill-poll.tmp \
            -w "%{http_code}" \
            --max-time 10 \
            "${TTS_SERVICE_URL}/tts/status/${job_id}" 2>/dev/null) || http_code="000"

        if [ "$http_code" = "404" ]; then
            if [ $elapsed -ge $N8N_TIMEOUT ]; then
                echo ""
                err "n8n did not submit TTS job within ${N8N_TIMEOUT}s — LLM or pipeline may have failed"
                err "Check n8n executions at: ${N8N_WEBHOOK%/webhook/*}"
                return 1
            fi
            printf "\r  ⏳ LLM rewrite in progress... (%ds elapsed, waiting up to %ds)   " \
                "$elapsed" "$N8N_TIMEOUT"

        elif [ "$http_code" = "200" ]; then
            status_json=$(cat /tmp/ghost-backfill-poll.tmp 2>/dev/null)
            status_val=$(echo "$status_json" | jq -r '.status // "unknown"' 2>/dev/null)
            phase="tts_active"

            case "$status_val" in
                "queued")
                    printf "\r  ⏳ TTS job queued, waiting for worker... (%ds elapsed)   " "$elapsed"
                    ;;
                "processing")
                    printf "\r  🎙  TTS synthesis in progress... (%ds elapsed)   " "$elapsed"
                    ;;
                "completed")
                    printf "\r%-70s\r" ""
                    success "TTS job completed in ${elapsed}s"
                    rm -f /tmp/ghost-backfill-poll.tmp
                    return 0
                    ;;
                "failed")
                    echo ""
                    local fail_reason
                    fail_reason=$(echo "$status_json" | jq -r '.error // "unknown error"' 2>/dev/null)
                    err "TTS job failed: ${fail_reason}"
                    rm -f /tmp/ghost-backfill-poll.tmp
                    return 1
                    ;;
                "paused")
                    printf "\r  ⏸  TTS job is paused (%ds elapsed)...   " "$elapsed"
                    ;;
                *)
                    printf "\r  ? Unknown TTS status: %s (%ds elapsed)   " "$status_val" "$elapsed"
                    ;;
            esac
        else
            printf "\r  ⚠ TTS service returned HTTP %s (%ds elapsed)...   " "$http_code" "$elapsed"
        fi

        sleep $POLL_INTERVAL
        elapsed=$((elapsed + POLL_INTERVAL))
    done

    echo ""
    err "Timed out waiting for TTS job after ${MAX_WAIT}s"
    rm -f /tmp/ghost-backfill-poll.tmp
    return 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} Scanning posts...${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"

GRAND_TRIGGERED=0
GRAND_ALREADY_DONE=0
GRAND_SKIPPED=0
GRAND_ERRORS=0

for site_idx in "${!GHOST_URLS[@]}"; do
    GHOST_URL="${GHOST_URLS[$site_idx]}"
    GHOST_KEY="${GHOST_KEYS[$site_idx]}"
    SITE_NUM=$((site_idx + 1))

    # Derive site slug from URL hostname (dots → hyphens)
    SITE_HOSTNAME=$(echo "$GHOST_URL" | sed 's|https\?://||' | sed 's|/.*||')
    SITE_SLUG=$(echo "$SITE_HOSTNAME" | tr '.' '-')

    echo ""
    echo -e "${BOLD}── Site ${SITE_NUM}: ${GHOST_URL} ──${NC}"
    echo ""

    info "Fetching published posts (this may take a moment for large sites)..."

    ALL_POSTS_FILE=$(mktemp)
    _CLEANUP_FILES+=("$ALL_POSTS_FILE")

    if ! get_all_posts "$GHOST_URL" "$GHOST_KEY" "$ALL_POSTS_FILE"; then
        warn "Skipping site ${GHOST_URL} due to fetch error"
        continue
    fi

    TOTAL=$(jq 'length' "$ALL_POSTS_FILE")
    success "Found ${TOTAL} published posts"
    [ "$TOTAL" -eq 0 ] && continue

    # ── Split into has-audio / needs-audio ────────────────────────────────────
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
    [ "$HAS_COUNT" -gt 0 ] && success "${HAS_COUNT} posts already have audio — skipping"

    if [ "$NEEDS_COUNT" -eq 0 ]; then
        success "All posts have audio. Nothing to do for this site."
        rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
        continue
    fi

    warn "${NEEDS_COUNT} posts need audio narration"
    echo ""

    # ── List posts to be processed ────────────────────────────────────────────
    echo -e "${BOLD}Posts queued for narration:${NC}"
    jq -r 'to_entries[] | "  \(.key + 1). \(.value.slug)"' "$NEEDS_FILE"
    echo ""

    # ── Dry run ───────────────────────────────────────────────────────────────
    if [[ "${DRY_RUN}" =~ ^[Yy]$ ]]; then
        warn "Dry run — no jobs triggered for ${GHOST_URL}"
        GRAND_SKIPPED=$((GRAND_SKIPPED + NEEDS_COUNT))
        rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
        continue
    fi

    # ── Confirm (only in interactive foreground mode) ─────────────────────────
    if [ "${1:-}" != "--config" ]; then
        read -r -p "Trigger all ${NEEDS_COUNT} jobs for ${GHOST_URL}? [Y/n]: " CONFIRM
        CONFIRM="${CONFIRM:-Y}"
        if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
            warn "Skipped ${GHOST_URL}"
            GRAND_SKIPPED=$((GRAND_SKIPPED + NEEDS_COUNT))
            rm -f "$ALL_POSTS_FILE" "$NEEDS_FILE"
            continue
        fi
    fi

    # ── Process each post ─────────────────────────────────────────────────────
    SITE_TRIGGERED=0

    while IFS= read -r post; do
        SLUG=$(echo "$post"  | jq -r '.slug')
        TITLE=$(echo "$post" | jq -r '.title')
        POST_URL=$(echo "$post" | jq -r '.url')
        POST_ID=$(echo "$post" | jq -r '.id')

        SITE_TRIGGERED=$((SITE_TRIGGERED + 1))
        GRAND_TRIGGERED=$((GRAND_TRIGGERED + 1))

        # Construct deterministic job_id using the backfill prefix
        # Format: backfill-{siteSlug}-pid-{postId}-{slug}
        # The -pid- separator is required for the n8n callback workflow to extract postId
        JOB_ID="backfill-${SITE_SLUG}-pid-${POST_ID}-${SLUG}"

        echo ""
        echo -e "${BOLD}[${SITE_TRIGGERED}/${NEEDS_COUNT}] ${TITLE}${NC}"
        echo "  Slug   : ${SLUG}"
        echo "  URL    : ${POST_URL}"
        echo "  Job ID : ${JOB_ID}"

        # Build webhook payload — same shape Ghost sends, with backfill_job_id hint
        PAYLOAD=$(echo "$post" | jq -c \
            --arg job_id "$JOB_ID" \
            '{post: {current: .}, backfill_job_id: $job_id}')

        # Trigger n8n webhook
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "$N8N_WEBHOOK" \
            -H "Content-Type: application/json" \
            --max-time 15 \
            -d "$PAYLOAD" 2>/dev/null) || HTTP_CODE="000"

        if [[ "$HTTP_CODE" =~ ^2 ]]; then
            success "Pipeline triggered (HTTP ${HTTP_CODE})"
        else
            err "Webhook returned HTTP ${HTTP_CODE} — skipping poll for this post"
            GRAND_ERRORS=$((GRAND_ERRORS + 1))
            continue
        fi

        # Poll TTS service until complete
        if poll_tts_job "$JOB_ID"; then
            : # success already printed
        else
            GRAND_ERRORS=$((GRAND_ERRORS + 1))
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
[ "$GRAND_ERRORS"  -gt 0 ] && err  "Errors             : ${GRAND_ERRORS}"
[ "$GRAND_SKIPPED" -gt 0 ] && warn "Skipped (dry run)  : ${GRAND_SKIPPED}"
echo ""

if [ "$GRAND_TRIGGERED" -gt 0 ]; then
    echo "Monitor:"
    echo "  n8n executions : ${N8N_WEBHOOK%/webhook/*}"
    echo "  TTS jobs       : ${TTS_SERVICE_URL}/docs"
    echo "  TTS logs       : docker logs -f tts-service"
    echo "  n8n logs       : docker logs -f n8n"
    echo ""
    if [ "$GRAND_ERRORS" -gt 0 ]; then
        warn "${GRAND_ERRORS} job(s) failed. Re-run to retry — posts that already have audio are skipped automatically."
        echo ""
    fi
fi

# Clean up PID file if we were the background process
[ -f "$PID_FILE" ] && [ "$(cat "$PID_FILE" 2>/dev/null)" = "$$" ] && rm -f "$PID_FILE"
