#!/usr/bin/env pwsh
# ═══════════════════════════════════════════════════════════════════════════════
# Ghost Narrator — Audio Backfill Script (PowerShell)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Finds all published Ghost posts that do not yet have an <audio> player
# embedded and triggers the Ghost Narrator n8n pipeline for each one,
# paced with a configurable delay to avoid overloading the TTS service.
#
# Usage:
#   .\scripts\backfill-audio.ps1
#
# Requirements:
#   PowerShell 5.1+ (built into Windows) or PowerShell 7+
# ═══════════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

# ─── Helpers ─────────────────────────────────────────────────────────────────
function Write-Info    { param($msg) Write-Host $msg -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "✓ $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "✗ $msg" -ForegroundColor Red }
function Write-Header  { param($msg) Write-Host "`n$msg" -ForegroundColor White }

# ─── Banner ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host " Ghost Narrator — Audio Backfill" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host ""
Write-Host "Scans your Ghost site(s) for published posts that do not yet have"
Write-Host "an audio player embedded, then triggers the narration pipeline for"
Write-Host "each one sequentially at a pace the TTS service can handle."
Write-Host ""

# ─── Configuration prompts ───────────────────────────────────────────────────
Write-Host "── Pipeline ────────────────────────────────────────────────" -ForegroundColor White
Write-Host ""

$defaultWebhook = "http://34.130.76.88:5678/webhook/ghost-published"
$inputWebhook = Read-Host "n8n webhook URL [$defaultWebhook]"
$N8N_WEBHOOK = if ($inputWebhook) { $inputWebhook } else { $defaultWebhook }

Write-Host ""
Write-Host "── Ghost Sites ─────────────────────────────────────────────" -ForegroundColor White
Write-Host ""

$inputCount = Read-Host "Number of Ghost sites to process [1]"
$SITE_COUNT = if ($inputCount) {
    try { [int]$inputCount }
    catch { Write-Err "Invalid number: '$inputCount' — must be a whole number"; exit 1 }
} else { 1 }

if ($SITE_COUNT -lt 1) {
    Write-Err "Site count must be at least 1"
    exit 1
}

$GhostUrls = @()
$GhostKeys = @()

for ($i = 1; $i -le $SITE_COUNT; $i++) {
    Write-Host ""
    Write-Host "  Site $i" -ForegroundColor White
    $ghostUrl = Read-Host "    Ghost URL (e.g. https://ghost.founderreality.com)"
    if (-not $ghostUrl) {
        Write-Err "Ghost URL cannot be empty"
        exit 1
    }
    $ghostKey = Read-Host "    Content API key"
    if (-not $ghostKey) {
        Write-Err "Content API key cannot be empty"
        exit 1
    }
    $GhostUrls += $ghostUrl.TrimEnd("/")
    $GhostKeys += $ghostKey
}

Write-Host ""
Write-Host "── Pacing ──────────────────────────────────────────────────" -ForegroundColor White
Write-Host ""
Write-Host "  Recommended delays by article length:"
Write-Host "    ~1000 words  →  180s (3 min)"
Write-Host "    ~2000 words  →  300s (5 min)  ← default"
Write-Host "    ~4000 words  →  600s (10 min)"
Write-Host ""
$inputDelay = Read-Host "Delay between jobs in seconds [300]"
$JOB_DELAY = if ($inputDelay) {
    try { [int]$inputDelay }
    catch { Write-Err "Invalid number: '$inputDelay' — must be a whole number"; exit 1 }
} else { 300 }

if ($JOB_DELAY -lt 30) {
    Write-Err "Delay must be at least 30 seconds"
    exit 1
}

Write-Host ""
Write-Host "── Options ─────────────────────────────────────────────────" -ForegroundColor White
Write-Host ""
$inputDryRun = Read-Host "Dry run? List posts that need audio without triggering anything [y/N]"
$DRY_RUN = $inputDryRun -match "^[Yy]$"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host " Scanning posts..." -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White

# ─── Counters ────────────────────────────────────────────────────────────────
$grandTriggered  = 0
$grandAlreadyDone = 0
$grandSkipped    = 0
$grandErrors     = 0

# ─── Helper: fetch all posts from one Ghost site ─────────────────────────────
function Get-AllPosts {
    param([string]$GhostUrl, [string]$GhostKey)

    $allPosts = @()
    $page = 1

    while ($true) {
        $apiUrl  = "$GhostUrl/ghost/api/content/posts/"
        $apiUrl += "?key=$GhostKey"
        $apiUrl += "&fields=id,slug,title,html,plaintext,url,status"
        $apiUrl += "&limit=15&page=$page&filter=status:published"

        try {
            $response = Invoke-RestMethod -Uri $apiUrl -Method Get -TimeoutSec 20
        } catch {
            throw "Failed to fetch posts (page $page): $_"
        }

        $pagePosts = $response.posts
        if (-not $pagePosts -or $pagePosts.Count -eq 0) { break }

        $allPosts += $pagePosts

        $totalPages = if ($null -ne $response.meta.pagination.pages) { $response.meta.pagination.pages } else { 1 }
        $totalPosts = if ($null -ne $response.meta.pagination.total) { $response.meta.pagination.total } else { $allPosts.Count }
        Write-Host "`r  Fetched $($allPosts.Count) / $totalPosts posts..." -NoNewline

        if ($page -ge $totalPages) { break }
        $page++
    }

    Write-Host ""
    return $allPosts
}

# ─── Helper: countdown between jobs ──────────────────────────────────────────
function Start-Countdown {
    param([int]$Seconds)

    $remaining = $Seconds
    while ($remaining -gt 0) {
        $step = [Math]::Min($remaining, 10)
        Write-Host "`r  Next job in: $("{0,3}" -f $remaining)s — monitor at http://34.130.76.88:5678  " -NoNewline
        Start-Sleep -Seconds $step
        $remaining -= $step
    }
    Write-Host "`r$(' ' * 70)`r" -NoNewline
}

# ─── Per-site processing ─────────────────────────────────────────────────────
for ($siteIdx = 0; $siteIdx -lt $GhostUrls.Count; $siteIdx++) {
    $ghostUrl = $GhostUrls[$siteIdx]
    $ghostKey = $GhostKeys[$siteIdx]
    $siteNum  = $siteIdx + 1

    Write-Host ""
    Write-Host "── Site $siteNum`: $ghostUrl ──" -ForegroundColor White
    Write-Host ""

    # Fetch all posts
    Write-Info "Fetching published posts (this may take a moment for large sites)..."

    try {
        $allPosts = Get-AllPosts -GhostUrl $ghostUrl -GhostKey $ghostKey
    } catch {
        Write-Err "Could not fetch posts from $ghostUrl"
        Write-Host "  $_"
        Write-Warn "Skipping this site — verify the URL and Content API key"
        continue
    }

    Write-Success "Found $($allPosts.Count) published posts"

    if ($allPosts.Count -eq 0) { continue }

    # ── Split into has-audio / needs-audio ────────────────────────────────────
    $needsAudio = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -notmatch '<audio[^>]*>'
    })
    $hasAudio = @($allPosts | Where-Object {
        $_.html -ne $null -and $_.html -match '<audio[^>]*>'
    })

    $grandAlreadyDone += $hasAudio.Count

    if ($hasAudio.Count -gt 0) {
        Write-Success "$($hasAudio.Count) posts already have audio — skipping"
    }

    if ($needsAudio.Count -eq 0) {
        Write-Success "All posts have audio. Nothing to do for this site."
        continue
    }

    Write-Warn "$($needsAudio.Count) posts need audio narration"

    $estimatedMin = [Math]::Ceiling(($needsAudio.Count * $JOB_DELAY) / 60)
    Write-Host "  Estimated processing time: ~$estimatedMin minutes"
    Write-Host "  ($($needsAudio.Count) posts × ${JOB_DELAY}s delay between each)"
    Write-Host ""

    # ── List posts to be processed ────────────────────────────────────────────
    Write-Host "Posts queued for narration:" -ForegroundColor White
    $idx = 1
    foreach ($post in $needsAudio) {
        Write-Host "  $idx. $($post.slug)"
        $idx++
    }
    Write-Host ""

    # ── Dry run ───────────────────────────────────────────────────────────────
    if ($DRY_RUN) {
        Write-Warn "Dry run — no jobs triggered for $ghostUrl"
        $grandSkipped += $needsAudio.Count
        continue
    }

    # ── Confirm ───────────────────────────────────────────────────────────────
    $confirm = Read-Host "Trigger all $($needsAudio.Count) jobs for $ghostUrl? [Y/n]"
    if ($confirm -and $confirm -notmatch "^[Yy]$") {
        Write-Warn "Skipped $ghostUrl"
        $grandSkipped += $needsAudio.Count
        continue
    }

    # ── Trigger each post ─────────────────────────────────────────────────────
    $siteTriggered = 0

    foreach ($post in $needsAudio) {
        $siteTriggered++
        $grandTriggered++

        Write-Host ""
        Write-Host "[$siteTriggered/$($needsAudio.Count)] $($post.title)" -ForegroundColor White
        Write-Host "  Slug : $($post.slug)"
        Write-Host "  URL  : $($post.url)"

        # Build the webhook payload — same shape Ghost sends
        $payload = @{
            post = @{
                current = $post
            }
        } | ConvertTo-Json -Depth 10 -Compress

        try {
            $response = Invoke-WebRequest `
                -Uri $N8N_WEBHOOK `
                -Method Post `
                -ContentType "application/json" `
                -Body $payload `
                -TimeoutSec 15 `
                -UseBasicParsing

            Write-Success "Pipeline triggered (HTTP $($response.StatusCode))"
        } catch {
            $statusCode = if ($null -ne $_.Exception.Response.StatusCode.Value__) { $_.Exception.Response.StatusCode.Value__ } else { "000" }
            Write-Err "Webhook returned HTTP $statusCode — job may not have been queued"
            Write-Host "  $_"
            $grandErrors++
        }

        # Countdown to next job (skip after the last one)
        if ($siteTriggered -lt $needsAudio.Count) {
            Start-Countdown -Seconds $JOB_DELAY
        }
    }
}

# ─── Summary ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host " Summary" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host ""
Write-Success "Already had audio  : $grandAlreadyDone"
Write-Success "Jobs triggered     : $grandTriggered"
if ($grandErrors  -gt 0) { Write-Err  "Webhook errors     : $grandErrors" }
if ($grandSkipped -gt 0) { Write-Warn "Skipped (dry run)  : $grandSkipped" }
Write-Host ""

if ($grandTriggered -gt 0) {
    Write-Host "Monitor progress:"
    Write-Host "  n8n executions : http://34.130.76.88:5678"
    Write-Host "  TTS jobs       : http://34.130.76.88:8020/docs"
    Write-Host ""
    if ($grandErrors -gt 0) {
        Write-Warn "$grandErrors job(s) failed to reach the webhook."
        Write-Host "  Re-run this script to retry — posts that already have audio are skipped automatically."
        Write-Host ""
    }
}
