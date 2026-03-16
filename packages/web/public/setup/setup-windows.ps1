# ============================================================================
# AutoApply — Windows Setup Script
# Downloads, installs, and configures everything needed to run AutoApply worker
# Run in PowerShell as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process; .\setup-windows.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

$RequiredPython = "3.11"
$RequiredNode = "18"
$InstallDir = "$env:USERPROFILE\autoapply"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║       AutoApply — Windows Setup              ║" -ForegroundColor Cyan
    Write-Host "  ║   Automated Job Application Engine           ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step($num, $msg) {
    Write-Host "`n[$num/$script:TotalSteps] $msg" -ForegroundColor White
}

function Write-OK($msg) {
    Write-Host "  ✓ $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "  ⚠ $msg" -ForegroundColor Yellow
}

function Write-Fail($msg) {
    Write-Host "  ✗ $msg" -ForegroundColor Red
}

function Write-Info($msg) {
    Write-Host "  → $msg" -ForegroundColor Cyan
}

function Test-CommandExists($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Install-WithWinget($packageId, $name) {
    if (Test-CommandExists "winget") {
        Write-Info "Installing $name via winget..."
        winget install --id $packageId --accept-package-agreements --accept-source-agreements --silent
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Fail "winget not available. Please install $name manually."
        Write-Host "  Download from the official website and re-run this script." -ForegroundColor Yellow
        return $false
    }
    return $true
}

$script:TotalSteps = 9

# ── Main ─────────────────────────────────────────────────────────────────────

Write-Banner

Write-Host "This script will:" -ForegroundColor White
Write-Host "  1. Check Windows prerequisites (winget)"
Write-Host "  2. Install/verify Python $RequiredPython+"
Write-Host "  3. Install/verify Node.js $RequiredNode+"
Write-Host "  4. Install OpenClaw CLI"
Write-Host "  5. Install Playwright browsers"
Write-Host "  6. Clone AutoApply repository"
Write-Host "  7. Install all dependencies"
Write-Host "  8. Configure environment variables"
Write-Host "  9. Verify the setup"
Write-Host ""
Write-Host "Estimated time: 5-10 minutes" -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to continue (or Ctrl+C to cancel)"

# ── Step 1: Prerequisites ───────────────────────────────────────────────────
Write-Step 1 "Checking Windows prerequisites..."

if (Test-CommandExists "winget") {
    Write-OK "winget available"
} else {
    Write-Warn "winget not found. Trying to install App Installer..."
    try {
        Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe
        Write-OK "winget installed"
    } catch {
        Write-Fail "Could not install winget. Please install App Installer from Microsoft Store."
        Write-Host "  https://apps.microsoft.com/detail/9NBLGGH4NNS1" -ForegroundColor Cyan
        exit 1
    }
}

if (Test-CommandExists "git") {
    Write-OK "Git found: $(git --version)"
} else {
    Install-WithWinget "Git.Git" "Git"
    if (Test-CommandExists "git") {
        Write-OK "Git installed: $(git --version)"
    }
}

# ── Step 2: Python ──────────────────────────────────────────────────────────
Write-Step 2 "Checking Python..."

$PythonCmd = $null
foreach ($cmd in @("python3", "python", "py")) {
    if (Test-CommandExists $cmd) {
        try {
            $ver = & $cmd --version 2>&1 | Select-String -Pattern '\d+\.\d+' | ForEach-Object { $_.Matches[0].Value }
            if ([version]$ver -ge [version]$RequiredPython) {
                $PythonCmd = $cmd
                break
            }
        } catch { continue }
    }
}

if ($PythonCmd) {
    Write-OK "Python found: $(& $PythonCmd --version) ($PythonCmd)"
} else {
    Write-Info "Installing Python via winget..."
    Install-WithWinget "Python.Python.3.12" "Python 3.12"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    foreach ($cmd in @("python3", "python", "py")) {
        if (Test-CommandExists $cmd) {
            $PythonCmd = $cmd
            break
        }
    }

    if ($PythonCmd) {
        Write-OK "Python installed: $(& $PythonCmd --version)"
    } else {
        Write-Fail "Python installation failed. Please install manually from python.org"
        exit 1
    }
}

# Verify pip
try {
    & $PythonCmd -m pip --version | Out-Null
    Write-OK "pip available"
} catch {
    Write-Info "Installing pip..."
    & $PythonCmd -m ensurepip --upgrade
}

# ── Step 3: Node.js ─────────────────────────────────────────────────────────
Write-Step 3 "Checking Node.js..."

if (Test-CommandExists "node") {
    $nodeVer = (node --version) -replace 'v', '' -split '\.' | Select-Object -First 1
    if ([int]$nodeVer -ge $RequiredNode) {
        Write-OK "Node.js found: $(node --version)"
    } else {
        Write-Warn "Node.js v$(node --version) is too old (need v$RequiredNode+)"
        Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS"
    }
} else {
    Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS"
}

# Refresh PATH after install
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

if (Test-CommandExists "node") {
    Write-OK "Node.js: $(node --version)"
    Write-OK "npm: $(npm --version)"
} else {
    Write-Fail "Node.js not found after install. Please install manually from nodejs.org"
}

# ── Step 4: OpenClaw CLI ────────────────────────────────────────────────────
Write-Step 4 "Checking OpenClaw CLI..."

if (Test-CommandExists "openclaw") {
    Write-OK "OpenClaw already installed"
} else {
    Write-Info "Installing OpenClaw CLI..."
    npm install -g openclaw 2>$null
    if (Test-CommandExists "openclaw") {
        Write-OK "OpenClaw installed"
    } else {
        Write-Warn "OpenClaw install failed — you may need to install it manually: npm install -g openclaw"
    }
}

Write-Host ""
Write-Host "  NOTE: OpenClaw Pro subscription (`$20/mo) is required for browser automation." -ForegroundColor Yellow
Write-Host "  Sign up at: https://openclaw.com/pricing" -ForegroundColor Yellow

# ── Step 5: Playwright ──────────────────────────────────────────────────────
Write-Step 5 "Installing Playwright browsers..."

& $PythonCmd -m pip install --quiet playwright 2>$null
& $PythonCmd -m playwright install chromium
Write-OK "Playwright Chromium installed"

# ── Step 6: Clone repo ──────────────────────────────────────────────────────
Write-Step 6 "Setting up AutoApply..."

if (Test-Path $InstallDir) {
    Write-OK "AutoApply directory exists at $InstallDir"
    Set-Location $InstallDir
    if (Test-Path ".git") {
        Write-Info "Pulling latest changes..."
        try { git pull origin main 2>$null } catch { Write-Warn "Git pull failed — using existing files" }
    }
} else {
    Write-Info "Cloning AutoApply..."
    try {
        git clone https://github.com/snehitvaddi/AutoApply.git $InstallDir 2>$null
    } catch {
        Write-Warn "Git clone failed (repo may be private). Creating directory..."
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }
    Set-Location $InstallDir
}

# ── Step 7: Install dependencies ────────────────────────────────────────────
Write-Step 7 "Installing dependencies..."

if (Test-Path "packages/worker/requirements.txt") {
    Write-Info "Installing Python packages..."
    & $PythonCmd -m pip install --quiet -r packages/worker/requirements.txt 2>$null
    Write-OK "Python packages installed"
} else {
    Write-Warn "packages/worker/requirements.txt not found — skipping"
}

if (Test-Path "packages/web/package.json") {
    Write-Info "Installing Node.js packages..."
    Push-Location packages/web
    npm install --silent 2>$null
    Pop-Location
    Write-OK "Node.js packages installed"
} else {
    Write-Warn "packages/web/package.json not found — skipping"
}

# ── Step 8: Environment configuration ───────────────────────────────────────
Write-Step 8 "Configuring environment..."

$EnvFile = Join-Path $InstallDir ".env"

if (Test-Path $EnvFile) {
    Write-OK ".env file already exists"
    Write-Info "To reconfigure, edit: $EnvFile"
} else {
    Write-Host ""
    Write-Host "Enter your configuration (press Enter to skip optional fields):" -ForegroundColor White
    Write-Host ""

    $SupabaseUrl = Read-Host "  Supabase URL (https://xxx.supabase.co)"
    $SupabaseAnon = Read-Host "  Supabase Anon Key"
    $SupabaseService = Read-Host "  Supabase Service Role Key"
    $AppUrl = Read-Host "  App URL [https://autoapply-web.vercel.app]"
    if (-not $AppUrl) { $AppUrl = "https://autoapply-web.vercel.app" }
    $TelegramToken = Read-Host "  Telegram Bot Token (optional)"
    $WorkerId = Read-Host "  Worker ID [worker-1]"
    if (-not $WorkerId) { $WorkerId = "worker-1" }

    # Generate encryption key
    $EncryptionKey = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })

    $envContent = @"
# AutoApply Environment Configuration
# Generated by setup-windows.ps1 on $(Get-Date)

# Supabase
NEXT_PUBLIC_SUPABASE_URL=$SupabaseUrl
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SupabaseAnon
SUPABASE_SERVICE_ROLE_KEY=$SupabaseService
SUPABASE_URL=$SupabaseUrl
SUPABASE_SERVICE_KEY=$SupabaseService

# App
NEXT_PUBLIC_APP_URL=$AppUrl
ENCRYPTION_KEY=$EncryptionKey

# Worker
WORKER_ID=$WorkerId
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=$env:TEMP\autoapply\resumes
SCREENSHOT_DIR=$env:TEMP\autoapply\screenshots

# Telegram (optional)
TELEGRAM_BOT_TOKEN=$TelegramToken

# Stripe (optional)
# STRIPE_SECRET_KEY=
# STRIPE_WEBHOOK_SECRET=
# STRIPE_STARTER_PRICE_ID=
# STRIPE_PRO_PRICE_ID=

# Redis rate limiting (optional)
# UPSTASH_REDIS_REST_URL=
# UPSTASH_REDIS_REST_TOKEN=

# Google OAuth for Gmail (optional)
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
"@

    $envContent | Out-File -FilePath $EnvFile -Encoding UTF8
    Write-OK ".env file created at $EnvFile"
}

# Create worker directories
$resumeDir = Join-Path $env:TEMP "autoapply\resumes"
$screenshotDir = Join-Path $env:TEMP "autoapply\screenshots"
New-Item -ItemType Directory -Path $resumeDir -Force | Out-Null
New-Item -ItemType Directory -Path $screenshotDir -Force | Out-Null
Write-OK "Worker directories created"

# ── Step 9: Verify ──────────────────────────────────────────────────────────
Write-Step 9 "Verifying setup..."

$Pass = 0
$Fail = 0

function Test-Setup($condition, $name) {
    if ($condition) {
        Write-OK $name
        $script:Pass++
    } else {
        Write-Fail $name
        $script:Fail++
    }
}

Test-Setup (Test-CommandExists $PythonCmd) "Python ($(& $PythonCmd --version 2>&1))"
Test-Setup (Test-CommandExists "node") "Node.js ($(node --version 2>&1))"
Test-Setup (Test-CommandExists "npm") "npm ($(npm --version 2>&1))"
Test-Setup (Test-CommandExists "openclaw") "OpenClaw CLI"

try { & $PythonCmd -c "import playwright" 2>$null; $pw = $true } catch { $pw = $false }
Test-Setup $pw "Playwright (Python)"

try { & $PythonCmd -c "import supabase" 2>$null; $sb = $true } catch { $sb = $false }
Test-Setup $sb "Supabase client (Python)"

try { & $PythonCmd -c "import httpx" 2>$null; $hx = $true } catch { $hx = $false }
Test-Setup $hx "httpx (Python)"

Test-Setup (Test-Path $EnvFile) "Environment config (.env)"
Test-Setup (Test-Path $resumeDir) "Worker directories"

Write-Host ""
Write-Host "════════════════════════════════════════════════" -ForegroundColor White
if ($Fail -eq 0) {
    Write-Host "  Setup complete! All $Pass checks passed." -ForegroundColor Green
} else {
    Write-Host "  Setup done with $Fail issue(s). $Pass/$($Pass + $Fail) checks passed." -ForegroundColor Yellow
}
Write-Host "════════════════════════════════════════════════" -ForegroundColor White

Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Start the worker:" -ForegroundColor White
Write-Host "     cd $InstallDir\packages\worker" -ForegroundColor Cyan
Write-Host "     $PythonCmd worker.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. Run the job scanner:" -ForegroundColor Cyan
Write-Host "     cd $InstallDir\packages\worker" -ForegroundColor Cyan
Write-Host "     $PythonCmd -m scanner.run" -ForegroundColor Cyan
Write-Host ""
Write-Host "  3. Start the web app (development):" -ForegroundColor White
Write-Host "     cd $InstallDir\packages\web" -ForegroundColor Cyan
Write-Host "     npm run dev" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Need help? See docs\CLIENT-ONBOARDING.md" -ForegroundColor Yellow
Write-Host ""
