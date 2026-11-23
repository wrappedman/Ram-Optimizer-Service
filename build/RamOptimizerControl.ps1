<#
.SYNOPSIS
    RAM Optimizer Service - control panel (install / remove / status / logs).

.DESCRIPTION
    One file that does everything an operator needs. Double-click
    Manage-RamOptimizer.bat (which calls this script), or run one action
    non-interactively:

        RamOptimizerControl.ps1 -Action install
        RamOptimizerControl.ps1 -Action remove
        RamOptimizerControl.ps1 -Action status
        RamOptimizerControl.ps1 -Action logs -Lines 100

    Actions: menu (default), install, remove, status, logs, start, stop,
             restart, test, config, reload, pause, resume, doctor, verify.

    Design notes
    ------------
    * The exe is looked up in this folder first, then ..\dist, then
      ..\release, so the same script works in the source tree, in a release
      zip, and next to a CI-built build\ folder.
    * Administrator rights are requested only for the actions that need them.
    * Exit codes: 0 = success, 1 = failure, 2 = nothing to do / warning.
#>
[CmdletBinding()]
param(
    [ValidateSet('menu', 'install', 'remove', 'status', 'logs', 'start', 'stop',
        'restart', 'test', 'config', 'reload', 'pause', 'resume', 'doctor',
        'verify')]
    [string]$Action = 'menu',

    [int]$Lines = 80,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent $PSCommandPath
$script:ScriptPath = $PSCommandPath
$script:ServiceName = 'RamOptimizerService'
$script:SawProblem = $false
# Actions that need elevation; 'status', 'logs', 'config', 'doctor' and
# 'verify' only read, so a normal user can run them.
$script:NeedsAdmin = @('install', 'remove', 'start', 'stop', 'restart', 'test',
    'reload', 'pause', 'resume')

# ---------------------------------------------------------------------------
# Output helpers: UTF-8 console so Persian text is readable in cmd.exe.
# ---------------------------------------------------------------------------
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    if ($Host.Name -eq 'ConsoleHost') { cmd /c chcp 65001 | Out-Null }
} catch { }

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
}

function Write-Ok([string]$Text) { Write-Host "[OK]   $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "[i]    $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text) {
    Write-Host "[FAIL] $Text" -ForegroundColor Red
    $script:SawProblem = $true
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

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Re-launches this script elevated for one action. Returns $true when the
# caller may continue, $false when everything was already handled.
function Confirm-Admin([string]$ForAction) {
    if (Test-Admin) { return $true }
    Write-Note 'This action needs Administrator rights - asking for elevation...'
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $script:ScriptPath),
        '-Action', $ForAction, '-Lines', $Lines
    )
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait
    } catch {
        Write-Bad 'Elevation was refused. Right-click Manage-RamOptimizer.bat -> Run as administrator.'
    }
    return $false
}

# ---------------------------------------------------------------------------
# Running the exe: output goes to the screen, only the exit code is returned.
# ---------------------------------------------------------------------------
function Invoke-Exe {
    param(
        [Parameter(Mandatory)][string[]]$ExeArgs,
        [switch]$AllowFail
    )
    $exe = Find-Exe
    if (-not $exe) {
        Write-Bad 'RamOptimizerService.exe was not found.'
        Write-Host "       Looked in: $script:Root , ..\dist , ..\release"
        Write-Host '       Build it with build_exe.bat (or unzip the release package here).'
        return 9009
    }
    Write-Host ('       > {0} {1}' -f (Split-Path -Leaf $exe), ($ExeArgs -join ' ')) -ForegroundColor DarkGray
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
    Write-Head 'Installing RAM Optimizer Service'
    if (-not (Confirm-Admin 'install')) { return 2 }
    if (Invoke-Exe -ExeArgs @('service', 'install', '--wait', '25') -AllowFail) {
        Write-Bad 'Installation failed - read the message above, then check the logs (menu 4).'
        return 1
    }
    Invoke-Exe -ExeArgs @('config', '--init') -AllowFail | Out-Null
    $service = Get-ServiceState
    if ($service) {
        Write-Ok "Service installed: state = $($service.Status), startup = $($service.StartType)"
    } else {
        Write-Note 'The service is not visible yet - run status again in a few seconds.'
    }
    Write-Ok "Configuration: $(Join-Path (Get-DataDir) 'config.ini')"
    Write-Note 'It frees unused RAM once a minute, and immediately when RAM is critical.'
    return 0
}

function Invoke-Remove {
    Write-Head 'Removing RAM Optimizer Service'
    if (-not (Confirm-Admin 'remove')) { return 2 }
    if (-not (Get-ServiceState)) {
        Write-Note 'The service is not installed - nothing to remove.'
        if (Test-Path -LiteralPath (Get-DataDir)) {
            Write-Note "Settings and logs are kept in $(Get-DataDir) (delete it for a clean uninstall)."
        }
        return 2
    }
    if (Invoke-Exe -ExeArgs @('service', 'remove', '--wait', '15') -AllowFail) {
        Write-Bad 'Removal failed.'
        return 1
    }
    if (Get-ServiceState) {
        Write-Bad 'The service is still registered - close services.msc, or reboot, then retry.'
        return 1
    }
    Write-Ok 'Service removed.'
    Write-Note "Settings and logs were kept in $(Get-DataDir)."
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
        Write-Ok "Service: installed, state = $($service.Status), startup = $($service.StartType)"
    } else {
        Write-Note 'Service: not installed'
    }

    $statusFile = Join-Path (Get-DataDir) 'status.json'
    if (Test-Path -LiteralPath $statusFile) {
        try {
            $data = Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Host ''
            Write-Host '  status.json (written by the service after every cycle):' -ForegroundColor DarkGray
            Write-Host ($data | Format-List | Out-String -Width 110)
            Write-Host "  Last written: $((Get-Item -LiteralPath $statusFile).LastWriteTime)" -ForegroundColor DarkGray
            if ($null -ne $data.critical) {
                if ($data.critical) { Write-Note 'critical = true: memory is above sustained_trigger_percent.' }
                else { Write-Ok 'critical = false: memory is below the critical threshold.' }
            }
        } catch {
            Write-Note "status.json could not be read: $($_.Exception.Message)"
        }
    } else {
        Write-Note "No status.json yet ($statusFile) - the service has not run a cycle."
    }

    Write-Host ''
    Write-Host '  Live view from the exe:' -ForegroundColor DarkGray
    Invoke-Exe -ExeArgs @('status') -AllowFail | Out-Null
    return 0
}

function Invoke-Logs {
    Write-Head "Logs (last $Lines lines)"
    $log = Join-Path (Get-DataDir) 'ram_optimizer.log'
    $crash = Join-Path (Get-DataDir) 'crash.log'
    if (Test-Path -LiteralPath $log) {
        Write-Host "  $log  ($((Get-Item -LiteralPath $log).Length) bytes)" -ForegroundColor DarkGray
        Get-Content -LiteralPath $log -Tail $Lines -Encoding UTF8 | ForEach-Object { Write-Host $_ }
    } else {
        Write-Note "No log file yet: $log"
    }
    if (Test-Path -LiteralPath $crash) {
        Write-Host ''
        Write-Note "Crash log found: $crash"
        Get-Content -LiteralPath $crash -Tail 40 -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    } else {
        Write-Ok 'No crash.log - no early-startup crashes were recorded.'
    }
    Write-Host ''
    Write-Host '  What to look for:' -ForegroundColor DarkGray
    Write-Host '    "starting the optimization loop ... every 60"   normal one-minute cadence'
    Write-Host '    "critical state ... acting immediately"          the critical path fired'
    Write-Host '    "freed ... MB"                                   an actual release pass'
    return 0
}

function Invoke-Test {
    Write-Head 'Dry run (nothing on the system is changed)'
    if (-not (Confirm-Admin 'test')) { return 2 }
    if (Invoke-Exe -ExeArgs @('test', '--dry-run')) { return 1 }
    Write-Ok 'Dry run finished - the JSON above is what a real pass would decide.'
    return 0
}

function Invoke-Config {
    Write-Head 'Configuration'
    $ini = Join-Path (Get-DataDir) 'config.ini'
    if (-not (Test-Path -LiteralPath $ini)) { Invoke-Exe -ExeArgs @('config', '--init') -AllowFail | Out-Null }
    if (Test-Path -LiteralPath $ini) {
        Write-Ok "Config file: $ini"
        Write-Host '  Keys that control the behaviour:' -ForegroundColor DarkGray
        Select-String -LiteralPath $ini -Pattern 'check_interval_seconds|trigger_percent|reset_percent|sustained_trigger_percent|sustained_polls|critical_poll_seconds' |
            ForEach-Object { Write-Host ('    ' + $_.Line.Trim()) }
        Write-Host ''
        Write-Host '  After editing, apply it to the running service: menu 10 (reload).' -ForegroundColor DarkGray
        if (-not $NoPause) {
            $answer = Read-Host '  Open it in Notepad now? [y/N]'
            if ($answer -match '^[Yy]') { Start-Process notepad.exe -ArgumentList $ini -Wait | Out-Null }
        }
    } else {
        Write-Bad 'config.ini could not be created.'
        return 1
    }
    Invoke-Exe -ExeArgs @('config', '--validate') -AllowFail | Out-Null
    return 0
}

function Invoke-Doctor {
    Write-Head 'Diagnostics'
    Write-Host "  Windows      : $([System.Environment]::OSVersion.VersionString)"
    Write-Host "  PowerShell   : $($PSVersionTable.PSVersion)"
    Write-Host "  64-bit OS    : $([System.Environment]::Is64BitOperatingSystem)"
    Write-Host "  Elevated     : $(Test-Admin)"
    Write-Host "  Data folder  : $(Get-DataDir)"
    Write-Note 'The service must run as LocalSystem to trim other processes working sets.'
    $exe = Find-Exe
    if ($exe) { Write-Ok "Exe: $exe" } else { Write-Bad 'Exe not found.' }
    if (Get-ServiceState) { Write-Ok "Service: $((Get-ServiceState).Status)" } else { Write-Note 'Service: not installed' }
    if ($exe) {
        Write-Host ''
        Invoke-Exe -ExeArgs @('version') -AllowFail | Out-Null
        Invoke-Exe -ExeArgs @('config', '--validate') -AllowFail | Out-Null
        if (Test-Admin) { Invoke-Exe -ExeArgs @('service', 'query') -AllowFail | Out-Null }
    }
    if ($script:SawProblem) { return 1 }
    return 0
}

# One-liner actions: elevate, run, report.
function Invoke-Verb([string]$Action, [string]$Head, [string[]]$ExeArgs) {
    Write-Head $Head
    if (-not (Confirm-Admin $Action)) { return 2 }
    if (Invoke-Exe -ExeArgs $ExeArgs) { return 1 }
    Write-Ok 'Done.'
    return 0
}

function Invoke-Verify {
    # فقط خواندن است: نیازی به elevation ندارد.
    Write-Head 'Scenario check: every minute, and immediately when critical'
    if (Invoke-Exe -ExeArgs @('verify', '--simulate-critical') -AllowFail) { return 1 }
    Write-Ok 'The service trims on a 60 s cycle and reacts to critical memory at once.'
    Write-Host '  For real evidence, leave the service running and select 4 (logs);' -ForegroundColor DarkGray
    Write-Host '  the loop logs both the 60 s cycle and the immediate critical pass.' -ForegroundColor DarkGray
    return 0
}

function Invoke-Named([string]$Action) {
    switch ($Action) {
        'install' { return (Invoke-Install) }
        'remove' { return (Invoke-Remove) }
        'status' { return (Invoke-Status) }
        'logs' { return (Invoke-Logs) }
        'test' { return (Invoke-Test) }
        'config' { return (Invoke-Config) }
        'doctor' { return (Invoke-Doctor) }
        'start' { return (Invoke-Verb 'start' 'Starting the service' @('service', 'start', '--wait', '20')) }
        'stop' { return (Invoke-Verb 'stop' 'Stopping the service' @('service', 'stop', '--wait', '15')) }
        'restart' { return (Invoke-Verb 'restart' 'Restarting the service' @('service', 'restart', '--wait', '20')) }
        'reload' { return (Invoke-Verb 'reload' 'Reloading config.ini' @('reload')) }
        'pause' { return (Invoke-Verb 'pause' 'Pausing trimming' @('pause')) }
        'resume' { return (Invoke-Verb 'resume' 'Resuming trimming' @('resume')) }
        'verify' { return (Invoke-Verify) }
        default { return 2 }
    }
}

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
function Show-Menu {
    $exe = Find-Exe
    $service = Get-ServiceState
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
    Write-Host '   RAM Optimizer Service - Control Panel' -ForegroundColor Cyan
    Write-Host '   پنل مدیریت سرویس بهینه‌ساز حافظه' -ForegroundColor Cyan
    Write-Host ('=' * 68) -ForegroundColor DarkCyan
    if ($exe) { Write-Host "  exe    : $exe" -ForegroundColor DarkGray }
    else { Write-Host '  exe    : NOT FOUND - run build_exe.bat first' -ForegroundColor Red }
    if ($service) { Write-Host "  service: $($service.Status) / $($service.StartType)" -ForegroundColor DarkGray }
    else { Write-Host '  service: not installed' -ForegroundColor DarkGray }
    Write-Host ''
    Write-Host '   1  Install the service              نصب'
    Write-Host '   2  Remove the service               حذف'
    Write-Host '   3  Status                           وضعیت'
    Write-Host '   4  Logs                             لاگ‌ها'
    Write-Host '   5  Start                            اجرا'
    Write-Host '   6  Stop                             توقف'
    Write-Host '   7  Restart                          ری‌استارت'
    Write-Host '   8  Dry run (no changes)             آزمون بی‌خطر'
    Write-Host '   9  Config file (open / validate)    پیکربندی'
    Write-Host '  10  Reload config in the service     بازخوانی پیکربندی'
    Write-Host '  11  Pause / resume trimming          توقف/ادامه‌ی پاک‌سازی'
    Write-Host '  12  Diagnostics                      عیب‌یابی'
    Write-Host '  13  Verify 1-minute / critical mode  بررسی سناریو'
    Write-Host '   0  Exit                             خروج'
    Write-Host ''
}

function Invoke-MenuAction([string]$Choice) {
    switch ($Choice) {
        '1' { Invoke-Named 'install' | Out-Null }
        '2' {
            $answer = Read-Host '  Remove the service? Settings and logs stay. [y/N]'
            if ($answer -match '^[Yy]') { Invoke-Named 'remove' | Out-Null } else { Write-Note 'Cancelled.' }
        }
        '3' { Invoke-Named 'status' | Out-Null }
        '4' {
            $raw = Read-Host "  How many lines? [Enter = $Lines]"
            if ($raw -match '^\d+$') { $script:Lines = [int]$raw }
            Invoke-Logs | Out-Null
        }
        '5' { Invoke-Named 'start' | Out-Null }
        '6' { Invoke-Named 'stop' | Out-Null }
        '7' { Invoke-Named 'restart' | Out-Null }
        '8' { Invoke-Named 'test' | Out-Null }
        '9' { Invoke-Named 'config' | Out-Null }
        '10' {
            Write-Note 'The service re-reads config.ini and applies it without a restart.'
            Invoke-Named 'reload' | Out-Null
        }
        '11' {
            Write-Host ''
            Write-Host '   p = pause trimming (the service keeps running and reporting)'
            Write-Host '   r = resume trimming'
            $answer = Read-Host '   Choice [p/r]'
            if ($answer -match '^[Pp]') { Invoke-Named 'pause' | Out-Null }
            elseif ($answer -match '^[Rr]') { Invoke-Named 'resume' | Out-Null }
            else { Write-Note 'Cancelled.' }
        }
        '12' { Invoke-Named 'doctor' | Out-Null }
        '13' { Invoke-Named 'verify' | Out-Null }
        default { Write-Note "Unknown option: $Choice" }
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
    if (-not $NoPause) {
        Write-Host ''
        Read-Host '  Press Enter to return to the menu' | Out-Null
    }
}
exit 0
