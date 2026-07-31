# BitaxePID Auto-Tuner

![logo](docs/assets/bitaxepid-logo.jpg)

## Overview

BitaxePID is an auto-tuning utility for Bitaxe open-source Bitcoin ASIC miners
(BM1366, BM1368, BM1370 and BM1397). It adjusts core voltage and frequency to
find the fastest setting the chip sustains, keeping temperature, power and
hardware error rate within limits. It provides a cyberpunk-themed TUI for
real-time monitoring; tuning data is logged to CSV and persisted to a JSON
snapshot.

> **This fork no longer contains a PID controller.** Not one. The name is
> historical. Hashrate is not a target either — it is a *result* of voltage and
> frequency, so `HASHRATE_SETPOINT` is read by nothing and only fills a CSV
> column. Two strategies are available and `ERROR_TUNING` selects between them;
> see [Tuning strategies](#tuning-strategies). If you are looking for the
> upstream PID behaviour, this is not it.

### Note

Upgrades may require updates to all files. You should either download the FULL
release for a version, or clone the main repo.

![example running](docs/assets/screenshot6.jpg)

---

### Intent

- **Performance optimization**: adjusts voltage and frequency within the limits
  declared in the chip's YAML file, looking for the highest sustainable frequency
  and the lowest voltage that holds it.
- **Thermal and power management**: safety comes first. If temperature exceeds
  `TARGET_TEMP` or power exceeds `POWER_LIMIT * 1.075`, the tuner lowers settings
  regardless of what that costs in hashrate.
- **Stability**: decisions are made on a rolling median of the miner's hardware
  error rate, not on a single reading, because that signal is noisy.
- **Non-intrusive by default**: BitaxePID does not touch the miner's stratum
  pool configuration unless you explicitly allow it. See
  [Pool management](#pool-management).
- **User experience**: a rich TUI with ANSI-art hashrate display, system stats,
  progress bars and a scrolling log, alongside file-based logging.

### Hardware context

The Bitaxe family (values below for the Ultra/Supra class boards):

- BM1366 ASIC: 0.021 J/GH efficiency.
- Power: 5V DC, 15W max, via TI TPS40305 buck regulator and Maxim DS4432U+ DAC.
- Control: ESP32-S3-WROOM-1 for WiFi/API, with INA260 power meter and EMC2101
  for fan/temperature monitoring.
- Cooling: requires a 40x40mm fan.

## Features

- **Model-specific configuration**: one YAML per ASIC model, plus an optional
  user YAML that overrides individual keys via `--config`.
- **Two tuning strategies**: selected by `ERROR_TUNING`. See
  [Tuning strategies](#tuning-strategies).
- **Safety constraints**: respects the power limit and the voltage/frequency
  bounds of the configured chip.
- **Snapshot**: writes the last applied pair to
  `bitaxepid_snapshot_<model>.json`. Note it is **written but never read back** —
  every run starts from `INITIAL_VOLTAGE`/`INITIAL_FREQUENCY`, not from where the
  previous one stopped.
- **TUI display**: cyberpunk-style interface with ANSI-art GH/s, system stats,
  progress bars and a scrolling log. `--log-to-console` disables it.
- **Logging**: `bitaxepid_monitor.log` plus a CSV tuning log.
- **Optional metrics endpoint**: JSON over HTTP on port 8093, enabled with
  `--serve-metrics`. Note it serves plain JSON, not the Prometheus text
  exposition format, so Prometheus cannot scrape it directly; it is useful as-is
  for a browser, `curl`, or anything that reads JSON.

## Installation

Requires **Python 3.9 or newer** (the code uses builtin generics such as
`tuple[str, int]`).

Install the dependencies declared in `requirements.txt`:

```bash
pip install -r requirements.txt
```

Or create a virtual environment with [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
bash scripts/setup.sh
```

The scripts under `scripts/` can be run from any directory; they resolve paths
relative to the repository root.

## Containers

### docker compose

The easiest way to leave the tuner running on a machine that is already on all
the time (an Umbrel node, a Raspberry Pi, a NAS):

```bash
cp .env.example .env      # put your miner IP in BITAXEPID_MINER_IP
docker compose up -d --build
docker compose logs -f
```

[UMBREL.md](UMBREL.md) walks through this on an Umbrel node step by step, in
Spanish: what the startup log should look like, how to check the limits are
actually in place, and what is verified and what is not.

`docker compose down` stops it. The default profile is
`safe-BM1370-estabilidad.yaml` (stability strategy, see below); change
`BITAXEPID_CONFIG` in `.env` for a different one. Unsetting it is a bad idea: you
get the factory limits of whichever chip the miner reports, with `ERROR_TUNING`
undeclared and therefore the other strategy.

The tuning CSV and the snapshot are written to `./data`, which is mounted into
the container, so they survive `docker compose down`. Metrics are published on
the host port set by `BITAXEPID_METRICS_PORT` (8093 by default).

The container talks to the miner over HTTP on the LAN through the default bridge
network: it needs no extra privileges and no host networking. It also means it
cannot discover the miner by mDNS, so give the miner a fixed address — a DHCP
reservation in your router is enough.

### podman

```bash
podman build --tag bitaxepid-container .
podman run -it --publish 8093:8093 bitaxepid-container 192.168.68.111
```

Extra flags are passed through to the tuner, so
`podman run ... bitaxepid-container 192.168.68.111 --manage-pools` works.

## Safe limits

`MIN_VOLTAGE`, `MAX_VOLTAGE`, `MIN_FREQUENCY` and `MAX_FREQUENCY` are hard
limits: no value outside that range is ever sent to the miner. Both paths that
write to the hardware are clamped — the initial value (in `validate_config`,
after the command-line overrides are applied) and every proposal from the tuning
strategy (at the end of `apply_strategy`). A clamped initial value is logged as
a warning rather than being applied silently.

`TARGET_TEMP` is not a limit but a setpoint: above it, the tuner lowers
frequency first and then voltage, one step per sample.

`safe-BM1370.yaml` is a conservative profile for the Bitaxe Gamma, meant to be
passed with `--config` on top of `BM1370.yaml`:

```bash
python bitaxepid.py --ip 192.168.68.111 --config safe-BM1370.yaml
```

It caps frequency at 500 MHz (factory 625) and voltage at 1150 mV (factory 1250),
targets 55 °C, and declares **all four** bounds rather than only the two maxima.
That matters: every key a profile does not declare is inherited from the chip
YAML, so declaring only the ceilings left the floors at the factory 1000 mV /
400 MHz — an effective range of 1000-1150 mV in a profile called "safe". The floor
is where the minimum-voltage search and the thermal branch bottom out, and a
BM1370 does not mine stably at 1000 mV.

`safe-BM1370-estabilidad.yaml` is the other profile, and the default for
`docker compose`: it declares all 32 readable keys explicitly (inheriting
nothing), runs the stability strategy, and is the one tested on real hardware.

A profile passed with `--config` must exist and must be readable: the program
exits rather than falling back to the chip defaults, because silently running
with factory limits when you believe otherwise is worse than not starting.

## Usage

Run the tuner with the Bitaxe IP address and optional arguments:

```bash
python bitaxepid.py --ip 192.168.68.111 --config custom_config.yaml --voltage 1200 --frequency 500
```

Or, with the uv virtual environment created by `scripts/setup.sh`:

```bash
bash scripts/start.sh 192.168.68.111
```

Full option list:

```text
usage: bitaxepid.py [-h] [--version] --ip IP [--config CONFIG] [--user-file USER_FILE] [--pools-file POOLS_FILE]
                    [--primary-stratum PRIMARY_STRATUM] [--backup-stratum BACKUP_STRATUM]
                    [--stratum-user STRATUM_USER] [--fallback-stratum-user FALLBACK_STRATUM_USER] [--voltage VOLTAGE]
                    [--frequency FREQUENCY] [--sample-interval SAMPLE_INTERVAL] [--log-to-console]
                    [--logging-level {info,debug}] [--serve-metrics] [--manage-pools]

BitaxePID Auto-Tuner

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --ip IP               IP address of the Bitaxe miner
  --config CONFIG       Path to optional user YAML configuration file
  --user-file USER_FILE
                        Path to user YAML file (default: from config)
  --pools-file POOLS_FILE
                        Path to pools YAML file (default: from config)
  --primary-stratum PRIMARY_STRATUM
                        Primary stratum URL (e.g., stratum+tcp://host:port)
  --backup-stratum BACKUP_STRATUM
                        Backup stratum URL (e.g., stratum+tcp://host:port)
  --stratum-user STRATUM_USER
                        Stratum user for primary pool
  --fallback-stratum-user FALLBACK_STRATUM_USER
                        Stratum user for backup pool
  --voltage VOLTAGE     Initial voltage override (mV)
  --frequency FREQUENCY
                        Initial frequency override (MHz)
  --sample-interval SAMPLE_INTERVAL
                        Sample interval override (seconds)
  --log-to-console      Log to console instead of UI
  --logging-level {info,debug}
                        Logging level
  --serve-metrics       Serve metrics via HTTP on port 8093 (default: False)
  --manage-pools        Permitir que BitaxePID reconfigure los pools stratum del miner y lo reinicie al arrancar
                        (default: False, no se toca la configuracion de pools existente)
```

## Pool management

By default BitaxePID **leaves the miner's stratum configuration alone**. Your
miner may be pointed at a pool you chose deliberately, and rewriting that
without being asked is intrusive. With pool management disabled the tuner reads
the miner's state, adjusts voltage and frequency, and nothing else — it does not
call `set_stratum`, does not measure pool latencies and does not rewrite
`pools.yaml`.

Enable it either per run or in the configuration file:

```bash
python bitaxepid.py --ip 192.168.68.111 --manage-pools
```

```yaml
MANAGE_MINER_POOLS: TRUE
```

Two consequences worth knowing before you enable it:

- BitaxePID measures the latency of every pool in `pools.yaml`, picks the two
  fastest, writes them to the miner and **restarts it**. Give it a couple of
  minutes to come back.
- Conversely, with pool management disabled the miner is **not** restarted at
  startup either, because the restart is part of the stratum sequence. This is
  deliberate.

Explicit endpoints (`--primary-stratum`, `PRIMARY_STRATUM` in the config) also
require `--manage-pools`: without it they are stored but never applied.

## Configuration notes

Default settings come from the ASIC model YAML file (`BM1366.yaml`,
`BM1368.yaml`, `BM1370.yaml`, `BM1397.yaml`). If `--config` is provided, its
keys override the model defaults. Command-line options such as `--voltage`,
`--frequency` and `--sample-interval` override both.

The following 14 keys are mandatory; the program exits if any is missing:
`INITIAL_VOLTAGE`, `INITIAL_FREQUENCY`, `SAMPLE_INTERVAL`, `LOG_FILE`,
`SNAPSHOT_FILE`, `POOLS_FILE`, `MIN_VOLTAGE`, `MAX_VOLTAGE`, `MIN_FREQUENCY`,
`MAX_FREQUENCY`, `VOLTAGE_STEP`, `FREQUENCY_STEP`, `TARGET_TEMP`, `POWER_LIMIT`.

With `ERROR_TUNING` off, seven more are required: `PID_FREQ_KP/KI/KD`,
`PID_VOLT_KP/KI/KD` and `HASHRATE_SETPOINT`. **Nothing reads them to decide
anything** — they only fill seven CSV columns, kept so a new history stays
comparable with older ones on that strategy. They are not required with
`ERROR_TUNING: TRUE`.

Everything else is optional and falls back to a default declared in one place,
`CLAVES_OPCIONALES` in `config.py`. Startup logs a warning listing every optional
key you did not declare and the value it will use instead. `ERROR_TUNING` gets a
warning of its own, because its default is `FALSE` — that is not a nuance, it is
the *other strategy*.

### Example configuration file (`BM1366.yaml`)

```yaml
# BM1366.yaml
INITIAL_FREQUENCY: 485       # "485 (default)" from BM1366DropdownFrequency
MIN_FREQUENCY: 400           # lowest available frequency in BM1366DropdownFrequency
MAX_FREQUENCY: 575           # highest available frequency in BM1366DropdownFrequency
INITIAL_VOLTAGE: 1200        # "1200 (default)" from BM1366CoreVoltage
MIN_VOLTAGE: 1100            # lowest available voltage in BM1366CoreVoltage
MAX_VOLTAGE: 1300            # highest available voltage in BM1366CoreVoltage
FREQUENCY_STEP: 25
VOLTAGE_STEP: 10
TARGET_TEMP: 55.0
SAMPLE_INTERVAL: 60
POWER_LIMIT: 15.0
HASHRATE_SETPOINT: 525
PID_FREQ_KP: 0.2
PID_FREQ_KI: 0.01
PID_FREQ_KD: 0.02
PID_VOLT_KP: 0.1
PID_VOLT_KI: 0.01
PID_VOLT_KD: 0.02
LOG_FILE: "bitaxepid_tuning_log_BM1366.csv"
SNAPSHOT_FILE: "bitaxepid_snapshot_BM1366.json"
POOLS_FILE: "pools.yaml"
METRICS_SERVE: false         # yaml boolean lowercase true/false
MANAGE_MINER_POOLS: FALSE    # see "Pool management" above
USER_FILE: "user.yaml"       # only used if stratumUser is blank on the Bitaxe
# PRIMARY_STRATUM: "stratum+tcp://stratum.solomining.io:7777"
# BACKUP_STRATUM: "stratum+tcp://stratum.solomining.io:7777"
```

## Tuning strategies

There is no PID controller in this fork. `ERROR_TUNING` picks one of two
rule-based strategies. Neither one targets a hashrate.

Every decision is printed with its reason (in Spanish, via `rich` on stdout), so
you can see why the tuner moved.

### `ERROR_TUNING: TRUE` — stability search (`tuning_estabilidad.py`)

The recommended one, and the only one tested on real hardware. A state machine:

1. **RAMPA** — raise voltage to `MAX_VOLTAGE`, then walk frequency up one
   `FREQUENCY_STEP` per sample until `TARGET_TEMP` stops it. That is the highest
   and most stable point available.
2. **BUSCAR_VOLTAJE** — lower voltage step by step until the hardware error rate
   reaches `ERROR_TARGET_PERCENT`, then back off one step. What remains is the
   *minimum* voltage that meets the target.
3. **OPTIMIZAR** — errors above target raise voltage; comfortable thermal margin
   raises frequency; and only with frequency already at the ceiling does it keep
   trying to lower voltage further.

Decisions use the **median** of the last `ERROR_WINDOW` samples, discarding
`ERROR_SETTLE` samples after each change. The miner's `errorPercentage` is noisy
enough that a single reading crosses any threshold in both directions.

### `ERROR_TUNING` absent or `FALSE` — limit-based (`tuning.py`)

Despite the `PIDTuningStrategy` class name, no PID. Five rules by priority:

1. Temperature above `TARGET_TEMP` → lower frequency (then voltage, if frequency
   is already at the floor).
2. Power above `POWER_LIMIT * 1.075` → lower voltage.
3. Errors above `ERROR_TARGET_PERCENT` → raise voltage.
4. Thermal margin available → raise frequency.
5. Several stable samples in a row → lower voltage, looking for the minimum.

Steps and limits live in the model YAML file; tune them there rather than in the
code.

## Architecture

Twelve flat modules, one responsibility each, no subpackages and no abstract
base class layer:

| Module | Responsibility |
| --- | --- |
| `bitaxepid.py` | Entry point: wires everything together and handles signals. |
| `cli.py` | Command-line arguments. |
| `config.py` | Loads and validates the YAML configuration. |
| `api_client.py` | HTTP client for the miner's API (`urllib3`). |
| `stratum.py` | Pool file handling, endpoint parsing and latency measurement. |
| `tuning.py` | Limit-based strategy (`ERROR_TUNING` off): decides the next voltage/frequency pair. |
| `tuning_estabilidad.py` | Stability strategy (`ERROR_TUNING: TRUE`), the default. |
| `tuning_manager.py` | The tuning loop and the startup sequence. |
| `logger.py` | CSV tuning log and JSON snapshot. |
| `metrics_server.py` | Optional HTTP metrics endpoint on port 8093. |
| `ui_rich.py` | The TUI, plus the colour theme and the shared `Console`. |
| `ui_null.py` | No-op UI used by `--log-to-console`. |

Dependencies only point one way: `bitaxepid.py` composes the objects, and the
lower modules never import it.

```mermaid
graph TD
    main[bitaxepid.py] --> cli[cli.py]
    main --> config[config.py]
    main --> api[api_client.py]
    main --> tuning[tuning.py]
    main --> test[tuning_estabilidad.py]
    main --> tm[tuning_manager.py]
    main --> logger[logger.py]
    main --> metrics[metrics_server.py]
    main --> uirich[ui_rich.py]
    main --> uinull[ui_null.py]
    main --> stratum[stratum.py]
    tm --> api
    tm --> stratum
    tm --> logger
    tm --> metrics
    tm --> config
    tm --> tuning
    tm --> test
    tm --> uirich
    tm --> uinull
    tuning --> uirich
    test --> uirich
```

Startup order matters and is explicit: constructing a `TuningManager` has no
side effects, and everything that talks to the miner happens in
`connect_and_configure()`. That is what makes the manager testable without a
miner on the network.

`stratum.py` can also be run on its own to measure pools and print the result:

```bash
python stratum.py            # YAML to stdout, log to stderr
```

## Tests

Unit tests need no miner and no network:

```bash
python -m unittest discover -s tests -t .
```

`scripts/smoke_test.sh` is a broader safety net: it byte-compiles every module,
checks by AST analysis that no module uses a name it neither defines nor imports
(the failure mode of moving code between files), validates the configuration
files against the keys the code actually requires, checks `requirements.txt`
**both ways** (nothing imported is undeclared, and nothing declared goes
unimported — the `Containerfile` installs that file verbatim, so a stale entry
ships a package that never runs) and then runs the unit tests. Checks that need
third-party packages are skipped, not failed, when those packages are absent.

On Windows, where the interpreter is `python` rather than `python3`:

```bash
PYTHON=python bash scripts/smoke_test.sh
```

```bash
bash scripts/smoke_test.sh
```

## Credits

Based on concepts and code from
[Hurllz/bitaxe-temp-monitor](https://github.com/Hurllz/bitaxe-temp-monitor/).

Extensively refactored: split into single-responsibility modules, and later
rewritten to drop the PID controllers and the hashrate setpoint in favour of the
two rule-based strategies described above.
