<#
.SYNOPSIS
    RAM Optimizer Service - control panel for Windows.

.DESCRIPTION
    One file for install, remove, status, logs and day-to-day operation.
    Launch it with Manage-RamOptimizer.bat (double-click), or run a single
    action without the menu:

        RamOptimizerControl.ps1 -Action install
        RamOptimizerControl.ps1 -Action remove
        RamOptimizerControl.ps1 -Action status
        RamOptimizerControl.ps1 -Action logs -Lines 200

    Actions: menu (default), install, remove, status, logs, start, stop,
             restart, test, config, reload, pause, resume, verify, doctor,
             repair.

    Deliberately compatible with Windows PowerShell 5.1 (the version that
    ships with Windows): this file is ASCII only, so no code page or
    Unicode-escape syntax can break it. All user-facing text is English.

    Exit codes: 0 = success, 1 = failure, 2 = nothing to do / warning.
#>
[CmdletBinding()]
param(
    [ValidateSet('menu', 'install', 'remove', 'status', 'logs', 'start', 'stop',
        'restart', 'test', 'config', 'reload', 'pause', 'resume', 'verify',
        'doctor', 'repair')]
    [string]$Action = 'menu',

    [int]$Lines = 60,
    [switch]$NoWait,
    [switch]$NoPause
)

# Do not let a failing helper abort the whole panel: every step below checks
# the exit code of the exe itself.
$ErrorActionPreference = 'Continue'
$script:Root = Split-Path -Parent $PSCommandPath
$script:ScriptPath = $PSCommandPath
$script:ServiceName = 'RamOptimizerService'
$script:SawProblem = $false
$script:LogLines = $Lines

# Actions that need an elevated shell. Read-only actions do not.
$script:NeedsAdmin = @('install', 'remove', 'start', 'stop', 'restart',
    'reload', 'pause', 'resume', 'repair')

# ---------------------------------------------------------------------------
# Console setup: UTF-8 + code page 65001 so exe output is not mangled.
# ---------------------------------------------------------------------------
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    if ($Host.Name -eq 'ConsoleHost') { cmd /c chcp 65001 > $null 2>&1 }
} catch { }

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
$script:UiWidth = 68

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host ('-' * $script:UiWidth) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('-' * $script:UiWidth) -ForegroundColor DarkGray
}

function Write-Ok([string]$Text) { Write-Host "[ ok ]  $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "[ .. ]  $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text) {
    Write-Host "[FAIL]  $Text" -ForegroundColor Red
    $script:SawProblem = $true
}

function Write-KeyValue([string]$Key, [string]$Value, [string]$Color = 'Gray') {
    Write-Host ('  {0,-14} {1}' -f $Key, $Value) -ForegroundColor $Color
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
function Get-DataDir {
    if ($env:RAMOPT_DATA_DIR) { return $env:RAMOPT_DATA_DIR }
    if ($env:ProgramData) { return (Join-Path $env:ProgramData 'RamOptimizer') }
    return (Join-Path $env:TEMP 'RamOptimizer')
}

function Find-Exe {
    $candidates = @(
        (Join-Path $script:Root 'RamOptimizerService\RamOptimizerService.exe'),
        (Join-Path $script:Root 'RamOptimizerService.exe'),
        (Join-Path $script:Root '..\dist\RamOptimizerService\RamOptimizerService.exe'),
        (Join-Path $script:Root '..\release\RamOptimizerService\RamOptimizerService.exe')
    )
    foreach ($candidate in $candidates) {
        $full = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path -LiteralPath $full -PathType Leaf) { return $full }
    }
    return $null
}

# Read one key from config.ini without depending on the exe. Returns the
# fallback when the file or the key is missing, so the panel never lies about
# the cadence it prints.
function Get-ConfigValue([string]$Key, [string]$Fallback) {
    $ini = Join-Path (Get-DataDir) 'config.ini'
    if (-not (Test-Path -LiteralPath $ini)) { return $Fallback }
    try {
        $match = Select-String -LiteralPath $ini -Pattern ("^\s*" + $Key + "\s*=\s*(\S+)") |
            Select-Object -First 1
        if ($match) { return $match.Matches[0].Groups[1].Value }
    } catch { }
    return $Fallback
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Re-run this script elevated for one action. $true = caller may continue.
function Confirm-Admin([string]$ForAction) {
    if (Test-Admin) { return $true }
    Write-Note "This action needs Administrator rights - asking for elevation..."
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $script:ScriptPath),
        '-Action', $ForAction, '-Lines', $script:LogLines, '-NoWait'
    )
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait
    } catch {
        Write-Bad 'Elevation was refused. Right-click Manage-RamOptimizer.bat and choose "Run as administrator".'
    }
    return $false
}

# ---------------------------------------------------------------------------
# Running the exe. Returns its exit code; output goes straight to the console.
# ---------------------------------------------------------------------------
function Invoke-Exe {
    param(
        [Parameter(Mandatory)][string[]]$ExeArgs,
        [switch]$AllowFail
    )
    $exe = Find-Exe
    if (-not $exe) {
        Write-Bad 'RamOptimizerService.exe was not found.'
        Write-Host "        looked in: $script:Root , ..\dist , ..\release"
        Write-Host '        build it with build_exe.bat, or unzip the release package here.'
        return 9009
    }
    Write-Host ('        > {0} {1}' -f (Split-Path -Leaf $exe), ($ExeArgs -join ' ')) -ForegroundColor DarkGray
    & $exe @ExeArgs 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFail) { Write-Bad "Command failed (exit code $code)." }
    return $code
}

function Get-ServiceState {
    return (Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
function Invoke-Install {
    Write-Head 'Install'
    if (-not (Confirm-Admin 'install')) { return 2 }
    if (Invoke-Exe -ExeArgs @('service', 'install', '--wait', '25') -AllowFail) {
        Write-Bad 'Installation failed - see the message above.'
        Write-Note 'Already installed? Use option 14 (repair) or remove it first.'
        return 1
    }
    Invoke-Exe -ExeArgs @('config', '--init') -AllowFail | Out-Null
    $service = Get-ServiceState
    if ($service) {
        Write-Ok "installed: state = $($service.Status), startup = $($service.StartType)"
    } else {
        Write-Note 'not visible yet - run status again in a few seconds'
    }
    $interval = Get-ConfigValue 'check_interval_seconds' '60'
    $critical = Get-ConfigValue 'sustained_trigger_percent' '92'
    Write-KeyValue 'config file' (Join-Path (Get-DataDir) 'config.ini')
    Write-KeyValue 'behaviour' "release pass every $interval s; immediate at $critical% used"
    Write-KeyValue 'verify' 'menu option 13, or: RamOptimizerService.exe verify --simulate-critical'
    return 0
}

function Invoke-Remove {
    Write-Head 'Remove'
    if (-not (Confirm-Admin 'remove')) { return 2 }
    if (-not (Get-ServiceState)) {
        Write-Note 'the service is not installed - nothing to remove'
        if (Test-Path -LiteralPath (Get-DataDir)) {
            Write-KeyValue 'data kept in' (Get-DataDir)
            Write-Note 'delete that folder for a completely clean uninstall'
        }
        return 2
    }
    if (Invoke-Exe -ExeArgs @('service', 'remove', '--wait', '15') -AllowFail) {
        Write-Bad 'Removal failed.'
        return 1
    }
    if (Get-ServiceState) {
        Write-Bad 'the service is still registered - close services.msc or reboot, then retry'
        return 1
    }
    Write-Ok 'service removed'
    Write-KeyValue 'data kept in' (Get-DataDir)
    return 0
}

function Invoke-Status {
    Write-Head 'Status'
    if (-not (Find-Exe)) {
        Write-Bad 'RamOptimizerService.exe was not found - build it first (build_exe.bat).'
        return 1
    }

    $service = Get-ServiceState
    if ($service) {
        $startup = $service.StartType
        Write-KeyValue 'service' "installed  ($($service.Status), $startup)" 'Green'
    } else {
        Write-KeyValue 'service' 'not installed' 'Yellow'
    }

    $statusFile = Join-Path (Get-DataDir) 'status.json'
    if (-not (Test-Path -LiteralPath $statusFile)) {
        Write-KeyValue 'status.json' "not written yet ($statusFile)"
        Write-Note 'the service writes it after every cycle'
        return 0
    }

    try {
        $data = Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Bad "status.json could not be parsed: $($_.Exception.Message)"
        return 1
    }

    $memory = $data.memory
    $counters = $data.counters
    $age = (Get-Date) - (Get-Item -LiteralPath $statusFile).LastWriteTime

    Write-Host ''
    Write-KeyValue 'state' ([string]$data.state)
    Write-KeyValue 'last cycle' ("{0}  ({1:n0} s ago)" -f $data.last_cycle_at, $age.TotalSeconds)
    Write-KeyValue 'last action' ([string]$data.last_action)
    Write-KeyValue 'reason' ([string]$data.last_reason)
    if ($memory) {
        Write-KeyValue 'memory' ("{0}% used, {1:n0} MB free, commit {2}%" -f `
            $memory.used_percent, $memory.available_mb, $memory.commit_percent)
    }
    if ($counters) {
        Write-KeyValue 'totals' ("{0} passes, {1:n0} MB freed, {2} errors, {3} cycles" -f `
            $counters.purges, $counters.freed_mb, $counters.errors, $counters.cycles)
    }
    $critical = $data.extra.critical
    if ($null -ne $critical) {
        if ($critical) {
            Write-KeyValue 'critical' 'YES - a release pass runs immediately' 'Yellow'
        } else {
            Write-KeyValue 'critical' 'no - below the critical threshold' 'Green'
        }
    }
    if ($data.recent_errors) {
        Write-Host ''
        Write-Note 'recent errors:'
        $data.recent_errors | Select-Object -Last 5 | ForEach-Object {
            Write-Host ("        {0}  {1}" -f $_.at, $_.message) -ForegroundColor Red
        }
    }
    return 0
}

function Invoke-Logs {
    Write-Head "Logs (last $script:LogLines lines)"
    $log = Join-Path (Get-DataDir) 'ram_optimizer.log'
    $crash = Join-Path (Get-DataDir) 'crash.log'

    if (Test-Path -LiteralPath $log) {
        Write-Host "  $log  ($((Get-Item -LiteralPath $log).Length) bytes)" -ForegroundColor DarkGray
        Write-Host ''
        Get-Content -LiteralPath $log -Tail $script:LogLines -Encoding UTF8 | ForEach-Object {
            # Colour the lines that matter, keep everything readable.
            if ($_ -match 'critical|IMMEDIATE') { Write-Host $_ -ForegroundColor Yellow }
            elseif ($_ -match 'ERROR|crash') { Write-Host $_ -ForegroundColor Red }
            else { Write-Host $_ }
        }
    } else {
        Write-Note "no log yet: $log"
    }

    Write-Host ''
    if (Test-Path -LiteralPath $crash) {
        Write-Note "crash log: $crash"
        Get-Content -LiteralPath $crash -Tail 30 -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    } else {
        Write-Ok 'no crash log - no startup crashes recorded'
    }
    Write-Host ''
    Write-Host '  what to look for:' -ForegroundColor DarkGray
    Write-Host '    "optimization loop started ... every 60"   normal cadence'
    Write-Host '    "critical"                                  immediate pass'
    Write-Host '    "released ... MB"                           measured result'
    return 0
}

function Invoke-Test {
    Write-Head 'Dry run (nothing on the system is changed)'
    if (-not (Confirm-Admin 'test')) { return 2 }
    if (Invoke-Exe -ExeArgs @('test', '--dry-run')) { return 1 }
    Write-Ok 'dry run finished - the JSON above is what a real pass would decide'
    return 0
}

function Invoke-Config {
    Write-Head 'Configuration'
    $ini = Join-Path (Get-DataDir) 'config.ini'
    if (-not (Test-Path -LiteralPath $ini)) {
        Invoke-Exe -ExeArgs @('config', '--init') -AllowFail | Out-Null
    }
    if (-not (Test-Path -LiteralPath $ini)) {
        Write-Bad 'config.ini could not be created.'
        return 1
    }
    Write-KeyValue 'file' $ini
    Write-Host ''
    Write-Host '  keys that control the behaviour:' -ForegroundColor DarkGray
    Select-String -LiteralPath $ini -Pattern 'check_interval_seconds|critical_poll_seconds|critical_probe_seconds|trigger_percent|reset_percent|sustained_trigger_percent|sustained_polls' |
        ForEach-Object { Write-Host ('    ' + $_.Line.Trim()) }
    Write-Host ''
    Write-Note 'after editing, apply it with menu option 10 (reload) - no restart needed'
    if (-not $NoPause) {
        $answer = Read-Host '  open it in Notepad now? [y/N]'
        if ($answer -match '^[Yy]') { Start-Process notepad.exe -ArgumentList $ini -Wait | Out-Null }
    }
    Invoke-Exe -ExeArgs @('config', '--validate') -AllowFail | Out-Null
    return 0
}

function Invoke-Verify {
    Write-Head 'Behaviour check: every minute, and immediate when critical'
    if (Invoke-Exe -ExeArgs @('verify', '--simulate-critical') -AllowFail) { return 1 }
    Write-Ok 'cadence and critical path verified (read-only)'
    Write-Note 'for evidence from a running service, see option 4 (logs)'
    return 0
}

function Invoke-Doctor {
    Write-Head 'Diagnostics'
    Write-KeyValue 'windows' ([System.Environment]::OSVersion.VersionString)
    Write-KeyValue 'powershell' ([string]$PSVersionTable.PSVersion)
    Write-KeyValue '64-bit OS' ([string][System.Environment]::Is64BitOperatingSystem)
    Write-KeyValue 'elevated' ([string](Test-Admin))
    Write-KeyValue 'data folder' (Get-DataDir)

    $exe = Find-Exe
    if ($exe) { Write-KeyValue 'exe' $exe 'Green' } else { Write-Bad 'RamOptimizerService.exe not found.' }

    $service = Get-ServiceState
    if ($service) {
        Write-KeyValue 'service' "$($service.Status) / $($service.StartType)" 'Green'
    } else {
        Write-KeyValue 'service' 'not installed' 'Yellow'
    }

    if ($exe) {
        Write-Host ''
        Invoke-Exe -ExeArgs @('version') -AllowFail | Out-Null
        Invoke-Exe -ExeArgs @('config', '--validate') -AllowFail | Out-Null
        if (Test-Admin) { Invoke-Exe -ExeArgs @('service', 'query') -AllowFail | Out-Null }
    }
    if ($script:SawProblem) { return 1 }
    return 0
}

# One-liner action: elevate, run, report.
function Invoke-Verb([string]$Action, [string]$Title, [string[]]$ExeArgs) {
    Write-Head $Title
    if (-not (Confirm-Admin $Action)) { return 2 }
    if (Invoke-Exe -ExeArgs $ExeArgs) { return 1 }
    Write-Ok 'done'
    return 0
}

function Invoke-Named([string]$Name) {
    switch ($Name) {
        'install' { return (Invoke-Install) }
        'remove' { return (Invoke-Remove) }
        'status' { return (Invoke-Status) }
        'logs' { return (Invoke-Logs) }
        'test' { return (Invoke-Test) }
        'config' { return (Invoke-Config) }
        'verify' { return (Invoke-Verify) }
        'doctor' { return (Invoke-Doctor) }
        'start' { return (Invoke-Verb 'start' 'Start' @('service', 'start', '--wait', '20')) }
        'stop' { return (Invoke-Verb 'stop' 'Stop' @('service', 'stop', '--wait', '15')) }
        'restart' { return (Invoke-Verb 'restart' 'Restart' @('service', 'restart', '--wait', '20')) }
        'reload' { return (Invoke-Verb 'reload' 'Reload configuration' @('reload')) }
        'pause' { return (Invoke-Verb 'pause' 'Pause trimming' @('pause')) }
        'resume' { return (Invoke-Verb 'resume' 'Resume trimming' @('resume')) }
        'repair' { return (Invoke-Verb 'repair' 'Repair installation' @('service', 'repair')) }
        default { return 2 }
    }
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
function Show-Header {
    $exe = Find-Exe
    $service = Get-ServiceState

    Write-Host ''
    Write-Host ('=' * $script:UiWidth) -ForegroundColor DarkCyan
    Write-Host '  RAM Optimizer Service  -  Control Panel' -ForegroundColor Cyan
    Write-Host ('=' * $script:UiWidth) -ForegroundColor DarkCyan

    if ($exe) {
        Write-KeyValue 'exe' (Split-Path -Leaf (Split-Path -Parent $exe)) 'DarkGray'
        Write-KeyValue 'path' $exe 'DarkGray'
    } else {
        Write-KeyValue 'exe' 'NOT FOUND - run build_exe.bat' 'Red'
    }
    if ($service) {
        Write-KeyValue 'service' "$($service.Status)  ($($service.StartType))" 'Green'
    } else {
        Write-KeyValue 'service' 'not installed' 'Yellow'
    }

    # Compact one-line summary of the last cycle, if there is one.
    $statusFile = Join-Path (Get-DataDir) 'status.json'
    if (Test-Path -LiteralPath $statusFile) {
        try {
            $data = Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $memory = $data.memory
            $usage = if ($memory) { $memory.used_percent } else { '?' }
            $criticalText = 'normal'
            if ($null -ne $data.extra.critical -and $data.extra.critical) { $criticalText = 'CRITICAL' }
            Write-KeyValue 'last cycle' ("{0}% used, {1}" -f $usage, $criticalText)
        } catch { }
    }
}

function Show-Menu {
    Show-Header
    Write-Host ''
    Write-Host '  SERVICE' -ForegroundColor DarkGray
    Write-Host '    1  Install'
    Write-Host '    2  Remove'
    Write-Host '    3  Status'
    Write-Host '    4  Logs'
    Write-Host ''
    Write-Host '  CONTROL' -ForegroundColor DarkGray
    Write-Host '    5  Start                         6  Stop'
    Write-Host '    7  Restart                      10  Reload configuration'
    Write-Host '   11  Pause / resume trimming'
    Write-Host ''
    Write-Host '  INSPECT' -ForegroundColor DarkGray
    Write-Host '    8  Dry run (no changes)           9  Configuration'
    Write-Host '   12  Diagnostics                   13  Behaviour check'
    Write-Host '   14  Repair installation (fix the exe path after moving it)'
    Write-Host ''
    Write-Host '    0  Exit' -ForegroundColor DarkGray
    Write-Host ''
}

function Invoke-MenuAction([string]$Choice) {
    switch ($Choice) {
        '1' { Invoke-Named 'install' | Out-Null }
        '2' {
            $answer = Read-Host '  Remove the service? Settings and logs are kept. [y/N]'
            if ($answer -match '^[Yy]') { Invoke-Named 'remove' | Out-Null } else { Write-Note 'cancelled' }
        }
        '3' { Invoke-Named 'status' | Out-Null }
        '4' {
            $raw = Read-Host "  How many lines? [Enter = $script:LogLines]"
            if ($raw -match '^\d+$') { $script:LogLines = [int]$raw }
            Invoke-Logs | Out-Null
        }
        '5' { Invoke-Named 'start' | Out-Null }
        '6' { Invoke-Named 'stop' | Out-Null }
        '7' { Invoke-Named 'restart' | Out-Null }
        '8' { Invoke-Named 'test' | Out-Null }
        '9' { Invoke-Named 'config' | Out-Null }
        '10' { Invoke-Named 'reload' | Out-Null }
        '11' {
            Write-Host ''
            Write-Host '    p = pause trimming (the service keeps running and reporting)'
            Write-Host '    r = resume trimming'
            $answer = Read-Host '    choice [p/r]'
            if ($answer -match '^[Pp]') { Invoke-Named 'pause' | Out-Null }
            elseif ($answer -match '^[Rr]') { Invoke-Named 'resume' | Out-Null }
            else { Write-Note 'cancelled' }
        }
        '12' { Invoke-Named 'doctor' | Out-Null }
        '13' { Invoke-Named 'verify' | Out-Null }
        '14' { Invoke-Named 'repair' | Out-Null }
        default { Write-Note "unknown option: $Choice" }
    }
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if ($Action -ne 'menu') {
    $exitCode = Invoke-Named $Action
    if ($null -eq $exitCode) { $exitCode = 0 }
    if ($script:SawProblem -and $exitCode -eq 0) { $exitCode = 1 }
    exit $exitCode
}

while ($true) {
    if ($Host.Name -eq 'ConsoleHost') { Clear-Host }
    Show-Menu
    $choice = (Read-Host '  Select').Trim()
    if ($choice -eq '0' -or $choice -eq 'q' -or $choice -eq 'Q') { break }
    try {
        Invoke-MenuAction $choice
    } catch {
        Write-Bad $_.Exception.Message
    }
    Write-Host ''
    Read-Host '  Press Enter to return to the menu' | Out-Null
}
exit 0
