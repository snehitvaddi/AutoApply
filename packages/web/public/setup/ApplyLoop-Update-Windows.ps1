# ============================================================================
# ApplyLoop — Windows Auto-Update Script
# Pulls latest code, updates dependencies, and restarts worker if running.
# Runs daily via Task Scheduler (installed by setup-windows.ps1) or manually.
# ============================================================================

param(
    [string]$Mode = ""  # --check = only run if stale, --quiet = no banner
)

$InstallDir = "$env:USERPROFILE\autoapply"
$LogDir = Join-Path $InstallDir "logs"
$LogFile = Join-Path $LogDir "update-$(Get-Date -Format 'yyyy-MM-dd').log"
$EnvFile = Join-Path $InstallDir ".env"
$LockFile = Join-Path $env:TEMP "autoapply-update.lock"
$LastUpdateFile = Join-Path $InstallDir ".last-update"
$UpdateIntervalDays = 5

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# ── Logging ─────────────────────────────────────────────────────────────────

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Log-OK($msg)   { Write-Log "[OK]   $msg" }
function Log-Warn($msg) { Write-Log "[WARN] $msg" }
function Log-Fail($msg) { Write-Log "[FAIL] $msg" }
function Log-Info($msg) { Write-Log "[-->]  $msg" }

# ── Check if update is needed ──────────────────────────────────────────────

function Test-NeedsUpdate {
    if (-not (Test-Path $LastUpdateFile)) { return $true }
    $lastTs = Get-Content $LastUpdateFile -ErrorAction SilentlyContinue
    if (-not $lastTs) { return $true }
    $lastDate = [DateTimeOffset]::FromUnixTimeSeconds([long]$lastTs).LocalDateTime
    $daysSince = ((Get-Date) - $lastDate).Days
    return ($daysSince -ge $UpdateIntervalDays)
}

# If called with --check, only run if stale (for login triggers)
if ($Mode -eq "--check") {
    if (-not (Test-NeedsUpdate)) {
        exit 0
    }
}

# ── Visual Banner ──────────────────────────────────────────────────────────

if ($Mode -ne "--quiet") {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║        ApplyLoop - Checking for updates...       ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan

    if (Test-Path $LastUpdateFile) {
        $lastTs = Get-Content $LastUpdateFile -ErrorAction SilentlyContinue
        if ($lastTs) {
            $lastDate = [DateTimeOffset]::FromUnixTimeSeconds([long]$lastTs).LocalDateTime
            $daysAgo = ((Get-Date) - $lastDate).Days
            if ($daysAgo -gt 0) {
                Write-Host "  Last updated: $daysAgo day(s) ago" -ForegroundColor Yellow
            } else {
                Write-Host "  Last updated: today" -ForegroundColor Green
            }
        }
    } else {
        Write-Host "  First update check" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ── Lock (prevent concurrent updates) ──────────────────────────────────────

if (Test-Path $LockFile) {
    $lockPid = Get-Content $LockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) {
        Log-Warn "Update already running (PID $lockPid). Skipping."
        exit 0
    } else {
        Remove-Item $LockFile -Force
    }
}
$PID | Out-File -FilePath $LockFile -Force
try {

# ── Start ───────────────────────────────────────────────────────────────────

Write-Log ""
Write-Log "==================================================="
Write-Log "ApplyLoop Auto-Update - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Log "==================================================="

if (-not (Test-Path $InstallDir)) {
    Log-Fail "ApplyLoop not found at $InstallDir. Run setup first."
    exit 1
}

Set-Location $InstallDir

# Detect Python
$PythonCmd = $null
foreach ($cmd in @("python3", "python", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $PythonCmd = $cmd
        break
    }
}

# ── Step 0: Check remote update API ───────────────────────────────────────

$ApiUrl = "https://applyloop.vercel.app/api/updates/check"
$MigrationNeeded = $false

Log-Info "Checking ApplyLoop update server..."
try {
    $apiResp = Invoke-RestMethod -Uri $ApiUrl -UseBasicParsing -TimeoutSec 10 -ErrorAction SilentlyContinue
    $remoteVersion = $apiResp.version
    $remoteCommit = $apiResp.latest_commit
    $MigrationNeeded = [bool]$apiResp.migration_needed

    Log-OK "Remote version: $remoteVersion (commit: $remoteCommit)"

    # Read local version
    $localVersion = "unknown"
    $pkgPath = Join-Path $InstallDir "packages\web\package.json"
    if (Test-Path $pkgPath) {
        $pkgJson = Get-Content $pkgPath -Raw | ConvertFrom-Json
        $localVersion = $pkgJson.version
    }
    Log-Info "Local version: $localVersion"

    if ($apiResp.changes) {
        Log-Info "What's new:"
        foreach ($change in $apiResp.changes) {
            Write-Log "    - $change"
        }
    }

    if ($MigrationNeeded) {
        Log-Warn "Database migration needed after this update"
    }
} catch {
    Log-Warn "Could not reach update server - continuing with git pull"
}

# ── Step 1: Pull latest code ────────────────────────────────────────────────

Log-Info "Checking for updates..."
$UpdatesPulled = $false

if (Test-Path ".git") {
    # Stash local changes
    $localChanges = (git status --porcelain 2>$null | Where-Object { $_ -notmatch "^\?\?" }).Count
    $stashed = $false
    if ($localChanges -gt 0) {
        Log-Info "Stashing $localChanges local change(s)..."
        git stash --quiet 2>$null
        $stashed = $true
    }

    # Fetch and compare
    git fetch origin main --quiet 2>$null
    $localHash = git rev-parse HEAD 2>$null
    $remoteHash = git rev-parse origin/main 2>$null

    if ($localHash -eq $remoteHash) {
        Log-OK "Already up to date ($($localHash.Substring(0,7)))"
    } else {
        $behind = (git rev-list HEAD..origin/main --count 2>$null)
        Log-Info "Pulling $behind new commit(s)..."

        $ErrorActionPreference = "Continue"
        git pull origin main --quiet 2>$null
        $ErrorActionPreference = "Stop"

        $newHash = git rev-parse HEAD 2>$null
        if ($newHash -ne $localHash) {
            Log-OK "Updated: $($localHash.Substring(0,7)) -> $($newHash.Substring(0,7))"
            $UpdatesPulled = $true

            # Show what changed
            Log-Info "Changes:"
            git log --oneline "${localHash}..HEAD" 2>$null | ForEach-Object {
                Write-Log "    $_"
            }
        } else {
            Log-Fail "Git pull failed"
        }
    }

    # Restore local changes
    if ($stashed) {
        git stash pop --quiet 2>$null
        Log-Info "Restored local changes"
    }
} else {
    Log-Warn "Not a git repo - skipping code update"
}

# ── Step 2: Update dependencies (only if code changed) ──────────────────────

if ($UpdatesPulled) {
    $ErrorActionPreference = "Continue"

    # Python dependencies
    if ($PythonCmd -and (Test-Path "packages\worker\requirements.txt")) {
        Log-Info "Updating Python packages..."
        & $PythonCmd -m pip install --quiet --upgrade -r packages\worker\requirements.txt 2>&1 | Out-Null
        Log-OK "Python packages updated"
    }

    # LLM SDKs
    if (Test-Path $EnvFile) {
        $llmProv = (Select-String -Path $EnvFile -Pattern "^LLM_PROVIDER=(.+)$" -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.Matches[0].Groups[1].Value })
        $llmBack = (Select-String -Path $EnvFile -Pattern "^LLM_BACKEND_PROVIDER=(.+)$" -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.Matches[0].Groups[1].Value })

        if ($llmProv -eq "anthropic" -or $llmBack -eq "anthropic") {
            & $PythonCmd -m pip install --quiet --upgrade anthropic 2>&1 | Out-Null
        }
        if ($llmProv -eq "openai" -or $llmBack -eq "openai") {
            & $PythonCmd -m pip install --quiet --upgrade openai 2>&1 | Out-Null
        }
        if ($llmProv -eq "google" -or $llmBack -eq "google") {
            & $PythonCmd -m pip install --quiet --upgrade google-generativeai 2>&1 | Out-Null
        }
    }

    # Node.js dependencies
    if ((Test-Path "packages\web\package.json") -and (Get-Command npm -ErrorAction SilentlyContinue)) {
        Log-Info "Updating Node.js packages..."
        Push-Location packages\web
        npm install --silent 2>&1 | Out-Null
        Pop-Location
        Log-OK "Node.js packages updated"
    }

    # OpenClaw CLI
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Log-Info "Updating OpenClaw CLI..."
        npm update -g openclaw 2>&1 | Out-Null
        Log-OK "OpenClaw CLI updated"
    }

    # Run migration if needed
    if ($MigrationNeeded) {
        Log-Info "Running database migration..."
        $migScript = Join-Path $InstallDir "packages\web\public\setup\run-migration.py"
        if ($PythonCmd -and (Test-Path $migScript) -and (Test-Path $EnvFile)) {
            & $PythonCmd $migScript $EnvFile 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Log-OK "Database migration complete"
            } else {
                Log-Warn "Migration failed - run manually from Supabase SQL Editor"
            }
        } else {
            Log-Warn "Migration script or .env not found - skipping"
        }
    }

    # Ollama model update
    if (Test-Path $EnvFile) {
        if ($llmProv -eq "ollama" -or $llmBack -eq "ollama") {
            if (Get-Command ollama -ErrorAction SilentlyContinue) {
                $ollamaModel = (Select-String -Path $EnvFile -Pattern "^LLM_MODEL=(.+)$" -ErrorAction SilentlyContinue |
                                ForEach-Object { $_.Matches[0].Groups[1].Value })
                if ($ollamaModel) {
                    Log-Info "Updating Ollama model $ollamaModel..."
                    ollama pull $ollamaModel 2>&1 | Out-Null
                }
            }
        }
    }

    $ErrorActionPreference = "Stop"
} else {
    Log-Info "No code changes - skipping dependency updates"
}

# ── Step 3: Restart worker if running ───────────────────────────────────────

$workerProc = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
              Where-Object { $_.CommandLine -match "worker\.py" } |
              Select-Object -First 1

if ($workerProc -and $UpdatesPulled) {
    Log-Info "Restarting worker (PID $($workerProc.Id))..."
    Stop-Process -Id $workerProc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Restart worker in background
    if ($PythonCmd -and (Test-Path "packages\worker\worker.py")) {
        $workerLog = Join-Path $LogDir "worker.log"
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $PythonCmd
        $startInfo.Arguments = "worker.py"
        $startInfo.WorkingDirectory = Join-Path $InstallDir "packages\worker"
        $startInfo.UseShellExecute = $false
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $newProc = [System.Diagnostics.Process]::Start($startInfo)
        Log-OK "Worker restarted (PID $($newProc.Id))"
    }
} elseif ($workerProc) {
    Log-OK "Worker running (PID $($workerProc.Id)) - no restart needed"
} else {
    Log-Info "Worker not running - skipping restart"
}

# ── Step 4: Health check ────────────────────────────────────────────────────

Log-Info "Running health check..."

$HealthPass = 0
$HealthFail = 0

function Check-Health($condition, $name) {
    if ($condition) {
        Log-OK $name
        $script:HealthPass++
    } else {
        Log-Fail $name
        $script:HealthFail++
    }
}

Check-Health (Test-Path $EnvFile) ".env exists"
Check-Health (Test-Path "packages\worker") "Worker code present"

if ($PythonCmd) {
    try { & $PythonCmd -c "import playwright" 2>$null; $pw = $true } catch { $pw = $false }
    Check-Health $pw "Playwright installed"

    try { & $PythonCmd -c "import supabase" 2>$null; $sb = $true } catch { $sb = $false }
    Check-Health $sb "Supabase SDK installed"
}

Check-Health ([bool](Get-Command openclaw -ErrorAction SilentlyContinue)) "OpenClaw CLI available"

# Supabase connectivity
if (Test-Path $EnvFile) {
    $sbUrl = (Select-String -Path $EnvFile -Pattern "^NEXT_PUBLIC_SUPABASE_URL=(.+)$" -ErrorAction SilentlyContinue |
              ForEach-Object { $_.Matches[0].Groups[1].Value })
    if ($sbUrl) {
        try {
            $resp = Invoke-WebRequest -Uri "${sbUrl}/rest/v1/" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
            Check-Health ($resp.StatusCode -lt 400) "Supabase API reachable"
        } catch {
            Check-Health $false "Supabase API reachable"
        }
    }
}

# ── Summary ─────────────────────────────────────────────────────────────────

Write-Log ""
Write-Log "==================================================="
if ($UpdatesPulled) {
    Write-Log "Update complete. Health: $HealthPass passed, $HealthFail failed."
} else {
    Write-Log "No updates available. Health: $HealthPass passed, $HealthFail failed."
}
Write-Log "==================================================="
Write-Log "Log saved to: $LogFile"

# Save last-update timestamp
[long]((Get-Date) - (Get-Date "1970-01-01")).TotalSeconds | Out-File -FilePath $LastUpdateFile -Force

# Show completion banner
if ($Mode -ne "--quiet") {
    Write-Host ""
    if ($UpdatesPulled) {
        Write-Host "  [OK] ApplyLoop updated successfully!" -ForegroundColor Green
    } else {
        Write-Host "  [OK] ApplyLoop is up to date." -ForegroundColor Green
    }
    Write-Host "  Next check: in $UpdateIntervalDays days or on next login" -ForegroundColor Cyan
    Write-Host ""
}

# ── Install applyloop-update function in PowerShell profile ────────────────

$profilePath = $PROFILE.CurrentUserCurrentHost
if ($profilePath) {
    $profileDir = Split-Path $profilePath -Parent
    if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }
    if (-not (Test-Path $profilePath)) { New-Item -ItemType File -Path $profilePath -Force | Out-Null }

    $funcLine = "function applyloop-update { powershell -ExecutionPolicy Bypass -File `"$($InstallDir)\update.ps1`" }"
    if (-not (Select-String -Path $profilePath -Pattern "applyloop-update" -Quiet -ErrorAction SilentlyContinue)) {
        Add-Content -Path $profilePath -Value "`n# ApplyLoop update command`n$funcLine"
        Log-OK "Added 'applyloop-update' command to PowerShell profile"
    }
}

# Cleanup old logs (keep 30 days)
Get-ChildItem -Path $LogDir -Filter "update-*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

} finally {
    # Release lock
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
