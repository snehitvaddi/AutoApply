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

$script:TotalSteps = 10

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
Write-Host "  9. Configure LLM providers (Claude / OpenAI / Local)"
Write-Host "  10. Verify the setup"
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
    $ErrorActionPreference = "Continue"
    npm install -g openclaw 2>&1 | Where-Object { $_ -notmatch "npm warn" } | Write-Host
    $ErrorActionPreference = "Stop"
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

# ── Step 9: LLM Configuration ──────────────────────────────────────────────
Write-Step 9 "Configuring LLM providers..."

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor White
Write-Host "║              LLM CONFIGURATION                              ║" -ForegroundColor White
Write-Host "╠══════════════════════════════════════════════════════════════╣" -ForegroundColor White
Write-Host "║  AutoApply uses LLMs at two levels:                         ║" -ForegroundColor White
Write-Host "║                                                             ║" -ForegroundColor White
Write-Host "║  Level 1: USER-FACING (Chat & AI Profile Import)            ║" -ForegroundColor Cyan
Write-Host "║    -> Powers the chat thread where users interact           ║" -ForegroundColor Cyan
Write-Host "║    -> Extracts profile data from conversations              ║" -ForegroundColor Cyan
Write-Host "║    -> Visible to the end user                               ║" -ForegroundColor Cyan
Write-Host "║                                                             ║" -ForegroundColor White
Write-Host "║  Level 2: BACKEND (Server-side Automation)                  ║" -ForegroundColor Cyan
Write-Host "║    -> Powers smart form filling & resume tailoring          ║" -ForegroundColor Cyan
Write-Host "║    -> Runs behind OpenClaw browser automation               ║" -ForegroundColor Cyan
Write-Host "║    -> Not visible to the end user                           ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor White
Write-Host ""

# --- Level 1: User-Facing LLM ---
Write-Host "--- Level 1: User-Facing LLM ---" -ForegroundColor White
Write-Host ""
Write-Host "  Which LLM provider for the USER-FACING chat?" -ForegroundColor White
Write-Host ""
Write-Host "    1. Claude (Anthropic)        - Best for reasoning & safety"
Write-Host "    2. GPT (OpenAI)              - Most popular, broad support"
Write-Host "    3. Gemini (Google)           - Good multimodal support"
Write-Host "    4. Local/Ollama              - Free, private, runs locally"
Write-Host "    5. None (keep manual copy-paste)"
Write-Host ""

$LlmL1Choice = Read-Host "  Enter choice [1-5] (default: 1)"
if (-not $LlmL1Choice) { $LlmL1Choice = "1" }

$LlmProvider = ""
$LlmModel = ""
$LlmApiKeyName = ""
$LlmApiKey = ""

switch ($LlmL1Choice) {
    "1" {
        $LlmProvider = "anthropic"
        Write-Host ""
        Write-Host "  Select Claude model:" -ForegroundColor White
        Write-Host "    1. claude-sonnet-4-6         - Fast, cost-effective (recommended)"
        Write-Host "    2. claude-opus-4-6           - Most capable, higher cost"
        Write-Host "    3. claude-haiku-4-5          - Fastest, lowest cost"
        Write-Host ""
        $ClaudeModel = Read-Host "  Enter choice [1-3] (default: 1)"
        if (-not $ClaudeModel) { $ClaudeModel = "1" }
        switch ($ClaudeModel) {
            "2" { $LlmModel = "claude-opus-4-6" }
            "3" { $LlmModel = "claude-haiku-4-5-20251001" }
            default { $LlmModel = "claude-sonnet-4-6" }
        }
        $LlmApiKeyName = "ANTHROPIC_API_KEY"
        Write-Host ""
        $LlmApiKey = Read-Host "  Anthropic API Key (get one at console.anthropic.com)"
        if ($LlmApiKey) {
            Write-OK "Anthropic API key saved - $LlmModel"
        } else {
            Write-Warn "No API key entered - you can add it to .env later"
        }
    }
    "2" {
        $LlmProvider = "openai"
        Write-Host ""
        Write-Host "  Select OpenAI model:" -ForegroundColor White
        Write-Host "    1. gpt-4.1                  - Latest, best quality (recommended)"
        Write-Host "    2. gpt-4.1-mini             - Fast, cost-effective"
        Write-Host "    3. gpt-4.1-nano             - Fastest, lowest cost"
        Write-Host "    4. o3                       - Best reasoning"
        Write-Host ""
        $OaiModel = Read-Host "  Enter choice [1-4] (default: 1)"
        if (-not $OaiModel) { $OaiModel = "1" }
        switch ($OaiModel) {
            "2" { $LlmModel = "gpt-4.1-mini" }
            "3" { $LlmModel = "gpt-4.1-nano" }
            "4" { $LlmModel = "o3" }
            default { $LlmModel = "gpt-4.1" }
        }
        $LlmApiKeyName = "OPENAI_API_KEY"
        Write-Host ""
        $LlmApiKey = Read-Host "  OpenAI API Key (get one at platform.openai.com)"
        if ($LlmApiKey) {
            Write-OK "OpenAI API key saved - $LlmModel"
        } else {
            Write-Warn "No API key entered - you can add it to .env later"
        }
    }
    "3" {
        $LlmProvider = "google"
        $LlmModel = "gemini-2.5-pro"
        $LlmApiKeyName = "GOOGLE_AI_API_KEY"
        Write-Host ""
        $LlmApiKey = Read-Host "  Google AI API Key (get one at aistudio.google.com)"
        if ($LlmApiKey) {
            Write-OK "Google AI API key saved - $LlmModel"
        } else {
            Write-Warn "No API key entered - you can add it to .env later"
        }
    }
    "4" {
        $LlmProvider = "ollama"
        Write-Host ""
        if (Test-CommandExists "ollama") {
            Write-OK "Ollama detected"
        } else {
            Write-Info "Installing Ollama..."
            if (Test-CommandExists "winget") {
                winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements --silent
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            } else {
                Write-Warn "Please install Ollama manually from https://ollama.com/download"
            }
        }
        Write-Host ""
        Write-Host "  Select local model:" -ForegroundColor White
        Write-Host "    1. llama3.1:8b               - Good balance (8GB RAM)"
        Write-Host "    2. llama3.1:70b              - High quality (64GB RAM)"
        Write-Host "    3. mistral:7b                - Fast, lightweight"
        Write-Host "    4. Custom model"
        Write-Host ""
        $LocalModel = Read-Host "  Enter choice [1-4] (default: 1)"
        if (-not $LocalModel) { $LocalModel = "1" }
        switch ($LocalModel) {
            "2" { $LlmModel = "llama3.1:70b" }
            "3" { $LlmModel = "mistral:7b" }
            "4" { $LlmModel = Read-Host "  Enter model name" }
            default { $LlmModel = "llama3.1:8b" }
        }
        Write-Info "Pulling model $LlmModel (this may take a while)..."
        $ErrorActionPreference = "Continue"
        ollama pull $LlmModel 2>&1 | Out-Null
        $ErrorActionPreference = "Stop"
    }
    "5" {
        $LlmProvider = "none"
        $LlmModel = ""
        Write-OK "No user-facing LLM - keeping manual copy-paste mode"
    }
}

# --- Level 2: Backend LLM ---
Write-Host ""
Write-Host "--- Level 2: Backend LLM (Server Automation) ---" -ForegroundColor White
Write-Host ""
Write-Host "  Which LLM provider for BACKEND automation?" -ForegroundColor White
Write-Host "  (Used for smart form filling, resume tailoring, cover letters)" -ForegroundColor Cyan
Write-Host ""
Write-Host "    1. Claude (Anthropic)        - Best for structured output"
Write-Host "    2. GPT (OpenAI)              - Strong function calling"
Write-Host "    3. Gemini (Google)           - Cost-effective for high volume"
Write-Host "    4. Local/Ollama              - Free, private, no API costs"
if ($LlmProvider -ne "none") {
    Write-Host "    5. Same as Level 1 ($LlmProvider - $LlmModel)"
}
Write-Host "    6. None (basic automation only - no LLM)"
Write-Host ""

$LlmL2Choice = Read-Host "  Enter choice [1-6] (default: 5)"
if (-not $LlmL2Choice) { $LlmL2Choice = "5" }

$LlmBackendProvider = ""
$LlmBackendModel = ""
$LlmBackendApiKeyName = ""
$LlmBackendApiKey = ""

switch ($LlmL2Choice) {
    "1" {
        $LlmBackendProvider = "anthropic"
        $LlmBackendModel = "claude-sonnet-4-6"
        $LlmBackendApiKeyName = "ANTHROPIC_API_KEY"
        if ($LlmProvider -eq "anthropic" -and $LlmApiKey) {
            $LlmBackendApiKey = $LlmApiKey
            Write-OK "Reusing Anthropic API key from Level 1"
        } else {
            $LlmBackendApiKey = Read-Host "  Anthropic API Key"
        }
    }
    "2" {
        $LlmBackendProvider = "openai"
        $LlmBackendModel = "gpt-4.1-mini"
        $LlmBackendApiKeyName = "OPENAI_API_KEY"
        if ($LlmProvider -eq "openai" -and $LlmApiKey) {
            $LlmBackendApiKey = $LlmApiKey
            Write-OK "Reusing OpenAI API key from Level 1"
        } else {
            $LlmBackendApiKey = Read-Host "  OpenAI API Key"
        }
    }
    "3" {
        $LlmBackendProvider = "google"
        $LlmBackendModel = "gemini-2.5-flash"
        $LlmBackendApiKeyName = "GOOGLE_AI_API_KEY"
        if ($LlmProvider -eq "google" -and $LlmApiKey) {
            $LlmBackendApiKey = $LlmApiKey
            Write-OK "Reusing Google AI API key from Level 1"
        } else {
            $LlmBackendApiKey = Read-Host "  Google AI API Key"
        }
    }
    "4" {
        $LlmBackendProvider = "ollama"
        $LlmBackendModel = "llama3.1:8b"
        if (-not (Test-CommandExists "ollama")) {
            Write-Info "Installing Ollama..."
            if (Test-CommandExists "winget") {
                winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements --silent
            }
        }
        $ErrorActionPreference = "Continue"
        ollama pull $LlmBackendModel 2>&1 | Out-Null
        $ErrorActionPreference = "Stop"
    }
    "5" {
        $LlmBackendProvider = $LlmProvider
        $LlmBackendModel = $LlmModel
        $LlmBackendApiKeyName = $LlmApiKeyName
        $LlmBackendApiKey = $LlmApiKey
        Write-OK "Reusing Level 1 config for backend ($LlmProvider - $LlmModel)"
    }
    "6" {
        $LlmBackendProvider = "none"
        $LlmBackendModel = ""
        Write-OK "No backend LLM - basic automation only"
    }
}

# --- LLM Features ---
Write-Host ""
Write-Host "--- LLM Features ---" -ForegroundColor White
Write-Host ""

$LlmResumeTailoring = "false"
$LlmCoverLetters = "false"
$LlmSmartAnswers = "false"
$LlmMonthlyLimit = "0"

if ($LlmBackendProvider -ne "none") {
    $featResume = Read-Host "  Enable resume tailoring per job? (LLM customizes resume) [Y/n]"
    if (-not $featResume -or $featResume -match "^[Yy]") { $LlmResumeTailoring = "true" }

    $featCover = Read-Host "  Enable auto cover letter generation? [Y/n]"
    if (-not $featCover -or $featCover -match "^[Yy]") { $LlmCoverLetters = "true" }

    $featSmart = Read-Host "  Enable smart form-field answering? ('Why do you want to work here?' etc.) [Y/n]"
    if (-not $featSmart -or $featSmart -match "^[Yy]") { $LlmSmartAnswers = "true" }

    Write-Host ""
    $LlmMonthlyLimit = Read-Host "  Set monthly LLM spending limit $/month [0 = unlimited] (default: 50)"
    if (-not $LlmMonthlyLimit) { $LlmMonthlyLimit = "50" }
    Write-Host "  -> Monthly limit set: `$$LlmMonthlyLimit" -ForegroundColor Green
} else {
    Write-Info "Skipping LLM features (no backend LLM selected)"
}

# --- Install LLM SDKs ---
Write-Host ""
$ErrorActionPreference = "Continue"

if ($LlmProvider -eq "anthropic" -or $LlmBackendProvider -eq "anthropic") {
    Write-Info "Installing Anthropic SDK..."
    & $PythonCmd -m pip install --quiet anthropic 2>&1 | Out-Null
    Write-OK "Anthropic Python SDK installed"
}

if ($LlmProvider -eq "openai" -or $LlmBackendProvider -eq "openai") {
    Write-Info "Installing OpenAI SDK..."
    & $PythonCmd -m pip install --quiet openai 2>&1 | Out-Null
    Write-OK "OpenAI Python SDK installed"
}

if ($LlmProvider -eq "google" -or $LlmBackendProvider -eq "google") {
    Write-Info "Installing Google AI SDK..."
    & $PythonCmd -m pip install --quiet google-generativeai 2>&1 | Out-Null
    Write-OK "Google AI Python SDK installed"
}

$ErrorActionPreference = "Stop"

# --- Write LLM config to .env ---
if (Test-Path $EnvFile) {
    $llmEnvBlock = @"

# -- LLM Configuration ------------------------------------------
# Level 1: User-Facing (Chat & AI Import)
LLM_PROVIDER=$LlmProvider
LLM_MODEL=$LlmModel

# Level 2: Backend (Server Automation)
LLM_BACKEND_PROVIDER=$LlmBackendProvider
LLM_BACKEND_MODEL=$LlmBackendModel

# API Keys
"@
    if ($LlmApiKeyName -and $LlmApiKey) {
        $llmEnvBlock += "`n${LlmApiKeyName}=${LlmApiKey}"
    } else {
        $llmEnvBlock += "`n# No Level 1 API key set"
    }
    if ($LlmBackendApiKeyName -and $LlmBackendApiKey -and $LlmBackendApiKeyName -ne $LlmApiKeyName) {
        $llmEnvBlock += "`n${LlmBackendApiKeyName}=${LlmBackendApiKey}"
    }
    if ($LlmBackendProvider -eq "ollama") {
        $llmEnvBlock += "`nOLLAMA_BASE_URL=http://localhost:11434"
    }

    $llmEnvBlock += @"

# LLM Features
LLM_RESUME_TAILORING=$LlmResumeTailoring
LLM_COVER_LETTERS=$LlmCoverLetters
LLM_SMART_ANSWERS=$LlmSmartAnswers
LLM_MONTHLY_LIMIT=$LlmMonthlyLimit
"@
    Add-Content -Path $EnvFile -Value $llmEnvBlock
    Write-OK "LLM configuration added to .env"
}

# --- LLM Summary ---
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════╗" -ForegroundColor White
Write-Host "║  LLM CONFIGURATION SUMMARY                      ║" -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────╣" -ForegroundColor White
Write-Host ("║  Level 1 (User-facing):  {0,-23} ║" -f "$LlmProvider / $LlmModel") -ForegroundColor Cyan
Write-Host ("║  Level 2 (Backend):      {0,-23} ║" -f "$LlmBackendProvider / $LlmBackendModel") -ForegroundColor Cyan
Write-Host ("║  Resume tailoring:       {0,-23} ║" -f $LlmResumeTailoring) -ForegroundColor White
Write-Host ("║  Cover letters:          {0,-23} ║" -f $LlmCoverLetters) -ForegroundColor White
Write-Host ("║  Smart form answers:     {0,-23} ║" -f $LlmSmartAnswers) -ForegroundColor White
Write-Host ("║  Monthly spend limit:    `${0,-22} ║" -f $LlmMonthlyLimit) -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────╣" -ForegroundColor White
Write-Host "║  API Keys saved to .env                          ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════╝" -ForegroundColor White
Write-Host ""

# ── Step 10: Verify ─────────────────────────────────────────────────────────
Write-Step 10 "Verifying setup..."

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

# ── Post-Setup Status Dashboard ──────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor White
Write-Host "║                  SETUP STATUS DASHBOARD                     ║" -ForegroundColor White
Write-Host "╠══════════════════════════════════════════════════════════════╣" -ForegroundColor White

Write-Host "║  INSTALLED COMPONENTS                                       ║" -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

function Write-Status($ok, $name, $detail) {
    if ($ok) {
        Write-Host ("  [READY]   {0,-22} {1}" -f $name, $detail) -ForegroundColor Green
    } else {
        Write-Host ("  [MISSING] {0,-22} {1}" -f $name, $detail) -ForegroundColor Red
    }
}

Write-Status (Test-CommandExists $PythonCmd) "Python" "$(& $PythonCmd --version 2>&1)"
Write-Status (Test-CommandExists "node") "Node.js" "$(node --version 2>&1)"
Write-Status (Test-CommandExists "npm") "npm" "$(npm --version 2>&1)"
Write-Status (Test-CommandExists "git") "Git" "$(git --version 2>&1)"
Write-Status (Test-CommandExists "openclaw") "OpenClaw CLI" "$(try { openclaw --version 2>&1 } catch { '' })"

try { & $PythonCmd -c "import playwright" 2>$null; $pwOk = $true } catch { $pwOk = $false }
Write-Status $pwOk "Playwright" ""

try { & $PythonCmd -c "import supabase" 2>$null; $sbOk = $true } catch { $sbOk = $false }
Write-Status $sbOk "Supabase SDK" ""

try { & $PythonCmd -c "import httpx" 2>$null; $hxOk = $true } catch { $hxOk = $false }
Write-Status $hxOk "httpx" ""

# LLM SDKs
if ($LlmProvider -eq "anthropic" -or $LlmBackendProvider -eq "anthropic") {
    try { & $PythonCmd -c "import anthropic" 2>$null; $anOk = $true } catch { $anOk = $false }
    Write-Status $anOk "Anthropic SDK" ""
}
if ($LlmProvider -eq "openai" -or $LlmBackendProvider -eq "openai") {
    try { & $PythonCmd -c "import openai" 2>$null; $oaiOk = $true } catch { $oaiOk = $false }
    Write-Status $oaiOk "OpenAI SDK" ""
}
if ($LlmProvider -eq "google" -or $LlmBackendProvider -eq "google") {
    try { & $PythonCmd -c "import google.generativeai" 2>$null; $gOk = $true } catch { $gOk = $false }
    Write-Status $gOk "Google AI SDK" ""
}
if ($LlmProvider -eq "ollama" -or $LlmBackendProvider -eq "ollama") {
    Write-Status (Test-CommandExists "ollama") "Ollama" ""
}

Write-Host ""
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White
Write-Host "║  CONFIGURATION                                              ║" -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

function Write-EnvStatus($key, $label) {
    $val = $null
    if (Test-Path $EnvFile) {
        $val = (Select-String -Path $EnvFile -Pattern "^${key}=(.+)$" -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Matches[0].Groups[1].Value })
    }
    if ($val) {
        Write-Host ("  [SET]     {0,-22}" -f $label) -ForegroundColor Green
    } else {
        Write-Host ("  [NOT SET] {0,-22} <-- action needed" -f $label) -ForegroundColor Yellow
    }
}

Write-Status (Test-Path $EnvFile) ".env file" "$EnvFile"
Write-EnvStatus "NEXT_PUBLIC_SUPABASE_URL" "Supabase URL       (required)"
Write-EnvStatus "NEXT_PUBLIC_SUPABASE_ANON_KEY" "Supabase Anon Key  (required)"
Write-EnvStatus "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service   (required)"
Write-EnvStatus "ENCRYPTION_KEY" "Encryption Key     (required)"
Write-EnvStatus "WORKER_ID" "Worker ID          (required)"
Write-EnvStatus "TELEGRAM_BOT_TOKEN" "Telegram Bot Token (optional)"
Write-EnvStatus "STRIPE_SECRET_KEY" "Stripe Secret Key  (optional)"
Write-EnvStatus "GOOGLE_CLIENT_ID" "Google OAuth       (optional)"

Write-Host ""
Write-Host "  LLM Config:" -ForegroundColor White
Write-EnvStatus "LLM_PROVIDER" "LLM Provider L1    (required)"
Write-EnvStatus "LLM_MODEL" "LLM Model L1       (required)"
Write-EnvStatus "LLM_BACKEND_PROVIDER" "LLM Provider L2    (required)"
Write-EnvStatus "LLM_BACKEND_MODEL" "LLM Model L2       (required)"
Write-EnvStatus "ANTHROPIC_API_KEY" "Anthropic Key      (if Claude)"
Write-EnvStatus "OPENAI_API_KEY" "OpenAI Key         (if GPT)"

Write-Host ""
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White
Write-Host "║  SERVICES & CONNECTIONS                                     ║" -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

# Test Supabase connection
$sbConnected = $false
if (Test-Path $EnvFile) {
    $sbUrl = (Select-String -Path $EnvFile -Pattern "^NEXT_PUBLIC_SUPABASE_URL=(.+)$" -ErrorAction SilentlyContinue |
              ForEach-Object { $_.Matches[0].Groups[1].Value })
    if ($sbUrl) {
        try {
            $response = Invoke-WebRequest -Uri "${sbUrl}/rest/v1/" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($response.StatusCode -lt 400) { $sbConnected = $true }
        } catch { }
    }
}
if ($sbConnected) {
    Write-Host ("  [ONLINE]  {0,-22}" -f "Supabase API") -ForegroundColor Green
} else {
    Write-Host ("  [OFFLINE] {0,-22} <-- check URL/keys" -f "Supabase API") -ForegroundColor Yellow
}

# Worker code
$workerPath = Join-Path $InstallDir "packages\worker\worker.py"
if (Test-Path $workerPath) {
    Write-Host ("  [READY]   {0,-22}" -f "Worker code") -ForegroundColor Green
} else {
    Write-Host ("  [MISSING] {0,-22} <-- repo not cloned?" -f "Worker code") -ForegroundColor Yellow
}

# OpenClaw Pro
if (Test-CommandExists "openclaw") {
    $ErrorActionPreference = "Continue"
    $ocStatus = try { openclaw status 2>&1 } catch { "" }
    $ErrorActionPreference = "Stop"
    if ($ocStatus -match "pro|active|licensed") {
        Write-Host ("  [ACTIVE]  {0,-22}" -f "OpenClaw Pro License") -ForegroundColor Green
    } else {
        Write-Host ("  [FREE]    {0,-22} <-- Pro needed (`$20/mo)" -f "OpenClaw Pro License") -ForegroundColor Yellow
    }
}

Write-Status (Test-Path $resumeDir) "Worker directories" ""

Write-Host ""
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White
Write-Host "║  STILL TODO                                                 ║" -ForegroundColor White
Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

$TodoNum = 0

function Write-Todo($msg) {
    $script:TodoNum++
    Write-Host "  $($script:TodoNum). $msg" -ForegroundColor Yellow
}

# Check what's still needed
$hasSbUrl = $false
if (Test-Path $EnvFile) {
    $hasSbUrl = [bool](Select-String -Path $EnvFile -Pattern "^NEXT_PUBLIC_SUPABASE_URL=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasSbUrl) { Write-Todo "(required) Add Supabase credentials to .env" }

if (-not (Test-CommandExists "openclaw")) {
    Write-Todo "(required) Install OpenClaw CLI: npm install -g openclaw"
} elseif (-not ($ocStatus -match "pro|active|licensed")) {
    Write-Todo "(required) Activate OpenClaw Pro: https://openclaw.com/pricing"
}

if (-not (Test-Path $workerPath)) {
    Write-Todo "(required) Clone the AutoApply repo (private - ask admin for access)"
}

if ($LlmProvider -eq "none" -and $LlmBackendProvider -eq "none") {
    Write-Todo "(required) Configure LLM provider - re-run setup or edit .env"
} else {
    if (($LlmProvider -eq "anthropic" -or $LlmBackendProvider -eq "anthropic") -and -not (Select-String -Path $EnvFile -Pattern "^ANTHROPIC_API_KEY=.+" -ErrorAction SilentlyContinue)) {
        Write-Todo "(required) Add Anthropic API key to .env (console.anthropic.com)"
    }
    if (($LlmProvider -eq "openai" -or $LlmBackendProvider -eq "openai") -and -not (Select-String -Path $EnvFile -Pattern "^OPENAI_API_KEY=.+" -ErrorAction SilentlyContinue)) {
        Write-Todo "(required) Add OpenAI API key to .env (platform.openai.com)"
    }
}

Write-Todo "(required) Log in at https://autoapply-web.vercel.app and complete onboarding"
Write-Todo "(required) Start the worker: cd packages\worker && $PythonCmd worker.py"

$hasStripe = $false
if (Test-Path $EnvFile) {
    $hasStripe = [bool](Select-String -Path $EnvFile -Pattern "^STRIPE_SECRET_KEY=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasStripe) { Write-Todo "(optional) Set up Stripe billing keys in .env" }

$hasGoogle = $false
if (Test-Path $EnvFile) {
    $hasGoogle = [bool](Select-String -Path $EnvFile -Pattern "^GOOGLE_CLIENT_ID=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasGoogle) { Write-Todo "(optional) Set up Google OAuth for Gmail connect" }

if ($TodoNum -eq 0) {
    Write-Host "  Nothing! You're all set." -ForegroundColor Green
}

Write-Host ""
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor White
Write-Host ""
Write-Host "  Run this status check anytime: powershell $InstallDir\status.ps1" -ForegroundColor Cyan
Write-Host ""
