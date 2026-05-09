<#
.SYNOPSIS
    ApplyLoop installer for Windows 10/11.

.DESCRIPTION
    PowerShell port of install.sh. Handles activation, dependency bootstrap
    (winget for Python/Node/Git, npm for openclaw + claude-code), repo clone,
    venv setup, UI build, cloud config fetch, profile.json + .env generation,
    .exe build, CLI shim, and Task Scheduler auto-update job.

.USAGE
    Recommended one-liner (run in an elevated PowerShell window):
        irm https://applyloop.vercel.app/install.ps1 | iex

    With activation code via env var:
        $env:APPLYLOOP_CODE = "AL-XXXX-XXXX"; irm https://applyloop.vercel.app/install.ps1 | iex

    Or download and run manually:
        iwr https://applyloop.vercel.app/install.ps1 -OutFile install.ps1
        .\install.ps1 -Code AL-XXXX-XXXX

.NOTES
    Requires Windows 10 1809+ (for ConPTY/winget).
    Mirrors install.sh feature-for-feature where possible.
#>
[CmdletBinding()]
param(
    [string]$Code = "",
    [string]$Branch = "main",
    [string]$RepoUrl = "https://github.com/snehitvaddi/ApplyLoop"
)

$ErrorActionPreference = "Stop"

# ─── Logging helpers ────────────────────────────────────────────────────────
function Write-Log    ($msg) { Write-Host "[applyloop] $msg" -ForegroundColor Cyan }
function Write-Warn   ($msg) { Write-Host "[applyloop] WARN: $msg" -ForegroundColor Yellow }
function Write-Err    ($msg) { Write-Host "[applyloop] ERROR: $msg" -ForegroundColor Red }
function Die          ($msg) { Write-Err $msg; exit 1 }

# ─── Constants ──────────────────────────────────────────────────────────────
$AppUrl         = if ($env:NEXT_PUBLIC_APP_URL) { $env:NEXT_PUBLIC_APP_URL } else { "https://applyloop.vercel.app" }
$ApplyloopHome  = if ($env:APPLYLOOP_HOME) { $env:APPLYLOOP_HOME } else { Join-Path $env:USERPROFILE ".applyloop" }
$WorkspaceDir   = Join-Path $env:USERPROFILE ".autoapply\workspace"
$LocalBinDir    = Join-Path $env:LOCALAPPDATA "Programs\ApplyLoop"

Write-Log "ApplyLoop install starting"
Write-Log "  AppUrl   = $AppUrl"
Write-Log "  Home     = $ApplyloopHome"
Write-Log "  WS       = $WorkspaceDir"

# ─── Phase A: Activation gate ───────────────────────────────────────────────
$WorkerToken = ""
$ActUserId = ""
$ActEmail = ""
$ActName = ""
$ActProfileJson = ""
$ActTelegramChat = ""

if ($env:APPLYLOOP_SKIP_ACTIVATION) {
    Write-Warn "APPLYLOOP_SKIP_ACTIVATION set — skipping code gate (dev mode)"
} else {
    if (-not $Code) { $Code = $env:APPLYLOOP_CODE }
    if (-not $Code) {
        Write-Host ""
        Write-Host "Before we begin, paste your activation code." -ForegroundColor White
        Write-Host "  (Get this from $AppUrl after admin approval.)" -ForegroundColor Blue
        Write-Host ""
        $Code = Read-Host "  Activation code (AL-XXXX-XXXX)"
        Write-Host ""
    }
    $Code = $Code.ToUpper().Trim()
    if (-not ($Code -match '^AL-[A-Z0-9]{4}-[A-Z0-9]{4}$')) {
        Die "Invalid code format: '$Code'. Expected AL-XXXX-XXXX."
    }

    Write-Log "Validating activation code against $AppUrl..."
    try {
        $hostname = $env:COMPUTERNAME
        $body = @{ code = $Code; install_id = $hostname; app_version = "install.ps1" } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$AppUrl/api/activate" -Method Post `
            -ContentType "application/json" -Body $body -ErrorAction Stop
    } catch {
        $errBody = $_.ErrorDetails.Message
        Die "Activation failed: $errBody`n  Possible causes:`n   1. Code mistyped`n   2. Code revoked or expired`n   3. uses_remaining = 0`n   4. Account not yet approved"
    }

    $data = $resp.data
    if (-not $data.worker_token) { Die "Activation succeeded but no worker_token in response — contact admin" }

    $WorkerToken     = $data.worker_token
    $ActUserId       = $data.user_id
    $ActEmail        = if ($data.email) { $data.email } else { "" }
    $ActName         = if ($data.full_name) { $data.full_name } else { "" }
    $ActTelegramChat = if ($data.telegram_chat_id) { $data.telegram_chat_id } else { "" }
    $ActProfileJson  = $resp | ConvertTo-Json -Depth 20

    $who = if ($ActName) { $ActName } else { $ActEmail }
    Write-Log "Code verified for $who (user $ActUserId)"
}

# ─── Phase B: Dependency bootstrap (winget) ─────────────────────────────────
function Test-Cmd($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Ensure-Winget {
    if (-not (Test-Cmd "winget")) {
        Die "winget not found. Install 'App Installer' from Microsoft Store first, or use Win10 1809+/Win11."
    }
    Write-Log "winget available: $(winget --version)"
}

function Ensure-WingetPackage($id, $friendly) {
    Write-Log "Ensuring $friendly is installed..."
    $exists = winget list --id $id --exact 2>$null | Select-String $id
    if ($exists) {
        Write-Log "  $friendly already installed"
        return
    }
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "$friendly install via winget reported non-zero exit; verifying..."
    }
}

Ensure-Winget
Ensure-WingetPackage "Python.Python.3.12" "Python 3.12"
Ensure-WingetPackage "OpenJS.NodeJS"      "Node.js 20"
Ensure-WingetPackage "Git.Git"            "Git"

# Refresh PATH so newly-installed tools are visible to this session.
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + `
            [System.Environment]::GetEnvironmentVariable("PATH", "User")

foreach ($tool in @("python", "node", "npm", "git")) {
    if (-not (Test-Cmd $tool)) {
        Die "$tool still not on PATH after winget install. Open a new PowerShell window and rerun."
    }
}

# Claude Code (via npm — the "claude" Homebrew formula is unrelated and
# wouldn't apply on Windows anyway)
if (Test-Cmd "claude") {
    $claudeVer = & claude --version 2>&1 | Out-String
    if ($claudeVer -match 'anthropic|claude code') {
        Write-Log "claude already installed (Anthropic Claude Code)"
    } else {
        Write-Log "Replacing non-Anthropic claude with Claude Code"
        npm install -g @anthropic-ai/claude-code 2>&1 | Out-Null
    }
} else {
    Write-Log "Installing Claude Code via npm"
    npm install -g @anthropic-ai/claude-code 2>&1 | Out-Null
}

# OpenClaw (browser automation backbone, also via npm)
$openclawInstalled = npm ls -g --depth=0 openclaw 2>$null | Select-String "openclaw@"
if ($openclawInstalled) {
    Write-Log "openclaw already installed (npm global)"
} else {
    Write-Log "Installing openclaw via npm"
    npm install -g openclaw --no-fund --no-audit 2>&1 | Out-Null
}

# Write minimal openclaw config — same as install.sh
$ocDir = Join-Path $env:USERPROFILE ".openclaw"
$ocConfig = Join-Path $ocDir "openclaw.json"
New-Item -ItemType Directory -Force -Path (Join-Path $ocDir "workspace") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ocDir "agents\main\sessions") | Out-Null
if (-not (Test-Path $ocConfig)) {
    Write-Log "Writing $ocConfig"
    $gwToken = -join ((1..24) | ForEach-Object { '{0:x2}' -f (Get-Random -Min 0 -Max 256) })
    $nowIso = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $ocJson = @"
{
  "meta": { "lastTouchedVersion": "2026.5.9", "lastTouchedAt": "$nowIso" },
  "wizard": { "lastRunAt": "$nowIso", "lastRunMode": "local", "lastRunCommand": "applyloop-install" },
  "browser": {
    "defaultProfile": "openclaw",
    "profiles": { "openclaw": { "cdpPort": 18800, "color": "#0066CC" } }
  },
  "gateway": {
    "port": 18789, "mode": "local", "bind": "loopback",
    "auth": { "mode": "token", "token": "$gwToken" }
  },
  "commands": { "native": "auto", "nativeSkills": "auto" }
}
"@
    Set-Content -Path $ocConfig -Value $ocJson -Encoding UTF8
}
# Best-effort gateway setup — no launchd equivalent on Windows; openclaw
# itself handles the start. The desktop server will spawn it on demand if
# this fails.
& openclaw gateway start 2>&1 | Out-Null

# ─── Phase C: Clone / update repo ───────────────────────────────────────────
$parentDir = Split-Path $ApplyloopHome -Parent
New-Item -ItemType Directory -Force -Path $parentDir | Out-Null

if (Test-Path (Join-Path $ApplyloopHome ".git")) {
    Write-Log "Existing install at $ApplyloopHome — fetching $Branch"
    git -C $ApplyloopHome fetch origin $Branch
    git -C $ApplyloopHome reset --hard "origin/$Branch"
} else {
    Write-Log "Cloning $RepoUrl (branch=$Branch) → $ApplyloopHome"
    git clone --depth 1 --branch $Branch $RepoUrl $ApplyloopHome
}

# ─── Phase D: Python venv + deps ────────────────────────────────────────────
$VenvDir = Join-Path $ApplyloopHome "venv"
$VenvPy  = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Log "Creating venv at $VenvDir"
    python -m venv $VenvDir
}
if (-not (Test-Path $VenvPy)) { Die "venv creation failed — $VenvPy missing" }

Write-Log "Upgrading pip"
& $VenvPip install --quiet --upgrade pip

Write-Log "Installing desktop + worker python deps"
& $VenvPip install `
    -r (Join-Path $ApplyloopHome "packages\desktop\requirements.txt") `
    -r (Join-Path $ApplyloopHome "packages\worker\requirements.txt")

# Install pyinstaller separately so build.py --win works for local rebuilds
& $VenvPip install --quiet "pyinstaller>=6.0"

# ─── Phase E: UI build ──────────────────────────────────────────────────────
Write-Log "Building static Next.js UI"
$uiDir = Join-Path $ApplyloopHome "packages\desktop\ui"
Push-Location $uiDir
try {
    npm install --no-fund --no-audit
    npm run build
} finally {
    Pop-Location
}

# ─── Phase F: Cloud config + profile.json ───────────────────────────────────
$TelegramBotToken = ""
$SupabaseUrl = ""
$SupabaseAnonKey = ""
$CliConfigJson = ""
$AgentmailKey = ""
$FinetuneKey = ""
$GmailEmail = ""
$GmailAppPw = ""

if ($WorkerToken) {
    Write-Log "Fetching cli-config..."
    try {
        $cfg = Invoke-RestMethod -Uri "$AppUrl/api/settings/cli-config" `
            -Headers @{ "X-Worker-Token" = $WorkerToken } -ErrorAction Stop
        $CliConfigJson = $cfg | ConvertTo-Json -Depth 20
        $d = $cfg.data
        if ($d.telegram_bot_token) { $TelegramBotToken = $d.telegram_bot_token }
        if ($d.supabase_url)       { $SupabaseUrl       = $d.supabase_url }
        if ($d.supabase_anon_key)  { $SupabaseAnonKey   = $d.supabase_anon_key }
        if (-not $ActTelegramChat -and $d.telegram_chat_id) { $ActTelegramChat = $d.telegram_chat_id }
    } catch {
        Write-Warn "cli-config fetch failed: $($_.Exception.Message) — Telegram + Supabase config will be empty"
    }

    Write-Log "Fetching saved integrations..."
    try {
        $intResp = Invoke-RestMethod -Uri "$AppUrl/api/settings/integrations?raw=1" `
            -Headers @{ "X-Worker-Token" = $WorkerToken } -ErrorAction Stop
        $i = $intResp.data.integrations
        if ($i.telegram_bot_token)     { $TelegramBotToken = $i.telegram_bot_token }
        if ($i.telegram_chat_id -and -not $ActTelegramChat) { $ActTelegramChat = $i.telegram_chat_id }
        if ($i.gmail_email)            { $GmailEmail = $i.gmail_email }
        if ($i.gmail_app_password)     { $GmailAppPw = $i.gmail_app_password }
        if ($i.agentmail_api_key)      { $AgentmailKey = $i.agentmail_api_key }
        if ($i.finetune_resume_api_key){ $FinetuneKey = $i.finetune_resume_api_key }
        $filled = @($TelegramBotToken, $ActTelegramChat, $GmailEmail, $GmailAppPw, $AgentmailKey, $FinetuneKey) | Where-Object { $_ }
        if ($filled.Count -gt 0) { Write-Log "  Loaded $($filled.Count) integration(s) from cloud" }
    } catch {
        Write-Log "  No saved integrations (or endpoint unavailable)"
    }
}

# Transform activate + cli-config into the nested profile.json shape via
# Python (mirrors install.sh exactly so behavior is identical).
if ($ActProfileJson) {
    Write-Log "Writing profile.json"
    $actTmp = Join-Path $env:TEMP "applyloop-activate.json"
    $cfgTmp = Join-Path $env:TEMP "applyloop-cliconfig.json"
    Set-Content -Path $actTmp -Value $ActProfileJson -Encoding UTF8
    Set-Content -Path $cfgTmp -Value $CliConfigJson -Encoding UTF8
    $env:APPLYLOOP_HOME_FOR_PY = $ApplyloopHome
    $env:ACTIVATE_PATH = $actTmp
    $env:CLI_CONFIG_PATH = $cfgTmp
    $pyTransform = @'
import json, os

def load(path):
    try:
        with open(path) as f:
            return json.loads(f.read()).get("data", {}) or {}
    except Exception:
        return {}

act = load(os.environ["ACTIVATE_PATH"])
cfg = load(os.environ.get("CLI_CONFIG_PATH", ""))
cfg_profile = cfg.get("profile") or {}
act_profile = act.get("profile") or {}
cfg_prefs = cfg.get("preferences") or {}
act_prefs = act.get("preferences") or {}

def pick(key, default=None):
    v = cfg_profile.get(key)
    if v not in (None, "", [], {}):
        return v
    return act_profile.get(key) if act_profile.get(key) not in (None, "") else default

user_id = act.get("user_id") or (cfg.get("user", {}) or {}).get("id") or ""
email = act.get("email") or (cfg.get("user", {}) or {}).get("email") or ""
full_name = act.get("full_name") or (cfg.get("user", {}) or {}).get("full_name") or ""
tier = act.get("tier") or cfg.get("tier") or ""

profile = {
  "user": {"id": user_id, "email": email, "full_name": full_name, "tier": tier},
  "personal": {
    "first_name": pick("first_name", "") or "",
    "last_name": pick("last_name", "") or "",
    "email": email,
    "phone": pick("phone", "") or "",
    "linkedin_url": pick("linkedin_url", "") or "",
    "github_url": pick("github_url", "") or "",
    "portfolio_url": pick("portfolio_url", "") or "",
  },
  "work": {
    "current_company": pick("current_company", "") or "",
    "current_title": pick("current_title", "") or "",
    "years_experience": pick("years_experience", "") or "",
  },
  "legal": {
    "work_authorization": pick("work_authorization", "") or "",
    "requires_sponsorship": pick("requires_sponsorship", False) or False,
  },
  "eeo": {
    "gender": pick("gender", "") or "",
    "race_ethnicity": pick("race_ethnicity", "") or "",
    "veteran_status": pick("veteran_status", "") or "",
    "disability_status": pick("disability_status", "") or "",
  },
  "experience": pick("work_experience", []) or [],
  "education": pick("education", "") or "",
  "education_summary": {
    "education_level": pick("education_level", "") or "",
    "school_name": pick("school_name", "") or "",
    "degree": pick("degree", "") or "",
    "graduation_year": pick("graduation_year", "") or "",
  },
  "skills": pick("skills", []) or [],
  "standard_answers": pick("answer_key_json", {}) or {},
  "cover_letter_template": pick("cover_letter_template", "") or "",
  "preferences": cfg_prefs or act_prefs or {},
  "resumes": [act.get("default_resume")] if act.get("default_resume") else [],
}

home = os.environ["APPLYLOOP_HOME_FOR_PY"]
os.makedirs(home, exist_ok=True)
with open(os.path.join(home, "profile.json"), "w") as f:
    json.dump(profile, f, indent=2)
print(f"  wrote {len(profile['experience'])} experience, {len(profile['skills'])} skills")
'@
    $pyScript = Join-Path $env:TEMP "applyloop-profile-transform.py"
    Set-Content -Path $pyScript -Value $pyTransform -Encoding UTF8
    & $VenvPy $pyScript
    Remove-Item $actTmp, $cfgTmp, $pyScript -ErrorAction SilentlyContinue
}

# Persist worker token to disk where desktop wizard expects it
$TokenFile = Join-Path $WorkspaceDir ".api-token"
New-Item -ItemType Directory -Force -Path $WorkspaceDir | Out-Null
if ($WorkerToken) {
    Set-Content -Path $TokenFile -Value $WorkerToken -Encoding UTF8 -NoNewline
    # Owner-only ACL (Windows equivalent of chmod 600). Best-effort.
    try {
        icacls $TokenFile /inheritance:r /grant:r "$($env:USERNAME):F" 2>&1 | Out-Null
    } catch {}
    Write-Log "Worker token saved to $TokenFile"
}

# ─── Phase G: Write .env ────────────────────────────────────────────────────
$EnvFile = Join-Path $ApplyloopHome ".env"
$EncryptionKey = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Min 0 -Max 256) })
$WorkerId = "worker-$($env:COMPUTERNAME.ToLower())-$(Get-Random)"

Write-Log "Writing $EnvFile"
$resumeDir = Join-Path $WorkspaceDir "resumes"
$screenshotDir = Join-Path $WorkspaceDir "screenshots"
$dbPath = Join-Path $WorkspaceDir "applications.db"
$envContent = @"
# ApplyLoop runtime config — generated by install.ps1 on $((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))
# Read by the desktop launcher and worker subprocess on Windows.
# Edit carefully. To regenerate: rerun install.ps1.

# ── Auth (REQUIRED) ────────────────────────────────────────────────
WORKER_TOKEN=$WorkerToken

# Tenant identity — worker.py main() reads this and loads TenantConfig.
APPLYLOOP_USER_ID=$ActUserId

# ── App ────────────────────────────────────────────────────────────
NEXT_PUBLIC_APP_URL=$AppUrl
APPLYLOOP_HOME=$ApplyloopHome
ENCRYPTION_KEY=$EncryptionKey

# ── Supabase (shared admin instance) ──────────────────────────────
NEXT_PUBLIC_SUPABASE_URL=$SupabaseUrl
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SupabaseAnonKey
SUPABASE_URL=$SupabaseUrl
SUPABASE_SERVICE_KEY=$SupabaseAnonKey

# ── Worker tuning ─────────────────────────────────────────────────
WORKER_ID=$WorkerId
POLL_INTERVAL=10
APPLY_COOLDOWN=30
APPLYLOOP_WORKSPACE=$WorkspaceDir
APPLYLOOP_DB=$dbPath
RESUME_DIR=$resumeDir
SCREENSHOT_DIR=$screenshotDir

# ── Telegram ──────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=$TelegramBotToken
TELEGRAM_CHAT_ID=$ActTelegramChat

# ── Optional integrations ─────────────────────────────────────────
AGENTMAIL_API_KEY=$AgentmailKey
FINETUNE_RESUME_API_KEY=$FinetuneKey
GMAIL_EMAIL=$GmailEmail
GMAIL_APP_PASSWORD=$GmailAppPw
"@
Set-Content -Path $EnvFile -Value $envContent -Encoding UTF8
try {
    icacls $EnvFile /inheritance:r /grant:r "$($env:USERNAME):F" 2>&1 | Out-Null
} catch {}

# CLIENT.md (preserved across updates — never overwrite)
$ClientMd = Join-Path $ApplyloopHome "CLIENT.md"
if (-not (Test-Path $ClientMd)) {
    $clientContent = @"
# CLIENT.md — Your personal overrides
#
# This file is NEVER overwritten by 'applyloop update'.
# Add anything here that should take precedence over the global rules.
#
# Examples:
#   - Companies to exclude beyond preferences
#   - Title preferences / blacklist
#   - Cover letter tone notes
#   - One-off form-fill instructions
#
# Lines starting with # are comments and are ignored by Claude.
"@
    Set-Content -Path $ClientMd -Value $clientContent -Encoding UTF8
    Write-Log "Created $ClientMd"
}

# Worker runtime dirs
New-Item -ItemType Directory -Force -Path $resumeDir, $screenshotDir | Out-Null

# Cache resume PDF
if ($WorkerToken) {
    Write-Log "Downloading resume PDF for local Claude parsing"
    $resumeTarget = Join-Path $resumeDir "default.pdf"
    try {
        Invoke-WebRequest -Uri "$AppUrl/api/onboarding/resume/download" `
            -Headers @{ "X-Worker-Token" = $WorkerToken } `
            -OutFile $resumeTarget -ErrorAction Stop
        $head = [System.IO.File]::ReadAllBytes($resumeTarget)[0..3] -join ","
        if ($head -eq "37,80,68,70") {  # %PDF
            $size = (Get-Item $resumeTarget).Length
            Write-Log "  Resume cached — $size bytes"
        } else {
            Write-Warn "Downloaded resume isn't a valid PDF, deleting"
            Remove-Item $resumeTarget -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warn "Resume download failed — Claude will ask interactively on first launch"
    }
}

# ─── Phase H: AGENTS.md + .claude/settings.json ─────────────────────────────
$AgentsFile = Join-Path $ApplyloopHome "AGENTS.md"
Write-Log "Writing $AgentsFile"
$hasTelegram = if ($ActTelegramChat -and $TelegramBotToken) { "yes ($ActTelegramChat)" } else { "no" }
$hasAgentmail = if ($AgentmailKey) { "yes" } else { "no" }
$hasFinetune  = if ($FinetuneKey) { "yes" } else { "no" }
$hasGmail     = if ($GmailEmail) { "yes ($GmailEmail)" } else { "no" }
$pyVenvPath   = $VenvPy

$agentsContent = @"
# ApplyLoop — Agent Context (Windows)

You are the ApplyLoop job application agent running on Windows.

## System info

- Install directory: ``$ApplyloopHome``
- Python venv: ``$pyVenvPath``
- Profile: ``$ApplyloopHome\profile.json`` — read this FIRST
- Playbook: ``$ApplyloopHome\packages\worker\SOUL.md``
- Config env: ``$ApplyloopHome\.env``
- Workspace: ``$WorkspaceDir``
- User: ${ActName}
- Email: ${ActEmail}

## Configured integrations

- Telegram: $hasTelegram
- AgentMail: $hasAgentmail
- Finetune: $hasFinetune
- Gmail: $hasGmail

## Your role

You own the complete pipeline end-to-end via MCP tool calls:
SCOUT → FILTER → ENQUEUE → APPLY → CONFIRM → SCREENSHOT → LOG → TELEGRAM

1. Read profile.json first.
2. Read SOUL.md for the full playbook.
3. Greet the user, then start the pipeline. Do NOT wait for "start".
4. On "status": show profile + last scout/apply stats + integrations.
5. On "apply to <URL>": apply directly via browser MCP tools.
6. On "stop": stop the loop, send a session summary via Telegram.

## Platform notes (Windows)

- Paths use ``\`` separators. Code uses pathlib so this is invisible.
- Local SQLite at ``$dbPath`` is the source of truth.
- Use ``tempfile.gettempdir()`` for temp paths (resolves to %TEMP%).
- ``keep_awake.start()`` is no-op on non-Windows — on Windows it
  blocks sleep via SetThreadExecutionState during applies.
"@
Set-Content -Path $AgentsFile -Value $agentsContent -Encoding UTF8

# .claude/settings.json — register MCP server
$ClaudeDir = Join-Path $ApplyloopHome ".claude"
New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
$ClaudeSettings = Join-Path $ClaudeDir "settings.json"
$workerCwd = Join-Path $ApplyloopHome "packages\worker"
# Escape backslashes for JSON
$pyEscaped = $VenvPy -replace '\\', '\\'
$cwdEscaped = $workerCwd -replace '\\', '\\'
$homeEscaped = $ApplyloopHome -replace '\\', '\\'

$claudeJson = @"
{
  "mcpServers": {
    "applyloop": {
      "command": "$pyEscaped",
      "args": ["-m", "brain.mcp_server"],
      "env": {
        "PYTHONPATH": "$cwdEscaped",
        "APPLYLOOP_USER_ID": "$ActUserId",
        "APPLYLOOP_HOME": "$homeEscaped"
      },
      "cwd": "$cwdEscaped"
    }
  }
}
"@
Set-Content -Path $ClaudeSettings -Value $claudeJson -Encoding UTF8
Write-Log "Wrote $ClaudeSettings"

# ─── Phase I: Build the .exe ───────────────────────────────────────────────
Write-Log "Building Windows .exe via packages\desktop\build.py --win"
$buildScript = Join-Path $ApplyloopHome "packages\desktop\build.py"
Push-Location (Split-Path $buildScript)
try {
    & $VenvPy $buildScript --win --skip-ui
} finally {
    Pop-Location
}

# ─── Phase J: CLI shim + PATH ──────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LocalBinDir | Out-Null
$ShimPath = Join-Path $LocalBinDir "applyloop.cmd"

# Find the built ApplyLoop.exe
$ExePath = Get-ChildItem -Path (Join-Path $ApplyloopHome "packages\desktop\dist\windows") `
    -Recurse -Filter "ApplyLoop.exe" -ErrorAction SilentlyContinue | Select-Object -First 1

if ($ExePath) {
    $exeFullPath = $ExePath.FullName
    $shimContent = @"
@echo off
REM ApplyLoop CLI shim — generated by install.ps1
"$exeFullPath" %*
"@
    Set-Content -Path $ShimPath -Value $shimContent -Encoding ASCII
    Write-Log "CLI shim → $ShimPath"
} else {
    Write-Warn ".exe build did not produce ApplyLoop.exe at expected path; CLI shim skipped"
}

# Add LocalBinDir to user PATH (idempotent)
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if (-not ($userPath -split ";" | Where-Object { $_ -eq $LocalBinDir })) {
    Write-Log "Adding $LocalBinDir to user PATH"
    $newPath = if ($userPath) { "$userPath;$LocalBinDir" } else { $LocalBinDir }
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    $env:PATH = "$env:PATH;$LocalBinDir"
}

# Version stamp
$version = git -C $ApplyloopHome rev-parse HEAD 2>$null
if ($version) {
    Set-Content -Path (Join-Path $ApplyloopHome ".applyloop-version") -Value $version -Encoding UTF8
}

# ─── Phase K: Auto-update Task Scheduler ───────────────────────────────────
Write-Log "Registering daily auto-update task (3 AM)"
try {
    schtasks /Delete /TN "ApplyLoopUpdate" /F 2>&1 | Out-Null
} catch {}
$updateCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `"& '$ShimPath' update`""
schtasks /Create /TN "ApplyLoopUpdate" /TR $updateCmd /SC DAILY /ST 03:00 /F 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Log "  Daily 3 AM update task registered"
} else {
    Write-Warn "  Could not register Task Scheduler entry — run 'applyloop update' manually"
}

# ─── Success ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ApplyLoop installed successfully" -ForegroundColor Green
Write-Host ""
Write-Host "  Location: $ApplyloopHome"
Write-Host "  Workspace: $WorkspaceDir"
Write-Host "  CLI shim: $ShimPath"
if ($version) { Write-Host "  Version: $($version.Substring(0,12))" }
Write-Host ""
Write-Host "  Next steps:"
if ($ExePath) {
    Write-Host "    1. Launch the app: " -NoNewline
    Write-Host "$($ExePath.FullName)" -ForegroundColor Blue
}
Write-Host "    2. Or from any new PowerShell: " -NoNewline
Write-Host "applyloop start" -ForegroundColor Blue
Write-Host ""
Write-Host "  Update later:    " -NoNewline; Write-Host "applyloop update" -ForegroundColor Blue
Write-Host "  Daily 3 AM auto-update task: ApplyLoopUpdate (Task Scheduler)"
Write-Host ""
