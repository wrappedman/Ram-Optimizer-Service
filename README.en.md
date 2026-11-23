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
build_exe.bat        :: needs Python 3.9+ in PATH
```

The script creates a virtual environment, installs build requirements, runs the
test suite, and produces `release\RamOptimizerService\RamOptimizerService.exe`
(a **onedir** build — a onefile exe regularly fails to answer the Service
Control Manager in time).

### Install the service

```bat
cd release
install_service.bat     :: self-elevates, installs as delayed-auto, starts it
```

The service is registered with three recovery actions, so Windows restarts it
if it crashes. Uninstall with `uninstall_service.bat` (it also offers to delete
`%ProgramData%\RamOptimizer`).

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
| `skip_when_fullscreen` | true | games, presentations, locked screen |
| `skip_on_battery` | false | jump out on battery |
| `quiet_hours` | empty | e.g. `23:00-06:00` |

Plus an exponential **backoff** when a run yields almost nothing, and a
**startup delay** so the service does not fight the boot storm.

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
