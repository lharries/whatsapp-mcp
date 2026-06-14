<#
.SYNOPSIS
    Start whatsapp-bridge.exe in the background on Windows.

.DESCRIPTION
    Builds whatsapp-bridge.exe if missing or older than main.go, then launches
    it hidden with stdout/stderr redirected to log files. Writes the PID to
    run\bridge.pid. Refuses to start if a paired session does not yet exist
    (store\whatsapp.db must be present from a prior interactive `go run .`).
#>

$ErrorActionPreference = 'Stop'

# Resolve the bridge directory regardless of where the script is invoked from.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridgeDir = Split-Path -Parent $scriptDir
Set-Location -Path $bridgeDir

$exePath  = Join-Path $bridgeDir 'whatsapp-bridge.exe'
$mainGo   = Join-Path $bridgeDir 'main.go'
$logsDir  = Join-Path $bridgeDir 'logs'
$runDir   = Join-Path $bridgeDir 'run'
$pidFile  = Join-Path $runDir 'bridge.pid'
$outLog   = Join-Path $logsDir 'bridge.out.log'
$errLog   = Join-Path $logsDir 'bridge.err.log'
$session  = Join-Path $bridgeDir 'store\whatsapp.db'

if (-not (Test-Path $session)) {
    Write-Host 'No paired session found at store\whatsapp.db.' -ForegroundColor Yellow
    Write-Host 'Run `$env:CGO_ENABLED=''1''; go run .` interactively from whatsapp-bridge\, scan the QR code, then try again.' -ForegroundColor Yellow
    exit 2
}

# go-sqlite3 is a cgo package and needs a C compiler (gcc) on PATH.
$gcc = Get-Command gcc.exe -ErrorAction SilentlyContinue
if (-not $gcc) {
    Write-Host 'gcc.exe not found on PATH.' -ForegroundColor Red
    Write-Host 'The bridge uses go-sqlite3 which requires cgo + a C compiler.' -ForegroundColor Red
    Write-Host 'Install MinGW-w64 (e.g. via MSYS2 or WinLibs) and add its bin dir to PATH.' -ForegroundColor Red
    Write-Host '  winget search mingw   # browse options' -ForegroundColor Red
    exit 1
}

# Force CGO on for the build that follows. Idempotent on machines that already have it.
$env:CGO_ENABLED = '1'

if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
if (-not (Test-Path $runDir))  { New-Item -ItemType Directory -Path $runDir  | Out-Null }

# Refuse to double-start if a PID file points at a live process.
if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existingPid) {
        $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Bridge already running (PID $existingPid)." -ForegroundColor Cyan
            exit 0
        } else {
            Remove-Item $pidFile -Force
        }
    }
}

# Build if the binary is missing or stale.
$needBuild = $true
if (Test-Path $exePath) {
    $exeTime  = (Get-Item $exePath).LastWriteTimeUtc
    $mainTime = (Get-Item $mainGo).LastWriteTimeUtc
    if ($exeTime -ge $mainTime) { $needBuild = $false }
}

if ($needBuild) {
    Write-Host 'Building whatsapp-bridge.exe ...' -ForegroundColor Cyan
    & go build -o $exePath .
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'go build failed.' -ForegroundColor Red
        exit 1
    }
}

$proc = Start-Process -FilePath $exePath `
    -WorkingDirectory $bridgeDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError  $errLog `
    -PassThru

if ($null -eq $proc) {
    Write-Host 'Failed to start whatsapp-bridge.exe.' -ForegroundColor Red
    exit 1
}

Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
Write-Host "Started whatsapp-bridge.exe (PID $($proc.Id))." -ForegroundColor Green
Write-Host "  stdout: $outLog"
Write-Host "  stderr: $errLog"
