# build_windows_zip.ps1 — Create a portable ApplyLoop-Windows.zip
#
# Usage: powershell -ExecutionPolicy Bypass -File build_windows_zip.ps1
#
# Output: dist/ApplyLoop-windows-portable.zip
# Contains: launch.py, venv/, ui/out/, .bat launcher, requirements
# User extracts, runs ApplyLoop.bat, gets the full desktop experience.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent (Split-Path -Parent $DesktopDir)

Write-Host "Building ApplyLoop Windows portable package..." -ForegroundColor Cyan
Write-Host "  Desktop: $DesktopDir"
Write-Host "  Repo:    $RepoRoot"

$BuildDir = Join-Path $DesktopDir "dist\build"
$DistDir = Join-Path $DesktopDir "dist"

# Clean previous build
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

# 1. Create venv + install deps
Write-Host "  Creating venv..." -ForegroundColor White
python -m venv "$BuildDir\venv"
& "$BuildDir\venv\Scripts\pip" install --quiet -r "$DesktopDir\requirements.txt" 2>&1 | Out-Null
& "$BuildDir\venv\Scripts\pip" install --quiet -r "$RepoRoot\packages\worker\requirements.txt" 2>&1 | Out-Null
Write-Host "  Deps installed" -ForegroundColor Green

# 2. Build UI
Write-Host "  Building UI..." -ForegroundColor White
Push-Location "$DesktopDir\ui"
npm install --silent 2>&1 | Out-Null
npm run build 2>&1 | Out-Null
Pop-Location

# 3. Copy files into build dir
Write-Host "  Copying files..." -ForegroundColor White
# Desktop server + launch
Copy-Item "$DesktopDir\launch.py" $BuildDir
Copy-Item "$DesktopDir\requirements.txt" $BuildDir
Copy-Item -Recurse "$DesktopDir\server" "$BuildDir\server"
Copy-Item -Recurse "$DesktopDir\ui\out" "$BuildDir\ui\out"

# Worker
New-Item -ItemType Directory -Path "$BuildDir\packages\worker" -Force | Out-Null
Copy-Item -Recurse "$RepoRoot\packages\worker\*" "$BuildDir\packages\worker\" -Exclude "__pycache__","*.pyc",".pytest_cache"

# Knowledge
if (Test-Path "$RepoRoot\knowledge") {
    Copy-Item -Recurse "$RepoRoot\knowledge" "$BuildDir\knowledge"
}

# Icon
if (Test-Path "$DesktopDir\AppIcon.ico") {
    Copy-Item "$DesktopDir\AppIcon.ico" $BuildDir
}
if (Test-Path "$DesktopDir\icon.svg") {
    Copy-Item "$DesktopDir\icon.svg" $BuildDir
}

# 4. Create launcher .bat
$BatContent = @"
@echo off
:: ApplyLoop Desktop — double-click to start
:: Dashboard: http://localhost:18790
cd /d "%~dp0"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%a:~0,1%%"=="#" set "%%a=%%b"
    )
)
venv\Scripts\pythonw.exe launch.py
"@
$BatContent | Out-File -FilePath "$BuildDir\ApplyLoop.bat" -Encoding ASCII

# 5. Create .env template
$EnvTemplate = @"
# ApplyLoop — paste your worker token below and save
WORKER_TOKEN=
APPLYLOOP_USER_ID=
NEXT_PUBLIC_APP_URL=https://applyloop.vercel.app
"@
$EnvTemplate | Out-File -FilePath "$BuildDir\.env.example" -Encoding UTF8

# 6. Zip it
Write-Host "  Creating zip..." -ForegroundColor White
$ZipPath = Join-Path $DistDir "ApplyLoop-windows-portable.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path "$BuildDir\*" -DestinationPath $ZipPath -CompressionLevel Optimal

$SizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "  Done! $ZipPath ($SizeMB MB)" -ForegroundColor Green
Write-Host "  User: extract → edit .env → double-click ApplyLoop.bat" -ForegroundColor Cyan
