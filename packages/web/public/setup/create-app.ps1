# ApplyLoop — Creates a proper Windows application shortcut on Desktop
# Called by setup-windows.ps1 after installation is complete.
# Creates a .bat launcher + Desktop shortcut with custom icon.

param(
    [string]$InstallDir = "$env:USERPROFILE\ApplyLoop"
)

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$LauncherPath = Join-Path $InstallDir "ApplyLoop.bat"
$IconPath = Join-Path $InstallDir "applyloop.ico"
$ShortcutPath = Join-Path $DesktopPath "ApplyLoop.lnk"

# Download icon if not present
if (-not (Test-Path $IconPath)) {
    try {
        # Use a generic briefcase icon from Windows system
        $IconPath = "$env:SystemRoot\System32\shell32.dll"
    } catch {}
}

# Create the launcher .bat if not present
if (-not (Test-Path $LauncherPath)) {
    try {
        Invoke-WebRequest -Uri "https://applyloop.vercel.app/setup/ApplyLoop.bat" -OutFile $LauncherPath -UseBasicParsing 2>$null
    } catch {}
}

# Create proper Windows shortcut
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $LauncherPath
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = "ApplyLoop — AI Job Application Bot. Double-click to start scouting and applying."
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,144"  # Briefcase icon
    $Shortcut.Save()

    # Set shortcut to run as administrator
    $bytes = [System.IO.File]::ReadAllBytes($ShortcutPath)
    $bytes[0x15] = $bytes[0x15] -bor 0x20  # Set "Run as administrator" flag
    [System.IO.File]::WriteAllBytes($ShortcutPath, $bytes)

    Write-Host "ApplyLoop shortcut created on Desktop (runs as administrator)" -ForegroundColor Green
} catch {
    Write-Host "Could not create shortcut — use ApplyLoop.bat directly" -ForegroundColor Yellow
}

# Also pin to Start Menu
try {
    $StartMenuPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ApplyLoop.lnk"
    Copy-Item $ShortcutPath $StartMenuPath -Force
    Write-Host "ApplyLoop added to Start Menu" -ForegroundColor Green
} catch {}
