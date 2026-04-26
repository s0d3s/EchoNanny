Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[i] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[✓] $msg" -ForegroundColor Green }
function Write-WarnMsg($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-ErrMsg($msg) { Write-Host "[x] $msg" -ForegroundColor Red }

function Resolve-Python {
    foreach ($candidate in @("python", "py")) {
        try {
            $null = Get-Command $candidate -ErrorAction Stop
            return $candidate
        } catch {
            continue
        }
    }
    return $null
}

function Get-PythonRunArgs([string]$pythonCmd, [string]$code) {
    if ($pythonCmd -eq "py") {
        return @("-3", "-c", $code)
    }
    return @("-c", $code)
}

function Get-PythonVenvArgs([string]$pythonCmd) {
    if ($pythonCmd -eq "py") {
        return @("-3", "-m", "venv", ".venv")
    }
    return @("-m", "venv", ".venv")
}

function Test-Prerequisites {
    $pythonCmd = Resolve-Python
    if (-not $pythonCmd) {
        Write-ErrMsg "Python 3.11+ is not available in PATH."
        Write-WarnMsg "Install Python first, then rerun this installer."
        return $null
    }

    $versionCode = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    $versionArgs = Get-PythonRunArgs -pythonCmd $pythonCmd -code $versionCode
    & $pythonCmd @versionArgs
    if ($LASTEXITCODE -ne 0) {
        Write-ErrMsg "Detected Python is below 3.11."
        Write-WarnMsg "Install Python 3.11+ and rerun this installer."
        return $null
    }

    $venvCode = "import venv"
    $venvArgs = Get-PythonRunArgs -pythonCmd $pythonCmd -code $venvCode
    & $pythonCmd @venvArgs
    if ($LASTEXITCODE -ne 0) {
        Write-ErrMsg "Python venv module is unavailable."
        Write-WarnMsg "Install Python venv support and rerun this installer."
        return $null
    }

    return $pythonCmd
}

function Select-InstallDirectory {
    while ($true) {
        $useCurrent = Read-Host "Use current directory as install target? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($useCurrent)) { $useCurrent = "Y" }

        if ($useCurrent -match '^[Yy]$') {
            $candidate = (Get-Location).Path
        } else {
            $candidate = Read-Host "Enter full path to an existing EMPTY directory"
        }

        if ([string]::IsNullOrWhiteSpace($candidate)) {
            Write-WarnMsg "Path cannot be empty."
            continue
        }

        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
            Write-WarnMsg "Directory does not exist: $candidate"
            Write-WarnMsg "Create it manually and retry."
            continue
        }

        $items = Get-ChildItem -LiteralPath $candidate -Force
        if ($items.Count -gt 0) {
            Write-WarnMsg "Directory is not empty: $candidate"
            Write-WarnMsg "Please choose an EMPTY directory."
            continue
        }

        return (Resolve-Path -LiteralPath $candidate).Path
    }
}

Write-Info "EchoNanny installer (Windows)"

$pythonCmd = Test-Prerequisites
if (-not $pythonCmd) { exit 1 }
Write-Ok "Prerequisites check passed"

$targetDir = Select-InstallDirectory
Set-Location -LiteralPath $targetDir
Write-Ok "Using target directory: $targetDir"

Write-Info "Creating virtual environment (.venv)..."
$venvArgs = Get-PythonVenvArgs -pythonCmd $pythonCmd
& $pythonCmd @venvArgs

$venvActivate = Join-Path $targetDir ".venv\Scripts\Activate.ps1"
if (-not (Test-Path -LiteralPath $venvActivate)) {
    Write-ErrMsg "Virtual environment activation script not found: $venvActivate"
    exit 1
}

. $venvActivate
Write-Ok "Virtual environment activated"

Write-Info "Installing EchoNanny from PyPI..."
python -m pip install --upgrade pip
python -m pip install echonanny
Write-Ok "EchoNanny installed"

Write-Info "Creating .env from template..."
echonanny init-env
Write-Ok ".env created"

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1) Edit credentials in: $targetDir\.env" -ForegroundColor Cyan
Write-Host "     - INSTANCE_USER_EMAIL"
Write-Host "     - INSTANCE_USER_PASSWORD"
Write-Host "  2) Start server from this directory:"
Write-Host "     echonanny serve" -ForegroundColor Cyan
Write-Host "  3) Open Web UI on this PC: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "Remote access warning:" -ForegroundColor Yellow
Write-Host "  For access outside your local machine/network, use secure tunneling"
Write-Host "  (e.g. Cloudflare Tunnel, zrok) or proper network forwarding."
Write-Host "  Login credentials are the values you set in .env."
Write-Host ""
