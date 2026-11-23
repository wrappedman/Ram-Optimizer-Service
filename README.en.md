# RAM Optimizer Service

A quiet Windows service that frees memory **only when it is actually needed**.

It combines the two mechanisms used by tools like RAMMap and Wise Memory
Optimizer, but adds the safety rules those tools usually skip:

1. **`EmptyWorkingSet`** on eligible processes → releases pages a program holds
   but does not use.
2. **Standby-list purge** (RAMMap's “Empty Standby List”) — **only if memory is
   still tight after step 1**.

> **Honest note:** modern Windows manages memory well, and a large part of what
> Task Manager shows as “In use” is the **standby cache**, which Windows keeps on
> purpose. Emptying it constantly makes the system slower, not faster. This tool
> therefore triggers on real memory pressure, leaves the cache alone unless the
> system is genuinely short on memory, and reports measured numbers instead of
> marketing ones.

Current version: **2.0.0** — see [CHANGELOG.md](CHANGELOG.md).
Persian documentation (کامل‌تر): [README.md](README.md).

---

## Quick start

### Build the executable

```bat
build_exe.bat        :: Python 3.9 - 3.15 (PyInstaller 6.22 supports <3.16)
                     :: pick one explicitly with  build_exe.bat -Python "py -3.13"
```

The script creates a virtual environment, installs build requirements, runs the
test suite, and produces `build\RamOptimizerService\RamOptimizerService.exe`
(a **onedir** build — a onefile exe regularly fails to answer the Service
Control Manager in time).

### Install the service — one file does everything

```bat
build\Manage-RamOptimizer.bat      :: menu: install / remove / status / logs / ...
build\Manage-RamOptimizer.bat install
build\Manage-RamOptimizer.bat remove
build\Manage-RamOptimizer.bat status
build\Manage-RamOptimizer.bat logs -Lines 200
```

`build\` contains:

| File | Purpose |
|---|---|
| `Manage-RamOptimizer.bat` | the control panel (double-click it) |
| `RamOptimizerControl.ps1` | its logic — batch is only a thin launcher |
| `build_exe.bat` | rebuilds the exe from source |
| `RamOptimizerService\` | PyInstaller output (the exe and its files) |
| `build_info.json`, `SHA256SUMS.txt` | what was built, from which commit, with which hash |

The panel is **plain ASCII and English only** on purpose: it has to run on
stock Windows PowerShell 5.1 and inside any console code page. (An earlier
version built Persian labels from `` `u{...}`` escapes — PowerShell 6+ syntax
that 5.1 prints literally, without any error, so the menu showed
`` `u{067E}`u{0646}… `` instead of text. Never again: a test now rejects
non-ASCII output.)

```
============================================================
  RAM Optimizer Service  -  Control Panel
============================================================
  exe             RamOptimizerService
  path            C:\...\build\RamOptimizerService\RamOptimizerService.exe
  service         RUNNING  (Automatic)
  last cycle      78% used, normal

  SERVICE
    1  Install          2  Remove
    3  Status           4  Logs

  CONTROL
    5  Start            6  Stop
    7  Restart         10  Reload configuration
   11  Pause / resume trimming

  INSPECT
    8  Dry run (no changes)   9  Configuration
   12  Diagnostics           13  Behaviour check
   14  Repair installation

    0  Exit
```

Menu items: 1 install, 2 remove, 3 status, 4 logs, 5-7 start/stop/restart,
8 dry run, 9 config file, 10 reload config, 11 pause/resume trimming,
12 diagnostics, 13 verify the 1-minute/critical behaviour, 14 repair
the installed service's exe path, 0 exit.

### Or use the installer

```bat
build_exe.bat
iscc installer\ramopt.iss     :: Inno Setup 6 → installer\Output\*-setup.exe
```

The installer handles upgrades properly, removes the service on uninstall, and
registers the Event Log source.

### Try it without installing anything

```bat
RamOptimizerService.exe test --dry-run    :: shows the decision, changes nothing
RamOptimizerService.exe test --force      :: optimizes now, ignoring thresholds
RamOptimizerService.exe console           :: run in the foreground
```

---

## What it does and when

Every `check_interval_seconds` (default 60 s) it reads the real memory state
(`GlobalMemoryStatusEx`) and decides whether to act:

| Rule | Default | Meaning |
|---|---|---|
| `trigger_percent` | 75 | start optimizing at this used % |
| `reset_percent` | 65 | go back to idle below this (hysteresis, no flapping) |
| `cooldown_seconds` | 300 | minimum gap between two optimizations |
| `max_purges_per_hour` | 6 | hard cap per hour (`0` = unlimited) |
| `min_available_mb` | 0 | never act while this much RAM is free |
| `min_free_mb_after_trim` | 512 | purge the cache only if still short after trimming |
| `min_process_ws_mb` | 20 | ignore tiny processes (no benefit, pure syscalls) |
| `max_processes` | 64 | trim the biggest N processes first |
| `exclude` / `exclude_patterns` | system-critical + AV | never touch these |
| `sustained_trigger_percent` | 92 | **critical**: act at once, ignoring cooldown |
| `sustained_polls` | 1 | consecutive polls above critical before acting |
| `critical_poll_seconds` | 5 | poll interval while memory stays critical |
| `critical_probe_seconds` | 2 | cheap mid-wait probe so a critical spike is not missed |
| `skip_when_fullscreen` | true | games, presentations, locked screen |
| `skip_on_battery` | false | jump out on battery |
| `quiet_hours` | empty | e.g. `23:00-06:00` |

Plus an exponential **backoff** when a run yields almost nothing, and a
**startup delay** so the service does not fight the boot storm.

### One-minute cycle, immediate action at the critical point

* Normal path: one cycle every `check_interval_seconds` (60 s).
* Critical path: as soon as used RAM reaches `sustained_trigger_percent` (92 %),
  the release pass runs **in that same cycle** — the cooldown, the hourly cap and
  `min_available_mb` are bypassed (an explicit `pause` still wins).
* Between cycles the loop only calls `GlobalMemoryStatusEx` every
  `critical_probe_seconds` (2 s). If RAM turns critical while the service is
  sleeping its one-minute wait, it wakes up immediately instead of waiting for
  the next minute.
* After a critical pass it polls every `critical_poll_seconds` (5 s) until memory
  comes back below the threshold, then returns to 60 s.

Verify it on your own machine — nothing on the system is changed:

```bat
RamOptimizerService.exe verify --simulate-critical
RamOptimizerService.exe verify --watch 60
```

The log then shows, in order:

```
حلقه‌ی بهینه‌سازی شروع شد | بررسی عادی هر 60 ثانیه | در وضعیت بحرانی (≥92%) هر 5 ثانیه (پایش هر 2 ثانیه)
حافظه در فاصله‌ی بین دو چرخه بحرانی شد (≥92%) — چرخه‌ی بعدی همین حالا اجرا می‌شود ...
وضعیت بحرانی: مصرف 93.8% ≥ 92% (آستانه‌ی عادی 75%) — اجرای فوری.
```

Covered by `tests/test_scenario_logs.py` and `tests/test_critical_mode.py`.

---

## Configuration

`%ProgramData%\RamOptimizer\config.ini` — created by `config --init`, validated
on load (`config --validate`). Invalid keys or values are reported in the log and
the built-in default is used, so a broken file can never brick the service.

No rebuild is needed: edit the file, then restart the service.

---

## Command line

```
RamOptimizerService.exe version | status [--json]
RamOptimizerService.exe config --init | --show | --validate
RamOptimizerService.exe test [--dry-run] [--force] [--json]
RamOptimizerService.exe console | once
RamOptimizerService.exe service install|remove|start|stop|restart|pause|continue|query|repair
RamOptimizerService.exe log --lines 50
RamOptimizerService.exe pause | resume | reload
RamOptimizerService.exe verify [--simulate-critical] [--watch N]
```

From a source checkout, `python -m ramopt …` and the `ramopt` entry point expose
the same commands.

---

## Monitoring

- `ram_optimizer.log` — rotating, only logs meaningful events plus an hourly
  heartbeat.
- `status.json` — machine readable: state, last action, last reason, memory,
  counters (`purges`, `freed_mb`, `errors`, `cycles`), recent errors.
- `crash.log` — rotating crash log, includes uncaught thread exceptions.
- Windows **Event Log** under source `RamOptimizerService`.

Reports distinguish “trimmed N processes”, “access denied for M processes”,
“standby purge skipped because X MB were already free”. A cycle that did nothing
is logged as `skipped` with the exact reason — never as success.

---

## Development

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt

pytest -q                       # 70+ tests; Windows-only ones skip elsewhere
ruff check . && ruff format --check .
mypy ramopt

python -m ramopt test --dry-run
```

Layout:

```
ramopt/
  config.py         configuration + validation
  engine.py         policy and cycle execution (OS-independent, fully tested)
  memory.py         measurement + trim/purge operations
  win32.py          the only place ctypes/Win32 is used
  service.py        pywin32 service class (pause/continue/preshutdown)
  service_admin.py  install/remove/control with recovery actions
  runner.py         shared loop for service/console/scheduled task
  status.py         status.json writer
  logging_setup.py  rotating file + Event Log + crash log
  cli.py            argparse CLI
tests/              pytest; FakeApi simulates Windows so policy is testable anywhere
installer/          Inno Setup script
.github/workflows/  CI: Linux (lint/tests) + real Windows (tests + exe build + smoke test)
```

### Code signing

Unsigned PyInstaller executables that call `OpenProcess` on every process look
like malware to antivirus heuristics. The only real fix is a code-signing
certificate. Put `signtool` in `[Setup] SignTool=` and sign the exe after building.

---

## Troubleshooting

**“The service did not respond to the start or control request in a timely fashion”**
Remove the old installation, rebuild (`build_exe.bat`, which uses onedir on
purpose), reinstall. Then run `RamOptimizerService.exe console` in an admin
prompt to see the real error, and check `crash.log`.

**The service runs but does nothing**
`RamOptimizerService.exe status` → `last_reason` tells you why (startup delay,
cooldown, fullscreen, …). `test --dry-run` shows the current decision.

**License** GPLv3 — [LICENSE](LICENSE)
