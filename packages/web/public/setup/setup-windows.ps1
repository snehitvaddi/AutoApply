# ============================================================================
# ApplyLoop — Windows Setup Script
# Downloads, installs, and configures everything needed to run ApplyLoop worker
# Run in PowerShell as Administrator:
#   Set-ExecutionPolicy Bypass -Scope Process; .\setup-windows.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

# Parse flags
$AdvancedMode = $args -contains "--advanced"

$RequiredPython = "3.11"
$RequiredNode = "18"
$InstallDir = "$env:USERPROFILE\autoapply"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║       ApplyLoop — Windows Setup              ║" -ForegroundColor Cyan
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

$script:TotalSteps = 11

# ── Main ─────────────────────────────────────────────────────────────────────

Write-Banner

Write-Host "This script will:" -ForegroundColor White
Write-Host "  1. Check Windows prerequisites (winget)"
Write-Host "  2. Install/verify Python $RequiredPython+"
Write-Host "  3. Install/verify Node.js $RequiredNode+"
Write-Host "  4. Install OpenClaw CLI"
Write-Host "  5. Install Playwright browsers"
Write-Host "  6. Clone ApplyLoop repository"
Write-Host "  7. Install all dependencies"
Write-Host "  8. Configure LLM provider + install AI CLI"
Write-Host "  9. Generate setup context (AGENTS.md)"
Write-Host "  10. Launch AI assistant to complete setup"
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

# OpenClaw onboarding + gateway setup
if (Test-CommandExists "openclaw") {
    # Check if already configured
    $ocConfigPath = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"
    if (-not (Test-Path $ocConfigPath)) {
        Write-Info "Setting up OpenClaw (browser will open for authentication)..."
        $ErrorActionPreference = "Continue"
        try {
            Start-Process -FilePath "openclaw.cmd" -ArgumentList "onboard" -NoNewWindow -Wait -ErrorAction SilentlyContinue 2>$null
        } catch {
            Write-Warn "OpenClaw onboard failed. After setup, run: openclaw onboard"
        }
        $ErrorActionPreference = "Stop"
    } else {
        Write-OK "OpenClaw already configured"
    }

    # Start the gateway (browser automation service)
    Write-Info "Starting OpenClaw gateway..."
    $ErrorActionPreference = "Continue"
    try {
        Start-Process -FilePath "openclaw.cmd" -ArgumentList "gateway", "start" -NoNewWindow -Wait -ErrorAction SilentlyContinue 2>$null
        Write-OK "OpenClaw gateway started"
    } catch {
        Write-Warn "Gateway start failed. After setup, run: openclaw gateway start"
    }
    $ErrorActionPreference = "Stop"
}


# ── Step 5: Playwright ──────────────────────────────────────────────────────
Write-Step 5 "Installing Playwright browsers..."

$ErrorActionPreference = "Continue"
& $PythonCmd -m pip install --quiet playwright 2>&1 | Where-Object { $_ -notmatch "WARNING|warn" } | Write-Host
& $PythonCmd -m playwright install chromium 2>&1 | Where-Object { $_ -notmatch "WARNING|warn" } | Write-Host
$ErrorActionPreference = "Stop"
Write-OK "Playwright Chromium installed"

# ── Step 5b: Optional tools (Himalaya, AgentMail) ─────────────────────────
Write-Step 5 "Installing optional tools (Himalaya, AgentMail)..."

Write-Host ""
Write-Host "  Himalaya CLI lets the worker read Gmail (OTP codes, confirmations)." -ForegroundColor Cyan
Write-Host "  AgentMail provides disposable email inboxes for applications." -ForegroundColor Cyan
Write-Host ""

# Himalaya CLI (Gmail reading)
if (Test-CommandExists "himalaya") {
    Write-OK "Himalaya CLI already installed"
} else {
    $installHim = Read-Host "  Install Himalaya CLI for Gmail reading? [Y/n]"
    if (-not $installHim -or $installHim -match "^[Yy]") {
        # Try cargo first (most reliable), then direct download, then winget
        $himInstalled = $false
        if (Test-CommandExists "cargo") {
            Write-Info "Installing Himalaya via cargo..."
            $ErrorActionPreference = "Continue"
            cargo install himalaya 2>&1 | Out-Null
            $ErrorActionPreference = "Stop"
            if (Test-CommandExists "himalaya") { $himInstalled = $true; Write-OK "Himalaya installed via cargo" }
        }
        if (-not $himInstalled) {
            # Direct download from GitHub releases (it's a .zip, not .exe)
            Write-Info "Downloading Himalaya from GitHub..."
            $ErrorActionPreference = "Continue"
            try {
                $himZipUrl = "https://github.com/pimalaya/himalaya/releases/latest/download/himalaya.x86_64-windows.zip"
                $himZip = Join-Path $env:TEMP "himalaya-windows.zip"
                $himExtract = Join-Path $env:TEMP "himalaya-extract"
                $himDest = "$env:LOCALAPPDATA\Microsoft\WindowsApps\himalaya.exe"
                Invoke-WebRequest -Uri $himZipUrl -OutFile $himZip -UseBasicParsing 2>$null
                if (Test-Path $himZip) {
                    Expand-Archive -Path $himZip -DestinationPath $himExtract -Force 2>$null
                    $himExe = Get-ChildItem -Path $himExtract -Filter "himalaya.exe" -Recurse | Select-Object -First 1
                    if ($himExe) {
                        Copy-Item $himExe.FullName $himDest -Force
                        $himInstalled = $true
                        Write-OK "Himalaya installed to $himDest"
                    }
                    Remove-Item $himZip -Force -ErrorAction SilentlyContinue
                    Remove-Item $himExtract -Recurse -Force -ErrorAction SilentlyContinue
                }
            } catch {}
            $ErrorActionPreference = "Stop"
        }
        if (-not $himInstalled) {
            Write-Warn "Himalaya install failed. Install manually from: https://github.com/pimalaya/himalaya/releases"
        }
    } else {
        Write-Info "Skipping Himalaya"
    }
}

# AgentMail (disposable inboxes)
$amInstalled = $false
try { & $PythonCmd -c "import agentmail" 2>$null; $amInstalled = $true } catch {}
if ($amInstalled) {
    Write-OK "AgentMail SDK already installed"
} else {
    $installAm = Read-Host "  Install AgentMail SDK for disposable inboxes? [Y/n]"
    if (-not $installAm -or $installAm -match "^[Yy]") {
        Write-Info "Installing AgentMail..."
        $ErrorActionPreference = "Continue"
        & $PythonCmd -m pip install --quiet agentmail 2>&1 | Out-Null
        $ErrorActionPreference = "Stop"
        Write-OK "AgentMail SDK installed"
    } else {
        Write-Info "Skipping AgentMail - install later: pip install agentmail"
    }
}

Write-Host ""
Write-Host "  Multi-resume support: You can upload multiple PDFs with role tags" -ForegroundColor Cyan
Write-Host "  (e.g., 'GenAI Resume.pdf', 'DS Resume.pdf') and the worker will" -ForegroundColor Cyan
Write-Host "  pick the best match for each job automatically." -ForegroundColor Cyan
Write-Host ""

# ── Step 6: Clone repo ──────────────────────────────────────────────────────
Write-Step 6 "Setting up ApplyLoop..."

if (Test-Path $InstallDir) {
    Write-OK "ApplyLoop directory exists at $InstallDir"
    Set-Location $InstallDir
    if (Test-Path ".git") {
        Write-Info "Pulling latest changes..."
        try { git pull origin main 2>$null } catch { Write-Warn "Git pull failed — using existing files" }
    }
} else {
    Write-Info "Cloning ApplyLoop (this may open a browser for GitHub auth)..."
    Write-Host "  If the terminal hangs after browser auth, press Ctrl+C and re-run the script." -ForegroundColor Yellow
    $cloned = $false
    try {
        # Set GIT_TERMINAL_PROMPT to avoid interactive prompts hanging
        $env:GIT_TERMINAL_PROMPT = "0"
        $cloneProcess = Start-Process -FilePath "git" -ArgumentList "clone", "https://github.com/snehitvaddi/AutoApply.git", $InstallDir -NoNewWindow -PassThru -Wait -RedirectStandardError "$env:TEMP\git-clone-err.txt"
        if ($cloneProcess.ExitCode -eq 0 -and (Test-Path "$InstallDir\.git")) {
            $cloned = $true
            Write-OK "Repository cloned"
        }
    } catch {}

    if (-not $cloned) {
        Write-Warn "Git clone failed. The repo is private — you need GitHub access."
        Write-Host ""
        Write-Host "  Option 1: Ask the admin to add your GitHub account as a collaborator" -ForegroundColor Yellow
        Write-Host "  Option 2: Ask the admin for a personal access token and run:" -ForegroundColor Yellow
        Write-Host "    git clone https://TOKEN@github.com/snehitvaddi/AutoApply.git $InstallDir" -ForegroundColor Cyan
        Write-Host ""
        $manualClone = Read-Host "  Press Enter after cloning manually, or type 'skip' to continue without code"
        if (-not (Test-Path $InstallDir)) {
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        }
    }

    if (Test-Path $InstallDir) { Set-Location $InstallDir }
}

# ── Step 7: Install dependencies ────────────────────────────────────────────
Write-Step 7 "Installing dependencies..."

$ErrorActionPreference = "Continue"

if (Test-Path "packages/worker/requirements.txt") {
    Write-Info "Installing Python packages from requirements.txt..."
    & $PythonCmd -m pip install --quiet -r packages/worker/requirements.txt 2>&1 | Where-Object { $_ -notmatch "WARNING|warn" } | Write-Host
    Write-OK "Python packages installed"
} else {
    Write-Info "Installing core Python packages directly..."
    & $PythonCmd -m pip install --quiet supabase httpx playwright cryptography google-auth google-auth-oauthlib google-api-python-client 2>&1 | Where-Object { $_ -notmatch "WARNING|warn" } | Write-Host
    Write-OK "Core Python packages installed"
}

if (Test-Path "packages/web/package.json") {
    Write-Info "Installing Node.js packages..."
    Push-Location packages/web
    npm install --silent 2>&1 | Where-Object { $_ -notmatch "npm warn" } | Write-Host
    Pop-Location
    Write-OK "Node.js packages installed"
} else {
    Write-Warn "packages/web/package.json not found — skipping"
}

$ErrorActionPreference = "Stop"

# ── Step 8: LLM Provider + AI CLI Installation ─────────────────────────────
Write-Step 8 "Configuring LLM provider and AI CLI..."

$LlmProvider = "none"; $LlmModel = ""; $LlmAccessType = "none"; $LlmApiKeyName = ""; $LlmApiKey = ""
$LlmCliCmd = $null

if ($AdvancedMode) {
    # ── Advanced mode: full provider selection (--advanced flag) ──
    Write-Host ""
    Write-Host "  One LLM powers everything (chat + OpenClaw backend)." -ForegroundColor Cyan
    Write-Host "  Pick your provider and access type — that's it." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    1. Claude (Anthropic)     2. GPT (OpenAI)"
    Write-Host "    3. Gemini (Google)        4. Local/Ollama"
    Write-Host "    5. None (skip for now)"
    Write-Host ""

    $LlmChoice = Read-Host "  Provider [1-5] (default: 1)"
    if (-not $LlmChoice) { $LlmChoice = "1" }

    switch ($LlmChoice) {
        "1" {
            $LlmProvider = "anthropic"
            Write-Host ""; Write-Host "    1. Subscription (Pro `$20, Max `$100-200/mo)    2. API (pay-per-token)"
            $ac = Read-Host "  Access type [1-2] (default: 2)"; if (-not $ac) { $ac = "2" }
            if ($ac -eq "1") {
                $LlmAccessType = "subscription"
                Write-Host "    1. Pro (`$20)  2. Max 5x (`$100)  3. Max 20x (`$200)"
                $st = Read-Host "  Tier [1-3] (default: 1)"
                switch ($st) { "2" { $LlmModel = "claude-max-5x" } "3" { $LlmModel = "claude-max-20x" } default { $LlmModel = "claude-pro" } }
            } else {
                $LlmAccessType = "api"
                Write-Host "    1. Sonnet 4.6 (recommended)  2. Opus 4.6  3. Haiku 4.5"
                $cm = Read-Host "  Model [1-3] (default: 1)"
                switch ($cm) { "2" { $LlmModel = "claude-opus-4-6" } "3" { $LlmModel = "claude-haiku-4-5-20251001" } default { $LlmModel = "claude-sonnet-4-6" } }
                $LlmApiKeyName = "ANTHROPIC_API_KEY"; $LlmApiKey = Read-Host "  API Key (console.anthropic.com)"
            }

            Write-Info "Installing Claude Code CLI..."
            $ErrorActionPreference = "Continue"
            npm install -g @anthropic-ai/claude-code 2>&1 | Where-Object { $_ -notmatch "npm warn" } | Write-Host
            $ErrorActionPreference = "Stop"
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

            if (Test-CommandExists "claude") {
                Write-OK "Claude Code CLI installed"
                $LlmCliCmd = "claude"
                if ($LlmAccessType -eq "subscription") {
                    Write-Info "Launching Claude login (browser will open)..."
                    $ErrorActionPreference = "Continue"
                    claude login 2>&1 | Write-Host
                    $ErrorActionPreference = "Stop"
                } else {
                    if ($LlmApiKey) {
                        $env:ANTHROPIC_API_KEY = $LlmApiKey
                        Write-OK "ANTHROPIC_API_KEY set for Claude Code CLI"
                    }
                }
            } else {
                Write-Warn "Claude Code CLI install failed — install manually: npm install -g @anthropic-ai/claude-code"
            }
        }
        "2" {
            $LlmProvider = "openai"
            Write-Host ""; Write-Host "    1. Subscription (Plus `$20, Pro `$200/mo)    2. API (pay-per-token)"
            $ac = Read-Host "  Access type [1-2] (default: 2)"; if (-not $ac) { $ac = "2" }
            if ($ac -eq "1") {
                $LlmAccessType = "subscription"
                Write-Host "    1. Plus (`$20)  2. Pro (`$200)  3. Business (`$30/user)"
                $st = Read-Host "  Tier [1-3] (default: 1)"
                switch ($st) { "2" { $LlmModel = "chatgpt-pro" } "3" { $LlmModel = "chatgpt-business" } default { $LlmModel = "chatgpt-plus" } }
            } else {
                $LlmAccessType = "api"
                Write-Host "    1. GPT-4.1 (recommended)  2. GPT-4.1-mini  3. GPT-4.1-nano  4. o3"
                $om = Read-Host "  Model [1-4] (default: 1)"
                switch ($om) { "2" { $LlmModel = "gpt-4.1-mini" } "3" { $LlmModel = "gpt-4.1-nano" } "4" { $LlmModel = "o3" } default { $LlmModel = "gpt-4.1" } }
                $LlmApiKeyName = "OPENAI_API_KEY"; $LlmApiKey = Read-Host "  API Key (platform.openai.com)"
            }

            Write-Info "Installing OpenAI Codex CLI..."
            $ErrorActionPreference = "Continue"
            npm install -g @openai/codex 2>&1 | Where-Object { $_ -notmatch "npm warn" } | Write-Host
            $ErrorActionPreference = "Stop"
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

            if (Test-CommandExists "codex") {
                Write-OK "Codex CLI installed"
                $LlmCliCmd = "codex"
                if ($LlmAccessType -eq "subscription") {
                    Write-Info "Launching Codex login (browser will open)..."
                    $ErrorActionPreference = "Continue"
                    codex login 2>&1 | Write-Host
                    $ErrorActionPreference = "Stop"
                } else {
                    if ($LlmApiKey) {
                        $ErrorActionPreference = "Continue"
                        echo $LlmApiKey | codex login --with-api-key 2>&1 | Write-Host
                        $ErrorActionPreference = "Stop"
                        Write-OK "Codex authenticated with API key"
                    }
                }
            } else {
                Write-Warn "Codex CLI install failed — install manually: npm install -g @openai/codex"
            }
        }
        "3" { $LlmProvider = "google"; $LlmAccessType = "api"; $LlmModel = "gemini-2.5-pro"; $LlmApiKeyName = "GOOGLE_AI_API_KEY"; $LlmApiKey = Read-Host "  Google AI Key"
              Write-Info "No Gemini CLI available yet — setup will continue without AI assistant" }
        "4" { $LlmProvider = "ollama"; $LlmAccessType = "local"; $LlmModel = "llama3.1:8b"
              Write-Info "Local/Ollama selected — no CLI to install" }
        default { Write-OK "No LLM - configure later via settings or openclaw config" }
    }
} else {
    # ── Default mode: install Codex CLI (simplest path) ──
    Write-Host ""
    Write-Host "  Installing OpenAI Codex as your AI engine (default)." -ForegroundColor Cyan
    Write-Host "  For advanced LLM options, re-run with: .\setup-windows.ps1 --advanced" -ForegroundColor Cyan
    Write-Host ""

    $LlmProvider = "openai"
    $LlmModel = "codex"
    $LlmAccessType = "subscription"

    Write-Info "Installing OpenAI Codex CLI..."
    $ErrorActionPreference = "Continue"
    npm install -g @openai/codex 2>&1 | Where-Object { $_ -notmatch "npm warn" } | Write-Host
    $ErrorActionPreference = "Stop"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    if (Test-CommandExists "codex") {
        Write-OK "Codex CLI installed"
        Write-Info "Authenticating Codex (browser will open)..."
        $ErrorActionPreference = "Continue"
        try {
            # Start codex auth in a new interactive window to avoid "stdout is not a terminal"
            Start-Process -FilePath "codex" -ArgumentList "auth" -NoNewWindow -Wait -ErrorAction SilentlyContinue 2>$null
        } catch {
            Write-Warn "Codex auth couldn't run here. After setup, run: codex auth"
        }
        $ErrorActionPreference = "Stop"
        $LlmCliCmd = "codex"
    } else {
        Write-Warn "Codex CLI install failed — install manually: npm install -g @openai/codex"
    }
}

if ($LlmProvider -ne "none") { Write-OK "$LlmProvider / $LlmModel ($LlmAccessType) - used for chat + OpenClaw" }

# Same provider for backend — no separate question
$LlmBackendProvider = $LlmProvider; $LlmBackendModel = $LlmModel

# Configure OpenClaw with the same LLM
if ($LlmProvider -ne "none" -and (Test-CommandExists "openclaw")) {
    $ErrorActionPreference = "Continue"
    openclaw config set ai.provider $LlmProvider 2>&1 | Out-Null
    if ($LlmModel) { openclaw config set ai.model $LlmModel 2>&1 | Out-Null }
    if ($LlmApiKey) { openclaw config set ai.apiKey $LlmApiKey 2>&1 | Out-Null }
    $ErrorActionPreference = "Stop"
    Write-OK "OpenClaw configured with same LLM"
}

# Install SDK + write LLM config to .env
$ErrorActionPreference = "Continue"
if ($LlmProvider -eq "anthropic") { & $PythonCmd -m pip install --quiet anthropic 2>&1 | Out-Null }
if ($LlmProvider -eq "openai") { & $PythonCmd -m pip install --quiet openai 2>&1 | Out-Null }
if ($LlmProvider -eq "google") { & $PythonCmd -m pip install --quiet google-generativeai 2>&1 | Out-Null }
$ErrorActionPreference = "Stop"

# Create .env — ONE input: worker token. Everything else is automatic.
$EnvFile = Join-Path $InstallDir ".env"
$AppUrl = "https://applyloop.vercel.app"

# Hardcoded Supabase connection (admin's shared instance — RLS enforces per-user access)
$SupabaseUrl = "https://vegcqubtypvdqlduxhqv.supabase.co"
$SupabaseAnon = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZlZ2NxdWJ0eXB2ZHFsZHV4aHF2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM3NTkyOTYsImV4cCI6MjA4OTMzNTI5Nn0.MJ24A6INzw2dOkv-TZUchM5WGPI2ZG-WxpEy-GROjfw"

if (-not (Test-Path $EnvFile)) {
    Write-Host ""
    Write-Host "  Enter your worker token (provided by admin after approval)." -ForegroundColor Cyan
    $WorkerToken = Read-Host "  Worker token"

    if (-not $WorkerToken) {
        Write-Warn "No worker token provided. You can add it to .env later."
    }

    # Fetch profile + telegram config from API using worker token
    $TelegramToken = ""
    $TelegramChatId = ""
    if ($WorkerToken) {
        Write-Info "Fetching your profile from ApplyLoop..."
        try {
            $ConfigResponse = Invoke-RestMethod -Uri "$AppUrl/api/settings/cli-config" -Headers @{ "X-Worker-Token" = $WorkerToken } -ErrorAction Stop

            if ($ConfigResponse.data) {
                # Telegram bot token is global (admin's bot) — fetched from API
                if ($ConfigResponse.data.telegram_bot_token) {
                    $TelegramToken = $ConfigResponse.data.telegram_bot_token
                }
                if ($ConfigResponse.data.telegram_chat_id) {
                    $TelegramChatId = $ConfigResponse.data.telegram_chat_id
                }

                # Write profile.json for worker LLM context
                $profile = @{
                    user = $ConfigResponse.data.profile
                    preferences = $ConfigResponse.data.preferences
                    resumes = $ConfigResponse.data.resumes
                    work_experience = if ($ConfigResponse.data.profile.work_experience) { $ConfigResponse.data.profile.work_experience } else { @() }
                    education = if ($ConfigResponse.data.profile.education) { $ConfigResponse.data.profile.education } else { @() }
                }
                $profile | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $InstallDir "profile.json") -Encoding UTF8
                Write-OK "Profile synced"
            }
        } catch {
            Write-Warn "Could not fetch profile (check your worker token). Continuing..."
        }
    }

    # Auto-generate worker ID (hostname + random suffix)
    $WorkerId = "worker-$($env:COMPUTERNAME.ToLower())-$(Get-Random -Maximum 9999)"

    # Generate encryption key
    $EncryptionKey = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })

    $envContent = @"
# ApplyLoop Environment Configuration
# Generated by setup-windows.ps1 on $(Get-Date)

# Worker Token (your unique auth — do not share)
WORKER_TOKEN=$WorkerToken

# Supabase (shared instance — your data is isolated via row-level security)
NEXT_PUBLIC_SUPABASE_URL=$SupabaseUrl
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SupabaseAnon
SUPABASE_URL=$SupabaseUrl
SUPABASE_SERVICE_KEY=$SupabaseAnon

# App
NEXT_PUBLIC_APP_URL=$AppUrl
ENCRYPTION_KEY=$EncryptionKey

# Worker
WORKER_ID=$WorkerId
POLL_INTERVAL=10
APPLY_COOLDOWN=30
RESUME_DIR=$env:TEMP\autoapply\resumes
SCREENSHOT_DIR=$env:TEMP\autoapply\screenshots

# Telegram (auto-configured from admin)
TELEGRAM_BOT_TOKEN=$TelegramToken
TELEGRAM_CHAT_ID=$TelegramChatId
"@

    $envContent | Out-File -FilePath $EnvFile -Encoding UTF8
    Write-OK ".env created — only worker token was needed, everything else is automatic"
} else {
    Write-OK ".env file already exists"
}

# Append LLM config to .env
if ($LlmProvider -ne "none" -and (Test-Path $EnvFile)) {
    $llmBlock = "`n# LLM (single provider for chat + OpenClaw)`nLLM_ACCESS_TYPE=$LlmAccessType`nLLM_PROVIDER=$LlmProvider`nLLM_MODEL=$LlmModel`nLLM_BACKEND_PROVIDER=$LlmBackendProvider`nLLM_BACKEND_MODEL=$LlmBackendModel"
    if ($LlmApiKeyName -and $LlmApiKey) { $llmBlock += "`n${LlmApiKeyName}=${LlmApiKey}" }
    if ($LlmProvider -eq "ollama") { $llmBlock += "`nOLLAMA_BASE_URL=http://localhost:11434" }
    Add-Content -Path $EnvFile -Value $llmBlock
    Write-OK "LLM config saved to .env"
}

# Create worker directories
$resumeDir = Join-Path $env:TEMP "autoapply\resumes"
$screenshotDir = Join-Path $env:TEMP "autoapply\screenshots"
New-Item -ItemType Directory -Path $resumeDir -Force | Out-Null
New-Item -ItemType Directory -Path $screenshotDir -Force | Out-Null
Write-OK "Worker directories created"

# ── Auto-Update Setup ──────────────────────────────────────────────────────
Write-Info "Setting up daily auto-updates..."

$UpdateScript = Join-Path $InstallDir "update.ps1"

# Get script directory safely (null when run via iex from URL)
$ScriptDir = $null
if ($MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# Copy update script into install dir
if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "update-windows.ps1"))) {
    Copy-Item (Join-Path $ScriptDir "update-windows.ps1") $UpdateScript -Force
} elseif (Test-Path (Join-Path $InstallDir "packages\web\public\setup\update-windows.ps1")) {
    Copy-Item (Join-Path $InstallDir "packages\web\public\setup\update-windows.ps1") $UpdateScript -Force
} else {
    # Download from hosted URL
    try {
        Invoke-WebRequest -Uri "https://applyloop.vercel.app/setup/update-windows.ps1" -OutFile $UpdateScript -UseBasicParsing -ErrorAction SilentlyContinue
    } catch { }
}

if (Test-Path $UpdateScript) {
    # Create a Scheduled Task for daily auto-update at 3 AM
    $taskName = "ApplyLoop-DailyUpdate"
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$UpdateScript`" -Mode --check"
    $triggerDaily = New-ScheduledTaskTrigger -Daily -At "3:00AM"
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName $taskName -Action $action `
        -Trigger @($triggerDaily, $triggerLogon) `
        -Settings $settings -Description "ApplyLoop auto-update: on login + daily 3AM (skips if updated within 5 days)" `
        -ErrorAction SilentlyContinue | Out-Null

    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Write-OK "Auto-update scheduled: on login + daily 3:00 AM (skips if updated within 5 days)"
    } else {
        Write-Warn "Could not create scheduled task - run manually: powershell $UpdateScript"
    }
    Write-Info "Manual update anytime: powershell $UpdateScript"
} else {
    Write-Warn "Could not set up auto-updates - update script not found"
}

# Skip database migration for regular users — admin handles migrations
# Migrations require the Supabase database password which only the admin has
Write-Info "Skipping database migration (handled by admin)..."
$SkipMigration = $true
$MigrationScript = $null

if (Test-Path (Join-Path $InstallDir "packages\web\public\setup\run-migration.py")) {
    $MigrationScript = Join-Path $InstallDir "packages\web\public\setup\run-migration.py"
} else {
    $MigrationScript = Join-Path $env:TEMP "autoapply-migration.py"
    try {
        Invoke-WebRequest -Uri "https://applyloop.vercel.app/setup/run-migration.py" -OutFile $MigrationScript -UseBasicParsing -ErrorAction SilentlyContinue
    } catch { }
}

if (-not $SkipMigration -and $MigrationScript -and (Test-Path $MigrationScript)) {
    $ErrorActionPreference = "Continue"
    & $PythonCmd $MigrationScript $EnvFile 2>&1 | Write-Host
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Database migration complete"
    } else {
        Write-Warn "Migration skipped - will be handled by AI assistant or run manually"
    }
    $ErrorActionPreference = "Stop"
} else {
    Write-OK "Database is managed by admin — no migration needed on your end"
}

Write-Host ""

# ── Step 9: Generate AGENTS.md context file ─────────────────────────────────
Write-Step 9 "Generating setup context (AGENTS.md)..."

# Gather status for all components
$statusLines = @()
$todoLines = @()
$todoNum = 0

# -- Component status --
function Get-StatusLine($ok, $name, $detail) {
    if ($ok) { return "  [READY]   $name  $detail" }
    else { return "  [MISSING] $name  $detail" }
}

function Get-EnvStatusLine($key, $label) {
    $val = $null
    if (Test-Path $EnvFile) {
        $val = (Select-String -Path $EnvFile -Pattern "^${key}=(.+)$" -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Matches[0].Groups[1].Value })
    }
    if ($val) { return "  [SET]     $label" }
    else { return "  [NOT SET] $label  <-- action needed" }
}

$statusLines += "## Installed Components"
$statusLines += ""
$statusLines += Get-StatusLine (Test-CommandExists $PythonCmd) "Python" "$(& $PythonCmd --version 2>&1)"
$statusLines += Get-StatusLine (Test-CommandExists "node") "Node.js" "$(node --version 2>&1)"
$statusLines += Get-StatusLine (Test-CommandExists "npm") "npm" "$(npm --version 2>&1)"
$statusLines += Get-StatusLine (Test-CommandExists "git") "Git" "$(git --version 2>&1)"
$statusLines += Get-StatusLine (Test-CommandExists "openclaw") "OpenClaw CLI" "$(try { openclaw --version 2>&1 } catch { '' })"

try { & $PythonCmd -c "import playwright" 2>$null; $pwOk = $true } catch { $pwOk = $false }
$statusLines += Get-StatusLine $pwOk "Playwright" ""

try { & $PythonCmd -c "import supabase" 2>$null; $sbOk = $true } catch { $sbOk = $false }
$statusLines += Get-StatusLine $sbOk "Supabase SDK" ""

try { & $PythonCmd -c "import httpx" 2>$null; $hxOk = $true } catch { $hxOk = $false }
$statusLines += Get-StatusLine $hxOk "httpx" ""

# LLM SDKs
if ($LlmProvider -eq "anthropic" -or $LlmBackendProvider -eq "anthropic") {
    try { & $PythonCmd -c "import anthropic" 2>$null; $anOk = $true } catch { $anOk = $false }
    $statusLines += Get-StatusLine $anOk "Anthropic SDK" ""
}
if ($LlmProvider -eq "openai" -or $LlmBackendProvider -eq "openai") {
    try { & $PythonCmd -c "import openai" 2>$null; $oaiOk = $true } catch { $oaiOk = $false }
    $statusLines += Get-StatusLine $oaiOk "OpenAI SDK" ""
}
if ($LlmProvider -eq "google" -or $LlmBackendProvider -eq "google") {
    try { & $PythonCmd -c "import google.generativeai" 2>$null; $gOk = $true } catch { $gOk = $false }
    $statusLines += Get-StatusLine $gOk "Google AI SDK" ""
}
if ($LlmProvider -eq "ollama" -or $LlmBackendProvider -eq "ollama") {
    $statusLines += Get-StatusLine (Test-CommandExists "ollama") "Ollama" ""
}

# LLM CLI
if ($LlmCliCmd) {
    $statusLines += Get-StatusLine (Test-CommandExists $LlmCliCmd) "$LlmCliCmd CLI" ""
}

$statusLines += ""

# -- Configuration status --
$statusLines += "## Configuration"
$statusLines += ""
$statusLines += Get-StatusLine (Test-Path $EnvFile) ".env file" "$EnvFile"
$statusLines += Get-EnvStatusLine "NEXT_PUBLIC_SUPABASE_URL" "Supabase URL       (required)"
$statusLines += Get-EnvStatusLine "NEXT_PUBLIC_SUPABASE_ANON_KEY" "Supabase Anon Key  (required)"
$statusLines += Get-EnvStatusLine "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service   (not needed - API proxy)"
$statusLines += Get-EnvStatusLine "ENCRYPTION_KEY" "Encryption Key     (required)"
$statusLines += Get-EnvStatusLine "WORKER_ID" "Worker ID          (required)"
$statusLines += Get-EnvStatusLine "TELEGRAM_BOT_TOKEN" "Telegram Bot Token (optional)"
$statusLines += Get-EnvStatusLine "STRIPE_SECRET_KEY" "Stripe Secret Key  (optional)"
$statusLines += Get-EnvStatusLine "GOOGLE_CLIENT_ID" "Google OAuth       (optional)"
$statusLines += ""
$statusLines += "### LLM Config"
$statusLines += Get-EnvStatusLine "LLM_PROVIDER" "LLM Provider       (required)"
$statusLines += Get-EnvStatusLine "LLM_MODEL" "LLM Model          (required)"
$statusLines += Get-EnvStatusLine "LLM_BACKEND_PROVIDER" "LLM Backend Prov   (required)"
$statusLines += Get-EnvStatusLine "LLM_BACKEND_MODEL" "LLM Backend Model  (required)"
$statusLines += Get-EnvStatusLine "ANTHROPIC_API_KEY" "Anthropic Key      (if Claude)"
$statusLines += Get-EnvStatusLine "OPENAI_API_KEY" "OpenAI Key         (if GPT)"
$statusLines += ""

# -- Services status --
$statusLines += "## Services & Connections"
$statusLines += ""

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
    $statusLines += "  [ONLINE]  Supabase API"
} else {
    $statusLines += "  [OFFLINE] Supabase API  <-- check URL/keys"
}

$workerPath = Join-Path $InstallDir "packages\worker\worker.py"
if (Test-Path $workerPath) {
    $statusLines += "  [READY]   Worker code"
} else {
    $statusLines += "  [MISSING] Worker code  <-- repo not cloned?"
}

if (Test-CommandExists "openclaw") {
    $ErrorActionPreference = "Continue"
    $ocStatus = try { openclaw status 2>&1 } catch { "" }
    $ErrorActionPreference = "Stop"
    if ($ocStatus -match "pro|active|licensed") {
        $statusLines += "  [ACTIVE]  OpenClaw Pro License"
    } else {
        $statusLines += "  [FREE]    OpenClaw Pro License  <-- Pro needed (`$20/mo)"
    }
}

$statusLines += Get-StatusLine (Test-Path $resumeDir) "Worker directories" ""
$statusLines += ""

# -- TODO list --
$todoLines += "## TODO — Remaining Setup Tasks"
$todoLines += ""

$hasSbUrl = $false
if (Test-Path $EnvFile) {
    $hasSbUrl = [bool](Select-String -Path $EnvFile -Pattern "^NEXT_PUBLIC_SUPABASE_URL=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasSbUrl) { $todoNum++; $todoLines += "$todoNum. **(required)** Add Supabase credentials to .env (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY)" }

if (-not (Test-CommandExists "openclaw")) {
    $todoNum++; $todoLines += "$todoNum. **(required)** Install OpenClaw CLI: ``npm install -g openclaw``"
} elseif (-not ($ocStatus -match "pro|active|licensed")) {
    $todoNum++; $todoLines += "$todoNum. **(required)** Activate OpenClaw Pro: https://openclaw.com/pricing"
}

if (-not (Test-Path $workerPath)) {
    $todoNum++; $todoLines += "$todoNum. **(required)** Clone the ApplyLoop repo: ``git clone https://github.com/snehitvaddi/AutoApply.git $InstallDir\repo && xcopy $InstallDir\repo\* $InstallDir\ /E /Y /I``"
}

if ($LlmProvider -eq "none" -and $LlmBackendProvider -eq "none") {
    $todoNum++; $todoLines += "$todoNum. **(required)** Configure LLM provider — re-run setup or edit .env"
} else {
    if (($LlmProvider -eq "anthropic" -or $LlmBackendProvider -eq "anthropic") -and -not (Select-String -Path $EnvFile -Pattern "^ANTHROPIC_API_KEY=.+" -ErrorAction SilentlyContinue)) {
        $todoNum++; $todoLines += "$todoNum. **(required)** Add Anthropic API key to .env (console.anthropic.com)"
    }
    if (($LlmProvider -eq "openai" -or $LlmBackendProvider -eq "openai") -and -not (Select-String -Path $EnvFile -Pattern "^OPENAI_API_KEY=.+" -ErrorAction SilentlyContinue)) {
        $todoNum++; $todoLines += "$todoNum. (optional) OpenAI API key not needed if using Codex subscription"
    }
}

$todoNum++; $todoLines += "$todoNum. **(required)** Log in at https://applyloop.vercel.app and complete onboarding"
$todoNum++; $todoLines += "$todoNum. (not needed) Database migration handled by admin — skip this"
$todoNum++; $todoLines += "$todoNum. **(required)** Start the worker: ``cd packages\worker && $PythonCmd worker.py``"

$hasStripe = $false
if (Test-Path $EnvFile) {
    $hasStripe = [bool](Select-String -Path $EnvFile -Pattern "^STRIPE_SECRET_KEY=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasStripe) { $todoNum++; $todoLines += "$todoNum. (optional) Set up Stripe billing keys in .env" }

$hasGoogle = $false
if (Test-Path $EnvFile) {
    $hasGoogle = [bool](Select-String -Path $EnvFile -Pattern "^GOOGLE_CLIENT_ID=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasGoogle) { $todoNum++; $todoLines += "$todoNum. (optional) Set up Google OAuth for Gmail connect" }

$hasTelegram = $false
if (Test-Path $EnvFile) {
    $hasTelegram = [bool](Select-String -Path $EnvFile -Pattern "^TELEGRAM_BOT_TOKEN=.+" -ErrorAction SilentlyContinue)
}
if (-not $hasTelegram) { $todoNum++; $todoLines += "$todoNum. (optional) Configure Telegram bot for notifications (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)" }

# -- Build AGENTS.md content --
$agentsMd = @"
# ApplyLoop Setup Status — AGENTS.md
# Generated by setup-windows.ps1 on $(Get-Date)
# This file provides context for the AI setup assistant.

## System Info

- **Install Directory:** $InstallDir
- **Python Command:** $PythonCmd
- **OS:** Windows $(([System.Environment]::OSVersion.Version).ToString())
- **LLM Provider:** $LlmProvider ($LlmAccessType)
- **LLM Model:** $LlmModel
- **LLM CLI:** $(if ($LlmCliCmd) { $LlmCliCmd } else { 'none' })
- **.env Path:** $EnvFile

$($statusLines -join "`n")

$($todoLines -join "`n")

## OpenClaw Commands Reference

``````
openclaw config set ai.provider <provider>   # Set LLM provider
openclaw config set ai.model <model>         # Set LLM model
openclaw config set ai.apiKey <key>          # Set API key
openclaw config get                          # Show current config
openclaw status                              # Show license/status
openclaw start                               # Start worker via OpenClaw
``````

## API Endpoints (Settings)

| Endpoint | Purpose |
|----------|---------|
| ``GET /api/settings``       | Get current user settings |
| ``PUT /api/settings``       | Update user settings |
| ``GET /api/usage``          | Get usage metrics |
| ``GET /api/auth/me``        | Current user info |
| ``POST /api/extract-job-metadata`` | Parse job description |

## How to Update .env

Edit the file directly at: ``$EnvFile``

``````powershell
# Open in notepad:
notepad $EnvFile

# Or set a single value via PowerShell:
(Get-Content $EnvFile) -replace '^NEXT_PUBLIC_SUPABASE_URL=.*', 'NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co' | Set-Content $EnvFile
``````

## Database Migration

``````powershell
cd $InstallDir
$PythonCmd packages\web\public\setup\run-migration.py $EnvFile
``````

## Starting the Worker

``````powershell
cd $InstallDir\packages\worker
$PythonCmd worker.py
``````

## Starting the Web App (Development)

``````powershell
cd $InstallDir\packages\web
npm run dev
``````
"@

$AgentsMdPath = Join-Path $InstallDir "AGENTS.md"
$agentsMd | Out-File -FilePath $AgentsMdPath -Encoding UTF8
Write-OK "AGENTS.md generated at $AgentsMdPath"

Write-Host ""

# ── Step 10: Launch LLM CLI with context ─────────────────────────────────────
Write-Step 10 "Launching AI setup assistant..."

# Copy SOUL.md to install directory (the agent's brain)
$SoulSource = Join-Path $InstallDir "repo\packages\worker\SOUL.md"
if (-not (Test-Path $SoulSource)) {
    $SoulSource = Join-Path $InstallDir "packages\worker\SOUL.md"
}
if (Test-Path $SoulSource) {
    Copy-Item $SoulSource (Join-Path $InstallDir "SOUL.md") -Force
    Write-OK "SOUL.md copied to $InstallDir"
} else {
    # Download from repo if not cloned
    try {
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/packages/worker/SOUL.md" -OutFile (Join-Path $InstallDir "SOUL.md") -UseBasicParsing 2>$null
        Write-OK "SOUL.md downloaded"
    } catch {
        Write-Warn "Could not get SOUL.md — Codex will work but without full instructions"
    }
}

# Build the context prompt — just point to SOUL.md
$UserName = $env:USERNAME
$ContextPrompt = @"
Read SOUL.md in this directory. It contains your complete instructions.
You are ApplyLoop for $UserName. Follow SOUL.md exactly.
Start by greeting the user, then begin the scout→filter→apply loop.
Do NOT run worker.py — YOU are the worker. Call openclaw browser commands directly.
Profile is in profile.json. Learnings are in packages\worker\knowledge\learnings.md.

## INTRODUCE YOURSELF FIRST
When the user opens this chat, immediately say:

"Hi $UserName! I'm your ApplyLoop assistant. Here's what I can do for you:

**Job Scouting** — I search 6 job boards every 30 minutes:
- Ashby (51 companies: Perplexity, Cohere, Notion, Cursor, Ramp...)
- Greenhouse (68 companies: Coinbase, Figma, Datadog, Waymo, DoorDash...)
- Indeed (massive volume across all companies)
- Himalayas (remote-focused roles)
- Google Jobs (fresh postings with salary data)
- LinkedIn (public search)

**Smart Filtering** — I only show you relevant roles:
- AI/ML/Data roles matching your preferences
- US locations, posted in last 24 hours
- Skip senior roles at big tech, skip management/VP/intern
- Max 5 applications per company per month

**Auto-Apply** — I fill out applications for you:
- Open each job form, read every field
- Fill in your full profile (work history, education, skills)
- Upload your resume automatically
- Submit and take a screenshot as proof
- Send you a Telegram notification for each submission

**Commands you can use:**
- **start** — begin scouting and auto-applying
- **scout** — scan job boards right now
- **status** — show your profile and what's configured
- **apply to [URL]** — apply to a specific job
- **stop** — pause the worker
- **update** — pull latest improvements

Would you like me to start scouting for jobs now?"

## SETUP CHECK (do this silently before introducing yourself)
1. Check if packages\worker\worker.py exists. If not:
   git clone https://github.com/snehitvaddi/AutoApply.git $InstallDir\repo
   xcopy $InstallDir\repo\* $InstallDir\ /E /Y /I
2. Check .env has WORKER_TOKEN set
3. Check profile.json has user data (if empty, fetch via: curl -s -H "X-Worker-Token: TOKEN" https://applyloop.vercel.app/api/settings/cli-config)
4. Fix any issues silently, then greet the user

## WHEN USER SAYS "start" or "scout"
Run: cd $InstallDir\packages\worker && $PythonCmd worker.py

## WHEN USER SAYS "status"
Read profile.json and .env, show:
- Name, email, target roles
- How many resumes uploaded
- Telegram connected? (check TELEGRAM_CHAT_ID in .env)
- Worker token set?
- Last scout results if available

## WHEN USER SAYS "apply to [URL]"
Run the applier directly on that URL using the worker's apply logic.

## APPLYING RULES (critical)
- ONE job at a time — fill every field, verify success before next
- Fill ALL work experiences and ALL education — never truncate
- Short answers for basic fields (sponsorship, salary, location)
- Long 3-4 sentence answers ONLY for "Why interested?" type questions
- Upload resume via JS/CLI, never file explorer
- Screenshot after submission → Telegram notification

## REMAINING SETUP (guide user if needed)
- **Telegram**: message @ApplyLoopBot on Telegram → send /start → copy Chat ID → paste in Settings > Telegram on applyloop.vercel.app
- **Gmail (optional)**: go to applyloop.vercel.app → Settings → Email → Connect Gmail (for reading verification codes)
- **Himalaya (optional)**: for power users — go to myaccount.google.com/apppasswords → create app password → configure himalaya
- **AgentMail (optional)**: sign up at agentmail.to → get API key → add AGENTMAIL_API_KEY to .env

## TECHNICAL DETAILS (don't show to user unless asked)
- .env: $EnvFile
- Install dir: $InstallDir
- Python: $PythonCmd
- Profile: $InstallDir\profile.json
- Worker uses API proxy via WORKER_TOKEN (no Supabase service key needed)
- Codex subscription covers LLM (no OpenAI API key needed)
- Database migrations handled by admin (not user)

## AUTO-START BEHAVIOR
When you launch, do this IMMEDIATELY without waiting for user input:
1. Silently check if packages\worker\worker.py exists — if not, clone the repo
2. Silently check .env has WORKER_TOKEN — if not, ask for it once
3. Greet the user with your capabilities (the intro message above)
4. Then say: "Starting the scout→apply loop now..."
5. Run: cd $InstallDir\packages\worker && $PythonCmd worker.py
6. The worker runs an INFINITE LOOP: scout every 30 min → filter → apply → telegram notify → repeat
7. While the worker runs, relay its output to the user in plain language:
   - "Scanning 51 Ashby boards..."
   - "Found 12 matching jobs"
   - "Applying to [Company] - [Role]..."
   - "✅ Applied to [Company]! Screenshot sent to Telegram."
8. If the user types anything while the worker is running, pause to respond, then resume
9. NEVER stop the loop unless the user says "stop"
"@

if ($LlmCliCmd -eq "claude") {
    Write-OK "Launching Claude Code to complete setup..."
    Write-Host ""
    Write-Host "  Claude will help you finish configuring ApplyLoop." -ForegroundColor Cyan
    Write-Host "  You can paste credentials, ask questions, or type 'exit' to quit." -ForegroundColor Cyan
    Write-Host ""

    # Set API key env var if available (for API access type)
    if ($LlmApiKey -and $LlmAccessType -eq "api") {
        $env:ANTHROPIC_API_KEY = $LlmApiKey
    }

    claude --cd $InstallDir $ContextPrompt

} elseif ($LlmCliCmd -eq "codex") {
    Write-OK "Launching Codex to complete setup..."
    Write-Host ""
    Write-Host "  Codex will help you finish configuring ApplyLoop." -ForegroundColor Cyan
    Write-Host "  You can paste credentials, ask questions, or type 'exit' to quit." -ForegroundColor Cyan
    Write-Host ""

    # Set API key env var if available (for API access type)
    if ($LlmApiKey -and $LlmAccessType -eq "api") {
        $env:OPENAI_API_KEY = $LlmApiKey
    }

    codex --approval-mode full-auto --cd $InstallDir $ContextPrompt

} else {
    # ── Fallback: No CLI available — show interactive status dashboard ────────
    Write-Warn "No AI CLI available — showing setup status manually."
    Write-Host ""

    # Print the status dashboard to console (fallback for no-CLI users)
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
    Write-Status $pwOk "Playwright" ""
    Write-Status $sbOk "Supabase SDK" ""
    Write-Status $hxOk "httpx" ""

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
    Write-EnvStatus "SUPABASE_SERVICE_ROLE_KEY" "Supabase Service   (not needed - API proxy)"
    Write-EnvStatus "ENCRYPTION_KEY" "Encryption Key     (required)"
    Write-EnvStatus "WORKER_ID" "Worker ID          (required)"
    Write-EnvStatus "TELEGRAM_BOT_TOKEN" "Telegram Bot Token (optional)"
    Write-EnvStatus "STRIPE_SECRET_KEY" "Stripe Secret Key  (optional)"
    Write-EnvStatus "GOOGLE_CLIENT_ID" "Google OAuth       (optional)"

    Write-Host ""
    Write-Host "  LLM Config:" -ForegroundColor White
    Write-EnvStatus "LLM_PROVIDER" "LLM Provider       (required)"
    Write-EnvStatus "LLM_MODEL" "LLM Model          (required)"
    Write-EnvStatus "LLM_BACKEND_PROVIDER" "LLM Backend Prov   (required)"
    Write-EnvStatus "LLM_BACKEND_MODEL" "LLM Backend Model  (required)"
    Write-EnvStatus "ANTHROPIC_API_KEY" "Anthropic Key      (if Claude)"
    Write-EnvStatus "OPENAI_API_KEY" "OpenAI Key         (if GPT)"

    Write-Host ""
    Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White
    Write-Host "║  SERVICES & CONNECTIONS                                     ║" -ForegroundColor White
    Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

    if ($sbConnected) {
        Write-Host ("  [ONLINE]  {0,-22}" -f "Supabase API") -ForegroundColor Green
    } else {
        Write-Host ("  [OFFLINE] {0,-22} <-- check URL/keys" -f "Supabase API") -ForegroundColor Yellow
    }

    if (Test-Path $workerPath) {
        Write-Host ("  [READY]   {0,-22}" -f "Worker code") -ForegroundColor Green
    } else {
        Write-Host ("  [MISSING] {0,-22} <-- repo not cloned?" -f "Worker code") -ForegroundColor Yellow
    }

    Write-Status (Test-Path $resumeDir) "Worker directories" ""

    Write-Host ""
    Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White
    Write-Host "║  STILL TODO                                                 ║" -ForegroundColor White
    Write-Host "╠──────────────────────────────────────────────────────────────╣" -ForegroundColor White

    foreach ($line in $todoLines) {
        if ($line -match "^\d+\.") {
            Write-Host "  $line" -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor White
    Write-Host ""

    # Interactive fallback — offer worker token or manual Supabase entry
    if (-not $hasSbUrl) {
        Write-Host ""
        Write-Host "Would you like to enter your worker token now?" -ForegroundColor White
        $enterToken = Read-Host "  [y/N]"
        if ($enterToken -eq "y" -or $enterToken -eq "Y") {
            $FallbackToken = Read-Host "  Worker token (from admin)"
            Write-Info "Fetching credentials from ApplyLoop..."
            try {
                $resp = Invoke-RestMethod -Uri "$AppUrl/api/settings/cli-config" -Headers @{ "X-Worker-Token" = $FallbackToken } -ErrorAction Stop
                if ($resp.data) {
                    (Get-Content $EnvFile) -replace '^WORKER_TOKEN=.*', "WORKER_TOKEN=$FallbackToken" `
                                           -replace '^NEXT_PUBLIC_SUPABASE_URL=.*', "NEXT_PUBLIC_SUPABASE_URL=$($resp.data.supabase_url)" `
                                           -replace '^SUPABASE_URL=.*', "SUPABASE_URL=$($resp.data.supabase_url)" `
                                           -replace '^NEXT_PUBLIC_SUPABASE_ANON_KEY=.*', "NEXT_PUBLIC_SUPABASE_ANON_KEY=$($resp.data.supabase_anon_key)" | Set-Content $EnvFile
                    Write-OK "Credentials fetched and saved to .env"
                } else { throw "No data" }
            } catch {
                Write-Warn "Could not fetch — entering manually"
                $SupabaseUrl = Read-Host "  Supabase URL"
                $SupabaseAnon = Read-Host "  Supabase Anon Key"
                if ($SupabaseUrl) {
                    (Get-Content $EnvFile) -replace '^NEXT_PUBLIC_SUPABASE_URL=.*', "NEXT_PUBLIC_SUPABASE_URL=$SupabaseUrl" `
                                           -replace '^SUPABASE_URL=.*', "SUPABASE_URL=$SupabaseUrl" | Set-Content $EnvFile
                }
                if ($SupabaseAnon) {
                    (Get-Content $EnvFile) -replace '^NEXT_PUBLIC_SUPABASE_ANON_KEY=.*', "NEXT_PUBLIC_SUPABASE_ANON_KEY=$SupabaseAnon" | Set-Content $EnvFile
                }
                Write-OK "Credentials saved to .env"
            }
        }
    }

    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor White
    Write-Host ""
    Write-Host "  1. Edit .env with remaining credentials:" -ForegroundColor White
    Write-Host "     notepad $EnvFile" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  2. Start the worker:" -ForegroundColor White
    Write-Host "     cd $InstallDir\packages\worker" -ForegroundColor Cyan
    Write-Host "     $PythonCmd worker.py" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  3. Start the web app (development):" -ForegroundColor White
    Write-Host "     cd $InstallDir\packages\web" -ForegroundColor Cyan
    Write-Host "     npm run dev" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Full context saved to: $AgentsMdPath" -ForegroundColor Yellow
    Write-Host "  Run this status check anytime: powershell $InstallDir\status.ps1" -ForegroundColor Cyan
    Write-Host "  Need help? See docs\CLIENT-ONBOARDING.md" -ForegroundColor Yellow
    Write-Host ""
}
