<#
.SYNOPSIS
    Build RamOptimizerService.exe  (the logic behind build_exe.bat).

.DESCRIPTION
    Why PowerShell and not plain batch?

    Batch files are read in the console's OEM code page. This repository's
    comments are UTF-8 (Persian), so a batch file that mixes non-ASCII
    *comments* with the delayed-expansion/protected-block syntax can be
    mis-parsed and end up running the wrong branch (we hit exactly that: a
    "no supported Python" message appeared while "py -3.13" was rejected).
    PowerShell is UTF-8 aware when started with -File on a BOM-less file only
    if it can decode it, so this file is plain ASCII on purpose: no Persian
    here, only in the .ps1 files that are *read* by other tools.

    Steps: find a supported Python (3.9 - 3.13) -> venv -> requirements ->
    tests -> version_info -> PyInstaller -> copy into build\ -> build_info.

.PARAMETER Python
    Force a specific interpreter, e.g. -Python "py -3.11" or -Python python.

.PARAMETER SkipTests
    Do not run pytest (not recommended).

.NOTES
    Exit codes: 0 = built, 1 = failed, 2 = no usable Python.
#>
[CmdletBinding()]
param(
    [string]$Python = '',
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$script:Supported = @(
    @{ Tag = '3.13'; Major = 3; Minor = 13 },
    @{ Tag = '3.12'; Major = 3; Minor = 12 },
    @{ Tag = '3.11'; Major = 3; Minor = 11 },
    @{ Tag = '3.10'; Major = 3; Minor = 10 },
    @{ Tag = '3.9'; Major = 3; Minor = 9 }
)
#: PyInstaller has no support for 3.14+ yet; anything newer is unusable here.
$script:MaxMajor = 3
$script:MaxMinor = 13

function Write-Step([string]$Text) { Write-Host "[build] $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[ OK ]  $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "[ .. ]  $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "[FAIL]  $Text" -ForegroundColor Red }

# Run a candidate interpreter and print "major.minor" (nothing on failure).
function Get-PythonVersion([string]$CommandLine) {
    $parts = $CommandLine.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    $exe = $parts[0]
    $prefix = @()
    if ($parts.Length -gt 1) { $prefix = $parts[1..($parts.Length - 1)] }
    $code = 'import sys; print("%d.%d" % sys.version_info[:2])'
    try {
        $output = & $exe @prefix -c $code 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    return ($output | Select-Object -First 1).ToString().Trim()
}

function Test-VenvVersion([string]$Version) {
    if (-not $Version) { return $false }
    $numbers = $Version.Split('.')
    $major = [int]$numbers[0]
    $minor = [int]$numbers[1]
    if ($major -ne 3) { return $false }
    if ($minor -lt 9) { return $false }
    if ($minor -gt 13) { return $false }
    return $true
}

# --- 0) pick an interpreter -------------------------------------------------
Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host '  RAM Optimizer Service - Build' -ForegroundColor Cyan
Write-Host '  Needs Python 3.9 - 3.13 (PyInstaller has no 3.14+ support)' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan

$venvPython = Join-Path $script:Root '.venv\Scripts\python.exe'
$reuseVenv = $false
if (Test-Path -LiteralPath $venvPython) {
    $existing = Get-PythonVersion $venvPython
    if (Test-VenvVersion $existing) {
        $reuseVenv = $true
        Write-Ok "reusing .venv (Python $existing)"
    } elseif ($existing) {
        Write-Note ".venv uses Python $existing, which PyInstaller does not support."
        Write-Note 'Deleting .venv and creating a supported one...'
        Remove-Item -LiteralPath (Join-Path $script:Root '.venv') -Recurse -Force
    }
}

$chosen = $null
if (-not $reuseVenv) {
    $candidates = @()
    if ($Python) { $candidates += $Python }
    foreach ($entry in $script:Supported) { $candidates += "py -$($entry.Tag)" }
    $candidates += 'python'
    $candidates += 'python3'

    foreach ($candidate in $candidates) {
        $version = Get-PythonVersion $candidate
        if (-not $version) { continue }
        if (Test-VenvVersion $version) {
            $chosen = $candidate
            Write-Ok "found Python $version via '$candidate'"
            break
        } else {
            Write-Note "'$candidate' is Python $version - not usable for this build"
        }
    }
}

if (-not $reuseVenv -and -not $chosen) {
    Write-Fail 'No supported Python found (3.9 - 3.13).'
    Write-Host '  Options:' -ForegroundColor Yellow
    Write-Host '   1) Install Python 3.11 from https://www.python.org/downloads/'
    Write-Host '      (tick "Add python.exe to PATH"), then run build_exe.bat again.'
    Write-Host '   2) If you have the Python launcher:   py install 3.11'
    Write-Host '   3) Force an interpreter:              build_exe.bat -Python "py -3.11"'
    Write-Host '   4) Skip the build entirely: download the exe from the CI artifact'
    Write-Host '      "RamOptimizerService-windows" (GitHub -> Actions -> latest green run)'
    Write-Host ''
    Write-Host '  Detected interpreters:' -ForegroundColor Yellow
    try { & py --list 2>$null | ForEach-Object { Write-Host "     $_" } } catch { }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        Write-Host '     (the py launcher is not installed)'
    }
    exit 2
}

Set-Location -LiteralPath $script:Root

# --- 1) virtual environment -------------------------------------------------
if ($reuseVenv) {
    Write-Step '1/6 using the existing .venv'
} else {
    Write-Step "1/6 creating .venv with '$chosen'"
    $parts = $chosen.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
    $exe = $parts[0]
    $prefix = @()
    if ($parts.Length -gt 1) { $prefix = $parts[1..($parts.Length - 1)] }
    & $exe @prefix -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        Write-Fail 'Creating the virtual environment failed (see the message above).'
        exit 1
    }
}

$py = $venvPython
$venvVersion = Get-PythonVersion $py
if (-not (Test-VenvVersion $venvVersion)) {
    Write-Fail ".venv is Python $venvVersion - delete the .venv folder and run again."
    exit 1
}
Write-Ok "using .venv (Python $venvVersion)"

# --- 2) requirements --------------------------------------------------------
Write-Step '2/6 installing build requirements'
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    Write-Fail 'pip install failed (see the message above).'
    exit 1
}

# A third-party PyPI package literally named "servicemanager" shadows pywin32's
# own module inside the frozen exe ("service did not respond in a timely
# fashion"). Make sure it is not installed.
& $py -m pip show servicemanager *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Note 'removing the conflicting PyPI package "servicemanager"'
    & $py -m pip uninstall -y servicemanager *> $null
}

# --- 3) tests ---------------------------------------------------------------
if ($SkipTests) {
    Write-Note '3/6 tests skipped (-SkipTests)'
} else {
    Write-Step '3/6 running the test suite'
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        Write-Fail 'Tests failed - not shipping a broken build.'
        exit 1
    }
}

# --- 4) version info --------------------------------------------------------
Write-Step '4/6 generating version_info.txt'
& $py tools\make_version_info.py
if ($LASTEXITCODE -ne 0) { Write-Fail 'make_version_info.py failed.'; exit 1 }

# --- 5) PyInstaller ---------------------------------------------------------
Write-Step '5/6 building with PyInstaller (onedir)'
& $py -m PyInstaller --clean --noconfirm RamOptimizerService.spec
if ($LASTEXITCODE -ne 0) { Write-Fail 'PyInstaller failed (see the message above).'; exit 1 }

# --- 6) copy into build\ ----------------------------------------------------
Write-Step '6/6 copying the result into build\'
$target = Join-Path $script:Root 'build\RamOptimizerService'
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $script:Root 'dist\RamOptimizerService\*') -Destination $target -Recurse -Force
& $py tools\make_build_info.py
if ($LASTEXITCODE -ne 0) { Write-Fail 'make_build_info.py failed.'; exit 1 }

$exe = Join-Path $target 'RamOptimizerService.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Fail "the exe was not produced: $exe"
    exit 1
}
Write-Ok 'smoke test: version'
& $exe version
if ($LASTEXITCODE -ne 0) { Write-Fail 'the built exe does not run.'; exit 1 }

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  BUILD OK' -ForegroundColor Green
Write-Host "  $exe"
Write-Host '  build\Manage-RamOptimizer.bat   (install / remove / status / logs)'
Write-Host '============================================================' -ForegroundColor Green
exit 0
