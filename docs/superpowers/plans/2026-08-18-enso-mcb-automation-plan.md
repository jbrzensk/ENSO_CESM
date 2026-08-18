# ENSO-MCB Automated Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the full ENSO-MCB experiment cycle (run → check June Niño3.4 warming → branch + MCB on 3 months → MCB off → resubmit) as a self-perpetuating chain of PBS jobs on Derecho, replacing the current manual download-and-check workflow.

**Architecture:** A single stateful Python orchestrator (`enso_mcb_orchestrator.py`) implements a 3-state machine (`RUNNING` / `MCB_ON` / `MCB_COOLDOWN`) persisted in a small JSON state file. Each PBS invocation performs exactly one transition — including shelling out to `check_warming.py` for the Niño3.4 anomaly check and to `create_branch_case.sh` for new branch cases — then resubmits itself as a new PBS job dependent on the CESM segment's archive job, and exits. Decision logic (pure functions) is separated from I/O (subprocess calls) so the state machine and the warming computation are unit-testable without touching PBS or `/glade`.

**Tech Stack:** Python 3.9+, `xarray` + `netCDF4` (Niño3.4 computation), `PyYAML` (config), `pytest` (tests), Bash (case-creation script, PBS wrapper).

**Spec:** [docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md](../specs/2026-08-17-enso-mcb-automation-design.md)

## Global Constraints

- Warming threshold default: **1.0°C**, read from `enso_mcb_config.yaml`, never hardcoded in logic.
- `RUNNING` segments: `STOP_N=12`, `STOP_OPTION=nmonths`, `RESUBMIT=0` — the orchestrator resubmits explicitly every year; CIME's auto-resubmit is never used for orchestrator-controlled segments.
- `MCB_ON` segment: `STOP_N=3` (Jun–Aug), `MCB_seeding_amt=1`.
- `MCB_COOLDOWN` segment: `STOP_N=4` (Sep–Dec), `MCB_seeding_amt=0`, same case directory as `MCB_ON`.
- End year: **2100**, read from config.
- Branch numbering is fully mechanical: new branch number is always the previous case's branch number + 1; `refcase` is always the case that just finished; `startdate` is always computed from state, never hand-entered.
- Every PBS job this system submits (CESM run jobs and orchestrator jobs) is submitted with `-m ae -M <notification_email>` so aborts/failures email the user — no silent unattended failures.
- No automatic retries. Any stage failure halts the chain (the orchestrator does not resubmit itself) and records `FAILED` in the state file.
- The orchestrator's self-resubmission depends on the segment's **archive job** (`st_archive`), not just the run job, since the warming check reads from archived output — `DOUT_S` must be `TRUE` on every case in the lineage (verified in the runbook's pre-flight checklist; the existing script sets `DOUT_S_ROOT` but does not explicitly force `DOUT_S=TRUE`, so this plan sets it explicitly rather than relying on CIME defaults).
- The exact `case.submit` stdout job-ID format and the exact POP history file path/naming are unverified against a real Derecho case (flagged in the spec as an open item) — code parses a documented, sensible format now; Task 9 (runbook) tells the operator how to verify and adjust before the first live run.

---

## Task 1: Project scaffolding, dependencies, and config loader

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `conftest.py`
- Create: `.gitignore`
- Create: `enso_mcb_config.yaml`
- Create: `enso_mcb_config.py`
- Test: `tests/test_enso_mcb_config.py`

**Interfaces:**
- Produces: `load_config(path: str) -> dict` — used by every later task that needs config values. Raises `ValueError` if required keys are missing.

- [ ] **Step 1: Create scaffolding files**

`requirements.txt`:
```
xarray>=2023.1.0
netCDF4>=1.6.0
numpy>=1.24.0
PyYAML>=6.0
pytest>=7.0.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

`conftest.py` (repo root — makes repo-root modules importable from `tests/`):
```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
```

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
```

- [ ] **Step 2: Create a virtualenv and install dependencies**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Expected: install completes with no errors.

- [ ] **Step 3: Write the failing test**

`tests/test_enso_mcb_config.py`:
```python
import textwrap

import pytest

from enso_mcb_config import load_config


VALID_CONFIG = textwrap.dedent("""\
    ens: "1051"
    resoln: "f09_g17"
    compset: "BSSP370smbb"
    project: "UCSD0083"
    srcdir: "/tmp/srcdir"
    tagdir: "/tmp/tagdir"
    caseroot: "/tmp/caseroot"
    scratchroot: "/tmp/scratchroot"
    climatology_file: "/tmp/clim.nc"
    warming_threshold_c: 1.0
    end_year: 2100
    notification_email: "test@example.edu"
    python_exe: "python3"
    check_warming_script: "check_warming.py"
    create_branch_case_script: "create_branch_case.sh"
    orchestrator_wrapper_script: "orchestrator_wrapper.sh"
""")


def test_load_config_reads_all_required_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG)

    config = load_config(str(config_path))

    assert config["ens"] == "1051"
    assert config["warming_threshold_c"] == 1.0
    assert config["end_year"] == 2100


def test_load_config_raises_on_missing_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('ens: "1051"\n')

    with pytest.raises(ValueError, match="missing required keys"):
        load_config(str(config_path))
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_enso_mcb_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enso_mcb_config'`

- [ ] **Step 5: Write the config loader and default config file**

`enso_mcb_config.py`:
```python
import yaml

REQUIRED_KEYS = [
    "ens", "resoln", "compset", "project", "srcdir", "tagdir",
    "caseroot", "scratchroot", "climatology_file", "warming_threshold_c",
    "end_year", "notification_email", "python_exe", "check_warming_script",
    "create_branch_case_script", "orchestrator_wrapper_script",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"{path} is missing required keys: {missing}")
    return config
```

`enso_mcb_config.yaml`:
```yaml
ens: "1051"
resoln: "f09_g17"
compset: "BSSP370smbb"
project: "UCSD0083"
srcdir: "/glade/work/walkerl/MCB_mods/bugfix_plus_namelist"
tagdir: "/glade/work/walkerl/cesm_tags/cesm2.1.5+MCBnl"
caseroot: "/glade/work/walkerl/cases"
scratchroot: "/glade/derecho/scratch/walkerl"

# TODO(user): fill in the path to the fixed Nino3.4 June climatology
# reference file before running this for real. See the "Open item" in
# docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md.
climatology_file: "/glade/work/walkerl/enso_mcb_automation/climatology/nino34_june_climatology.nc"

warming_threshold_c: 1.0
end_year: 2100
notification_email: "walkerl@example.edu"

python_exe: "python3"
check_warming_script: "check_warming.py"
create_branch_case_script: "create_branch_case.sh"
orchestrator_wrapper_script: "orchestrator_wrapper.sh"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_enso_mcb_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini conftest.py .gitignore \
        enso_mcb_config.yaml enso_mcb_config.py tests/test_enso_mcb_config.py
git commit -m "Add project scaffolding and config loader"
```

---

## Task 2: Lineage state module

**Files:**
- Create: `enso_mcb_state.py`
- Test: `tests/test_enso_mcb_state.py`

**Interfaces:**
- Consumes: nothing (no dependency on Task 1's code, only stdlib).
- Produces: `Stage` (class of string constants: `RUNNING`, `MCB_ON`, `MCB_COOLDOWN`, `FAILED`, `DONE`), `CycleState` dataclass (`lineage_name: str, case_name: str, stage: str, branch_number: int, year: int`), `load_state(path: str) -> CycleState`, `save_state(path: str, state: CycleState) -> None`. Used by Tasks 5, 6, 7.

- [ ] **Step 1: Write the failing test**

`tests/test_enso_mcb_state.py`:
```python
from enso_mcb_state import CycleState, Stage, load_state, save_state


def test_save_and_load_state_round_trip(tmp_path):
    state_path = tmp_path / "state.json"
    state = CycleState(
        lineage_name="enso_mcb_1051",
        case_name="b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
        stage=Stage.RUNNING,
        branch_number=8,
        year=2054,
    )

    save_state(str(state_path), state)
    loaded = load_state(str(state_path))

    assert loaded == state


def test_save_state_is_atomic_leaves_no_tmp_file(tmp_path):
    state_path = tmp_path / "state.json"
    state = CycleState(
        lineage_name="l", case_name="c", stage=Stage.RUNNING,
        branch_number=1, year=2050,
    )

    save_state(str(state_path), state)

    assert not (tmp_path / "state.json.tmp").exists()
    assert state_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_enso_mcb_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enso_mcb_state'`

- [ ] **Step 3: Implement the state module**

`enso_mcb_state.py`:
```python
import dataclasses
import json
import os


class Stage:
    RUNNING = "RUNNING"
    MCB_ON = "MCB_ON"
    MCB_COOLDOWN = "MCB_COOLDOWN"
    FAILED = "FAILED"
    DONE = "DONE"


@dataclasses.dataclass
class CycleState:
    lineage_name: str
    case_name: str
    stage: str
    branch_number: int
    year: int


def load_state(path: str) -> CycleState:
    with open(path) as f:
        data = json.load(f)
    return CycleState(**data)


def save_state(path: str, state: CycleState) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(dataclasses.asdict(state), f, indent=2)
    os.replace(tmp_path, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_enso_mcb_state.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add enso_mcb_state.py tests/test_enso_mcb_state.py
git commit -m "Add lineage state module"
```

---

## Task 3: Niño3.4 warming check (`check_warming.py`)

**Files:**
- Create: `check_warming.py`
- Test: `tests/test_check_warming.py`

**Interfaces:**
- Produces: `compute_nino34_sst(history_file: str, sst_var="SST", area_var="TAREA", lat_var="TLAT", lon_var="TLONG") -> float`, `compute_anomaly(sst_value: float, climatology_value: float) -> float`, `is_warming(anomaly_c: float, threshold_c: float) -> bool`. CLI: `check_warming.py --history-file F --climatology-file F --year Y [--threshold T]`, prints `{"year": Y, "anomaly_c": ..., "warming": bool}` JSON to stdout on success (exit 0), or `{"error": "..."}` JSON to stderr on failure (exit 1). Used by Task 6's `run_check_warming`.

- [ ] **Step 1: Write the failing tests**

`tests/test_check_warming.py`:
```python
import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest
import xarray as xr

from check_warming import compute_anomaly, compute_nino34_sst, is_warming

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "check_warming.py")


def make_synthetic_history_file(path, sst_value_inside_box, sst_value_outside_box):
    lat = np.array([-10.0, -2.5, 2.5, 10.0])
    lon = np.array([100.0, 200.0, 300.0])
    lat2d, lon2d = np.meshgrid(lat, lon, indexing="ij")
    inside = (lat2d >= -5.0) & (lat2d <= 5.0) & (lon2d >= 190.0) & (lon2d <= 240.0)
    sst = np.where(inside, sst_value_inside_box, sst_value_outside_box)
    area = np.ones_like(sst)
    ds = xr.Dataset(
        {
            "SST": (("nlat", "nlon"), sst),
            "TAREA": (("nlat", "nlon"), area),
        },
        coords={
            "TLAT": (("nlat", "nlon"), lat2d),
            "TLONG": (("nlat", "nlon"), lon2d),
        },
    )
    ds.to_netcdf(path)


def test_compute_nino34_sst_averages_only_inside_the_box(tmp_path):
    history_file = tmp_path / "history.nc"
    make_synthetic_history_file(history_file, sst_value_inside_box=28.0, sst_value_outside_box=15.0)

    result = compute_nino34_sst(str(history_file))

    assert result == pytest.approx(28.0)


def test_compute_anomaly_is_difference_from_climatology():
    assert compute_anomaly(sst_value=29.0, climatology_value=27.5) == pytest.approx(1.5)


def test_is_warming_true_at_or_above_threshold():
    assert is_warming(anomaly_c=1.0, threshold_c=1.0) is True
    assert is_warming(anomaly_c=1.5, threshold_c=1.0) is True


def test_is_warming_false_below_threshold():
    assert is_warming(anomaly_c=0.9, threshold_c=1.0) is False


def test_cli_prints_warming_json(tmp_path):
    history_file = tmp_path / "history.nc"
    climatology_file = tmp_path / "clim.nc"
    make_synthetic_history_file(history_file, sst_value_inside_box=29.0, sst_value_outside_box=15.0)
    make_synthetic_history_file(climatology_file, sst_value_inside_box=27.5, sst_value_outside_box=15.0)

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--history-file", str(history_file),
         "--climatology-file", str(climatology_file),
         "--year", "2054", "--threshold", "1.0"],
        capture_output=True, text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["year"] == 2054
    assert payload["anomaly_c"] == pytest.approx(1.5, abs=0.01)
    assert payload["warming"] is True


def test_cli_fails_clearly_on_missing_history_file(tmp_path):
    climatology_file = tmp_path / "clim.nc"
    make_synthetic_history_file(climatology_file, sst_value_inside_box=27.5, sst_value_outside_box=15.0)

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--history-file", str(tmp_path / "does_not_exist.nc"),
         "--climatology-file", str(climatology_file),
         "--year", "2054"],
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert "error" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_check_warming.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'check_warming'`

- [ ] **Step 3: Implement `check_warming.py`**

```python
#!/usr/bin/env python3
"""Computes the Nino3.4 SST anomaly for a CESM ocean history file against
a fixed climatology reference file, and reports whether it crosses the
configured warming threshold."""
import argparse
import json
import sys

import xarray as xr

NINO34_LAT_BOUNDS = (-5.0, 5.0)
NINO34_LON_BOUNDS = (190.0, 240.0)  # 170 W - 120 W in 0-360 convention


def compute_nino34_sst(history_file: str, sst_var: str = "SST",
                        area_var: str = "TAREA", lat_var: str = "TLAT",
                        lon_var: str = "TLONG") -> float:
    ds = xr.open_dataset(history_file)
    lat = ds[lat_var]
    lon = ds[lon_var] % 360
    mask = (
        (lat >= NINO34_LAT_BOUNDS[0]) & (lat <= NINO34_LAT_BOUNDS[1]) &
        (lon >= NINO34_LON_BOUNDS[0]) & (lon <= NINO34_LON_BOUNDS[1])
    )
    sst = ds[sst_var]
    if "z_t" in sst.dims:
        sst = sst.isel(z_t=0)
    area = ds[area_var].where(mask)
    weighted_mean = (sst.where(mask) * area).sum() / area.sum()
    return float(weighted_mean.values)


def compute_anomaly(sst_value: float, climatology_value: float) -> float:
    return sst_value - climatology_value


def is_warming(anomaly_c: float, threshold_c: float) -> bool:
    return anomaly_c >= threshold_c


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-file", required=True)
    parser.add_argument("--climatology-file", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--threshold", type=float, default=1.0)
    args = parser.parse_args()

    try:
        sst_value = compute_nino34_sst(args.history_file)
        climatology_value = compute_nino34_sst(args.climatology_file)
        anomaly_c = compute_anomaly(sst_value, climatology_value)
        warming = is_warming(anomaly_c, args.threshold)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"year": args.year, "anomaly_c": round(anomaly_c, 3), "warming": warming}))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_check_warming.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add check_warming.py tests/test_check_warming.py
git commit -m "Add Nino3.4 warming check script"
```

---

## Task 4: Parameterized branch-case creation script (`create_branch_case.sh`)

**Files:**
- Create: `create_branch_case.sh`
- Test: `tests/test_create_branch_case.py`

**Interfaces:**
- Produces: a shell script invoked with env vars `ENS`, `REFCASE`, `BRANCH_NUMBER`, `STARTDATE`, `STOP_N`, `MCB_ON` (required) and `RESOLN`, `COMPSET`, `PROJECT`, `SRCDIR`, `TAGDIR`, `CASEROOT`, `SCRATCHROOT`, `NOTIFICATION_EMAIL` (optional, defaulting to the values from the existing `create_ENSO_controller_case.sh`; `NOTIFICATION_EMAIL` unset means no mail xmlchange calls are made). Set `DRY_RUN=1` to echo commands instead of running them. Prints `CASEDIR=<path>` as the last stdout line on success. Non-zero exit and a message on stderr naming the missing variable if a required var is unset. Used by Task 6's `create_branch_case()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_create_branch_case.py`:
```python
import os
import pathlib
import subprocess

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "create_branch_case.sh")

BASE_ENV = {
    "ENS": "1051",
    "REFCASE": "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
    "BRANCH_NUMBER": "9",
    "STARTDATE": "2054-06-01",
    "STOP_N": "3",
    "MCB_ON": "1",
}


def run_script(env_overrides):
    env = os.environ.copy()
    env["DRY_RUN"] = "1"
    env.update(env_overrides)
    return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)


def test_dry_run_reports_correct_branch_name_and_refcase():
    result = run_script(BASE_ENV)

    assert result.returncode == 0, result.stderr
    assert "branch.009" in result.stdout
    assert "RUN_REFCASE=b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008" in result.stdout


def test_dry_run_sets_stop_n_resubmit_zero_and_dout_s():
    result = run_script(BASE_ENV)

    assert "STOP_N=3" in result.stdout
    assert "RESUBMIT=0" in result.stdout
    assert "DOUT_S=TRUE" in result.stdout


def test_dry_run_sets_batch_mail_when_notification_email_provided():
    env = dict(BASE_ENV, NOTIFICATION_EMAIL="walkerl@example.edu")

    result = run_script(env)

    assert "BATCH_MAIL_TO=walkerl@example.edu" in result.stdout
    assert "BATCH_MAIL_TYPE=begin,end,fail" in result.stdout


def test_dry_run_skips_batch_mail_when_notification_email_unset():
    result = run_script(BASE_ENV)

    assert "BATCH_MAIL_TO" not in result.stdout
    assert "BATCH_MAIL_TYPE" not in result.stdout


def test_dry_run_appends_mcb_line_when_mcb_on():
    result = run_script(BASE_ENV)

    assert "MCB_seeding_amt = 1" in result.stdout


def test_dry_run_skips_mcb_line_when_mcb_off():
    env = dict(BASE_ENV, MCB_ON="0")

    result = run_script(env)

    assert "MCB_seeding_amt" not in result.stdout


def test_prints_casedir_as_last_line():
    result = run_script(BASE_ENV)

    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines[-1].startswith("CASEDIR=")
    assert "branch.009" in lines[-1]


def test_fails_clearly_when_required_var_missing():
    env = dict(BASE_ENV)
    del env["REFCASE"]

    result = run_script(env)

    assert result.returncode != 0
    assert "REFCASE" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_create_branch_case.py -v`
Expected: FAIL — `create_branch_case.sh` does not exist yet (`No such file or directory`), all tests error.

- [ ] **Step 3: Implement `create_branch_case.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Creates a new CESM branch case for the ENSO-MCB automated cycle.
#
# Required environment variables:
#   ENS           - ensemble member id, e.g. "1051"
#   REFCASE       - name of the case to branch from
#   BRANCH_NUMBER - integer branch number for the new case (zero-padded to 3 digits)
#   STARTDATE     - branch start date, YYYY-MM-DD
#   STOP_N        - number of months to run (STOP_OPTION is always nmonths)
#   MCB_ON        - "1" to enable MCB seeding, "0" to leave it off
#
# Optional environment variables (fall back to the current experiment's
# defaults if unset):
#   RESOLN, COMPSET, PROJECT, SRCDIR, TAGDIR, CASEROOT, SCRATCHROOT
#   NOTIFICATION_EMAIL - if set, configures CIME to email this address on
#                        job begin/end/fail (BATCH_MAIL_TO/BATCH_MAIL_TYPE);
#                        if unset, no mail xmlchange calls are made.
#
# On success, prints "CASEDIR=<path>" as the last line of stdout.
# Set DRY_RUN=1 to print the commands that would run instead of executing them.

: "${ENS:?ENS is required}"
: "${REFCASE:?REFCASE is required}"
: "${BRANCH_NUMBER:?BRANCH_NUMBER is required}"
: "${STARTDATE:?STARTDATE is required}"
: "${STOP_N:?STOP_N is required}"
: "${MCB_ON:?MCB_ON is required}"

RESOLN="${RESOLN:-f09_g17}"
COMPSET="${COMPSET:-BSSP370smbb}"
PROJECT="${PROJECT:-UCSD0083}"
SRCDIR="${SRCDIR:-/glade/work/walkerl/MCB_mods/bugfix_plus_namelist}"
TAGDIR="${TAGDIR:-/glade/work/walkerl/cesm_tags/cesm2.1.5+MCBnl}"
CASEROOT="${CASEROOT:-/glade/work/walkerl/cases}"
SCRATCHROOT="${SCRATCHROOT:-/glade/derecho/scratch/walkerl}"
NOTIFICATION_EMAIL="${NOTIFICATION_EMAIL:-}"

BRANCH_SUFFIX=$(printf "%03d" "$BRANCH_NUMBER")
RUNNAME="b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.${ENS}.branch.${BRANCH_SUFFIX}"

CASEDIR="$CASEROOT/$RUNNAME"
RUNDIR="$SCRATCHROOT/$RUNNAME/run"
ARCHIVEDIR="$SCRATCHROOT/archive/$RUNNAME/"
ICSDIR="$SCRATCHROOT/archive/$REFCASE/rest/${STARTDATE}-00000"

run() {
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "DRYRUN: $*"
  else
    "$@"
  fi
}

echo "##### setting up case $RUNNAME #####"

(
  cd "$TAGDIR/cime/scripts"
  run ./create_newcase --case "$CASEDIR" --res "$RESOLN" --compset "$COMPSET" --project "$PROJECT"
)

(
  cd "$CASEDIR"

  run ./xmlchange JOB_WALLCLOCK_TIME=1:15:00 --subgroup case.run
  run ./xmlchange RUN_TYPE=branch
  run ./xmlchange GET_REFCASE=FALSE
  run ./xmlchange RUN_REFCASE="$REFCASE"
  run ./xmlchange RUN_REFDATE="$STARTDATE"
  run ./xmlchange RUN_STARTDATE="$STARTDATE"
  run ./xmlchange DOUT_S=TRUE
  run ./xmlchange DOUT_S_ROOT="$ARCHIVEDIR"
  run ./xmlchange CIME_OUTPUT_ROOT="$SCRATCHROOT/"
  run ./xmlchange RUNDIR="$RUNDIR/"
  run ./xmlchange PROJECT="$PROJECT"
  run ./xmlchange STOP_N="$STOP_N"
  run ./xmlchange STOP_OPTION=nmonths
  run ./xmlchange RESUBMIT=0

  if [ -n "$NOTIFICATION_EMAIL" ]; then
    run ./xmlchange BATCH_MAIL_TO="$NOTIFICATION_EMAIL"
    run ./xmlchange BATCH_MAIL_TYPE=begin,end,fail
  fi

  run mkdir -p "$RUNDIR"
  run cp "$ICSDIR"/* "$RUNDIR"/.

  run ./case.setup --reset
  run ./preview_namelists

  run cp "$SRCDIR"/* SourceMods/src.cam/.

  if [ "$MCB_ON" = "1" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      echo "DRYRUN: append 'MCB_seeding_amt = 1' to user_nl_cam"
    else
      cat >> user_nl_cam << EOF
MCB_seeding_amt = 1
EOF
    fi
  fi
)

echo "##### script finished, ready to build #####"
echo "CASEDIR=$CASEDIR"
```

- [ ] **Step 4: Make the script executable and run tests to verify they pass**

Run:
```bash
chmod +x create_branch_case.sh
.venv/bin/pytest tests/test_create_branch_case.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add create_branch_case.sh tests/test_create_branch_case.py
git commit -m "Add parameterized branch-case creation script"
```

---

## Task 5: Orchestrator decision logic (`enso_mcb_decision.py`)

**Files:**
- Create: `enso_mcb_decision.py`
- Test: `tests/test_enso_mcb_decision.py`

**Interfaces:**
- Consumes: `CycleState`, `Stage` from `enso_mcb_state` (Task 2).
- Produces: `Transition` dataclass (`action: str, next_stage: str, ref_case: str, start_date: str, stop_n: int, mcb_on: bool, next_branch_number: int, next_year: int`), `decide_transition(state: CycleState, warming_result: Optional[dict], end_year: int) -> Transition`. `action` is one of `"branch_mcb_on"`, `"flip_mcb_off_resubmit"`, `"resubmit_running"`, `"stop"`. Used by Task 7's `run_cycle`.

- [ ] **Step 1: Write the failing tests**

`tests/test_enso_mcb_decision.py`:
```python
import pytest

from enso_mcb_decision import decide_transition
from enso_mcb_state import CycleState, Stage


def make_state(**overrides):
    defaults = dict(
        lineage_name="enso_mcb_1051",
        case_name="b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
        stage=Stage.RUNNING,
        branch_number=8,
        year=2054,
    )
    defaults.update(overrides)
    return CycleState(**defaults)


def test_running_with_warming_branches_to_mcb_on():
    state = make_state(stage=Stage.RUNNING, year=2054, branch_number=8)

    transition = decide_transition(state, {"warming": True, "anomaly_c": 1.5}, end_year=2100)

    assert transition.action == "branch_mcb_on"
    assert transition.next_stage == Stage.MCB_ON
    assert transition.ref_case == state.case_name
    assert transition.start_date == "2054-06-01"
    assert transition.stop_n == 3
    assert transition.mcb_on is True
    assert transition.next_branch_number == 9
    assert transition.next_year == 2054


def test_running_without_warming_resubmits_next_year():
    state = make_state(stage=Stage.RUNNING, year=2054, branch_number=8)

    transition = decide_transition(state, {"warming": False, "anomaly_c": 0.2}, end_year=2100)

    assert transition.action == "resubmit_running"
    assert transition.next_stage == Stage.RUNNING
    assert transition.start_date == "2055-01-01"
    assert transition.stop_n == 12
    assert transition.mcb_on is False
    assert transition.next_branch_number == 8
    assert transition.next_year == 2055


def test_running_requires_warming_result():
    state = make_state(stage=Stage.RUNNING)

    with pytest.raises(ValueError, match="warming_result is required"):
        decide_transition(state, None, end_year=2100)


def test_mcb_on_flips_off_and_runs_sept_through_dec():
    state = make_state(stage=Stage.MCB_ON, year=2054, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "flip_mcb_off_resubmit"
    assert transition.next_stage == Stage.MCB_COOLDOWN
    assert transition.start_date == "2054-09-01"
    assert transition.stop_n == 4
    assert transition.mcb_on is False
    assert transition.next_year == 2054


def test_mcb_cooldown_resubmits_next_year_running():
    state = make_state(stage=Stage.MCB_COOLDOWN, year=2054, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "resubmit_running"
    assert transition.next_stage == Stage.RUNNING
    assert transition.start_date == "2055-01-01"
    assert transition.next_year == 2055


def test_stops_when_next_year_exceeds_end_year_from_running():
    state = make_state(stage=Stage.RUNNING, year=2100, branch_number=8)

    transition = decide_transition(state, {"warming": False, "anomaly_c": 0.1}, end_year=2100)

    assert transition.action == "stop"
    assert transition.next_stage == Stage.DONE


def test_stops_when_next_year_exceeds_end_year_from_cooldown():
    state = make_state(stage=Stage.MCB_COOLDOWN, year=2100, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "stop"
    assert transition.next_stage == Stage.DONE


def test_cannot_transition_from_failed_stage():
    state = make_state(stage=Stage.FAILED)

    with pytest.raises(ValueError, match="Cannot decide a transition"):
        decide_transition(state, None, end_year=2100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_enso_mcb_decision.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enso_mcb_decision'`

- [ ] **Step 3: Implement `enso_mcb_decision.py`**

```python
import dataclasses
from typing import Optional

from enso_mcb_state import CycleState, Stage


@dataclasses.dataclass
class Transition:
    action: str
    next_stage: str
    ref_case: str
    start_date: str
    stop_n: int
    mcb_on: bool
    next_branch_number: int
    next_year: int


def decide_transition(state: CycleState, warming_result: Optional[dict], end_year: int) -> Transition:
    if state.stage == Stage.RUNNING:
        if warming_result is None:
            raise ValueError("warming_result is required when stage is RUNNING")
        if warming_result["warming"]:
            return Transition(
                action="branch_mcb_on",
                next_stage=Stage.MCB_ON,
                ref_case=state.case_name,
                start_date=f"{state.year}-06-01",
                stop_n=3,
                mcb_on=True,
                next_branch_number=state.branch_number + 1,
                next_year=state.year,
            )
        return _resubmit_next_year(state, end_year)

    if state.stage == Stage.MCB_ON:
        return Transition(
            action="flip_mcb_off_resubmit",
            next_stage=Stage.MCB_COOLDOWN,
            ref_case=state.case_name,
            start_date=f"{state.year}-09-01",
            stop_n=4,
            mcb_on=False,
            next_branch_number=state.branch_number,
            next_year=state.year,
        )

    if state.stage == Stage.MCB_COOLDOWN:
        return _resubmit_next_year(state, end_year)

    raise ValueError(f"Cannot decide a transition from stage {state.stage!r}")


def _resubmit_next_year(state: CycleState, end_year: int) -> Transition:
    next_year = state.year + 1
    if next_year > end_year:
        return Transition(
            action="stop",
            next_stage=Stage.DONE,
            ref_case=state.case_name,
            start_date="",
            stop_n=0,
            mcb_on=False,
            next_branch_number=state.branch_number,
            next_year=state.year,
        )
    return Transition(
        action="resubmit_running",
        next_stage=Stage.RUNNING,
        ref_case=state.case_name,
        start_date=f"{next_year}-01-01",
        stop_n=12,
        mcb_on=False,
        next_branch_number=state.branch_number,
        next_year=next_year,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_enso_mcb_decision.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add enso_mcb_decision.py tests/test_enso_mcb_decision.py
git commit -m "Add orchestrator state-transition decision logic"
```

---

## Task 6: PBS job interaction layer (`enso_mcb_jobs.py`)

**Files:**
- Create: `enso_mcb_jobs.py`
- Test: `tests/test_enso_mcb_jobs.py`

**Interfaces:**
- Produces: `parse_last_job_id(submit_output: str) -> str`, `submit_case(case_dir: str) -> str`, `set_stop_n(case_dir: str, stop_n: int) -> None`, `resubmit_case(case_dir: str, stop_n: int) -> str`, `flip_mcb_off(case_dir: str) -> None`, `set_batch_mail(case_dir: str, email: str) -> None`, `run_check_warming(python_exe: str, script_path: str, history_file: str, climatology_file: str, year: int, threshold: float) -> dict`, `create_branch_case(script_path: str, ens: str, refcase: str, branch_number: int, startdate: str, stop_n: int, mcb_on: bool, caseroot: str, email: str) -> str`, `submit_orchestrator_self(wrapper_script: str, depend_job_id: str, state_file: str, email: str) -> str`. All are thin `subprocess` wrappers; every one is monkeypatched (not called for real) in Task 7's tests. Used by Task 7. `set_batch_mail` exists separately from `create_branch_case` because the bootstrap case is created outside this automation (Task 7's `bootstrap()` calls it directly on the pre-existing initial case), while branch cases get mail configured inline as part of `create_branch_case.sh`.

- [ ] **Step 1: Write the failing tests**

`tests/test_enso_mcb_jobs.py`:
```python
import json
import subprocess

import pytest

import enso_mcb_jobs as jobs


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_parse_last_job_id_extracts_numeric_id():
    assert jobs.parse_last_job_id("12345.desched1\n") == "12345"


def test_parse_last_job_id_raises_on_empty_output():
    with pytest.raises(ValueError, match="no output"):
        jobs.parse_last_job_id("")


def test_parse_last_job_id_raises_on_unparseable_line():
    with pytest.raises(ValueError, match="could not parse"):
        jobs.parse_last_job_id("submission failed\n")


def test_submit_case_returns_parsed_job_id(monkeypatch):
    def fake_run(cmd, cwd, capture_output, text, check):
        assert cmd == ["./case.submit"]
        assert cwd == "/fake/case"
        return FakeCompletedProcess(stdout="Submitted job: 55555.derecho\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert jobs.submit_case("/fake/case") == "55555"


def test_resubmit_case_sets_stop_n_then_submits(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, check=None, capture_output=False, text=False):
        calls.append(cmd)
        if cmd[0] == "./case.submit":
            return FakeCompletedProcess(stdout="99999.derecho\n")
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    job_id = jobs.resubmit_case("/fake/case", 12)

    assert calls[0] == ["./xmlchange", "STOP_N=12"]
    assert calls[1] == ["./case.submit"]
    assert job_id == "99999"


def test_flip_mcb_off_replaces_namelist_line(tmp_path, monkeypatch):
    nl_path = tmp_path / "user_nl_cam"
    nl_path.write_text("some_other_var = 1\nMCB_seeding_amt = 1\n")

    calls = []

    def fake_run(cmd, cwd=None, check=None):
        calls.append((cmd, cwd))
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.flip_mcb_off(str(tmp_path))

    content = nl_path.read_text()
    assert "MCB_seeding_amt = 0" in content
    assert content.count("MCB_seeding_amt") == 1
    assert "some_other_var = 1" in content
    assert calls == [(["./preview_namelists"], str(tmp_path))]


def test_set_batch_mail_runs_expected_xmlchange_calls(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, check=None):
        calls.append((cmd, cwd))
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.set_batch_mail("/fake/case", "walkerl@example.edu")

    assert calls == [
        (["./xmlchange", "BATCH_MAIL_TO=walkerl@example.edu"], "/fake/case"),
        (["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], "/fake/case"),
    ]


def test_run_check_warming_parses_json_stdout(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(
            stdout=json.dumps({"year": 2054, "anomaly_c": 1.3, "warming": True}),
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = jobs.run_check_warming("python3", "check_warming.py", "hist.nc", "clim.nc", 2054, 1.0)

    assert result == {"year": 2054, "anomaly_c": 1.3, "warming": True}


def test_run_check_warming_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(stderr="boom", returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        jobs.run_check_warming("python3", "check_warming.py", "hist.nc", "clim.nc", 2054, 1.0)


def test_create_branch_case_returns_parsed_casedir(monkeypatch):
    def fake_run(cmd, env, capture_output, text, check):
        assert env["REFCASE"] == "refcase-1"
        assert env["MCB_ON"] == "1"
        assert env["NOTIFICATION_EMAIL"] == "walkerl@example.edu"
        return FakeCompletedProcess(
            stdout="##### done #####\nCASEDIR=/glade/work/walkerl/cases/branch.009\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    casedir = jobs.create_branch_case(
        "create_branch_case.sh", "1051", "refcase-1", 9, "2054-06-01", 3, True,
        "/glade/work/walkerl/cases", "walkerl@example.edu",
    )

    assert casedir == "/glade/work/walkerl/cases/branch.009"


def test_create_branch_case_raises_when_no_casedir_reported(monkeypatch):
    def fake_run(cmd, env, capture_output, text, check):
        return FakeCompletedProcess(stdout="no casedir here\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="did not report a CASEDIR"):
        jobs.create_branch_case(
            "create_branch_case.sh", "1051", "refcase-1", 9, "2054-06-01", 3, True,
            "/glade/work/walkerl/cases", "walkerl@example.edu",
        )


def test_submit_orchestrator_self_builds_qsub_dependency_command(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, check):
        captured["cmd"] = cmd
        return FakeCompletedProcess(stdout="66666.derecho\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    job_id = jobs.submit_orchestrator_self(
        "orchestrator_wrapper.sh", "55555", "/glade/work/state.json", "walkerl@example.edu",
    )

    assert captured["cmd"] == [
        "qsub", "-W", "depend=afterok:55555", "-m", "ae", "-M", "walkerl@example.edu",
        "-v", "STATE_FILE=/glade/work/state.json", "orchestrator_wrapper.sh",
    ]
    assert job_id == "66666.derecho"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_enso_mcb_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enso_mcb_jobs'`

- [ ] **Step 3: Implement `enso_mcb_jobs.py`**

```python
import json
import os
import re
import subprocess

JOB_ID_RE = re.compile(r"(\d+)(?:\.\S+)?\s*$")
CASEDIR_RE = re.compile(r"^CASEDIR=(.+)$", re.MULTILINE)


def parse_last_job_id(submit_output: str) -> str:
    lines = [line for line in submit_output.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("case.submit produced no output to parse a job ID from")
    match = JOB_ID_RE.search(lines[-1])
    if not match:
        raise ValueError(f"could not parse job ID from case.submit output: {lines[-1]!r}")
    return match.group(1)


def submit_case(case_dir: str) -> str:
    result = subprocess.run(
        ["./case.submit"], cwd=case_dir, capture_output=True, text=True, check=True,
    )
    return parse_last_job_id(result.stdout)


def set_stop_n(case_dir: str, stop_n: int) -> None:
    subprocess.run(["./xmlchange", f"STOP_N={stop_n}"], cwd=case_dir, check=True)


def resubmit_case(case_dir: str, stop_n: int) -> str:
    set_stop_n(case_dir, stop_n)
    return submit_case(case_dir)


def flip_mcb_off(case_dir: str) -> None:
    nl_path = os.path.join(case_dir, "user_nl_cam")
    with open(nl_path) as f:
        lines = f.readlines()
    lines = [line for line in lines if not line.strip().startswith("MCB_seeding_amt")]
    lines.append("MCB_seeding_amt = 0\n")
    with open(nl_path, "w") as f:
        f.writelines(lines)
    subprocess.run(["./preview_namelists"], cwd=case_dir, check=True)


def set_batch_mail(case_dir: str, email: str) -> None:
    subprocess.run(["./xmlchange", f"BATCH_MAIL_TO={email}"], cwd=case_dir, check=True)
    subprocess.run(["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], cwd=case_dir, check=True)


def run_check_warming(python_exe: str, script_path: str, history_file: str,
                       climatology_file: str, year: int, threshold: float) -> dict:
    result = subprocess.run(
        [python_exe, script_path,
         "--history-file", history_file,
         "--climatology-file", climatology_file,
         "--year", str(year),
         "--threshold", str(threshold)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"check_warming.py failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def create_branch_case(script_path: str, ens: str, refcase: str, branch_number: int,
                        startdate: str, stop_n: int, mcb_on: bool, caseroot: str,
                        email: str) -> str:
    env = os.environ.copy()
    env.update({
        "ENS": ens,
        "REFCASE": refcase,
        "BRANCH_NUMBER": str(branch_number),
        "STARTDATE": startdate,
        "STOP_N": str(stop_n),
        "MCB_ON": "1" if mcb_on else "0",
        "CASEROOT": caseroot,
        "NOTIFICATION_EMAIL": email,
    })
    result = subprocess.run(
        ["bash", script_path], env=env, capture_output=True, text=True, check=True,
    )
    match = CASEDIR_RE.search(result.stdout)
    if not match:
        raise ValueError(f"create_branch_case.sh did not report a CASEDIR: {result.stdout!r}")
    return match.group(1)


def submit_orchestrator_self(wrapper_script: str, depend_job_id: str, state_file: str,
                              email: str) -> str:
    result = subprocess.run(
        ["qsub", "-W", f"depend=afterok:{depend_job_id}", "-m", "ae", "-M", email,
         "-v", f"STATE_FILE={state_file}", wrapper_script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_enso_mcb_jobs.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add enso_mcb_jobs.py tests/test_enso_mcb_jobs.py
git commit -m "Add PBS/CIME job interaction layer"
```

---

## Task 7: Orchestrator entrypoint and PBS wrapper

**Files:**
- Create: `enso_mcb_orchestrator.py`
- Create: `orchestrator_wrapper.sh`
- Test: `tests/test_enso_mcb_orchestrator.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `CycleState`/`Stage`/`load_state`/`save_state` (Task 2), `decide_transition` (Task 5), all of `enso_mcb_jobs` (Task 6).
- Produces: `run_cycle(state_file: str, config_file: str) -> None`, `bootstrap(state_file: str, config_file: str, lineage_name: str, initial_refcase: str, start_year: int) -> None`, `main() -> None` (CLI entrypoint, `python enso_mcb_orchestrator.py --state-file F --config-file F [--bootstrap --lineage-name N --initial-refcase C --start-year Y]`). This is the final integration point — no later task depends on it.

- [ ] **Step 1: Write the failing tests**

`tests/test_enso_mcb_orchestrator.py`:
```python
import textwrap

import pytest

import enso_mcb_jobs as jobs
import enso_mcb_orchestrator as orch
from enso_mcb_state import CycleState, Stage, load_state, save_state


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(f"""\
        ens: "1051"
        resoln: "f09_g17"
        compset: "BSSP370smbb"
        project: "UCSD0083"
        srcdir: "/tmp/srcdir"
        tagdir: "/tmp/tagdir"
        caseroot: "{tmp_path}/cases"
        scratchroot: "{tmp_path}/scratch"
        climatology_file: "/tmp/clim.nc"
        warming_threshold_c: 1.0
        end_year: 2100
        notification_email: "walkerl@example.edu"
        python_exe: "python3"
        check_warming_script: "check_warming.py"
        create_branch_case_script: "create_branch_case.sh"
        orchestrator_wrapper_script: "orchestrator_wrapper.sh"
    """))
    return str(path)


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(str(path), CycleState(
        lineage_name="enso_mcb_1051", case_name="branch.008",
        stage=Stage.RUNNING, branch_number=8, year=2054,
    ))
    return str(path)


def test_run_cycle_branches_to_mcb_on_when_warming_detected(monkeypatch, config_file, state_file):
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 1.4, "warming": True})
    monkeypatch.setattr(jobs, "create_branch_case", lambda *a, **k: "/cases/branch.009")
    monkeypatch.setattr(jobs, "submit_case", lambda casedir: "11111")
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email: submitted_self.update(
                             wrapper=wrapper, job_id=job_id, state_file=sf, email=email))

    orch.run_cycle(state_file, config_file)

    new_state = load_state(state_file)
    assert new_state.stage == Stage.MCB_ON
    assert new_state.case_name == "branch.009"
    assert new_state.branch_number == 9
    assert new_state.year == 2054
    assert submitted_self["job_id"] == "11111"


def test_run_cycle_resubmits_next_year_when_no_warming(monkeypatch, config_file, state_file):
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 0.2, "warming": False})
    monkeypatch.setattr(jobs, "resubmit_case", lambda casedir, stop_n: "22222")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(state_file, config_file)

    new_state = load_state(state_file)
    assert new_state.stage == Stage.RUNNING
    assert new_state.case_name == "branch.008"
    assert new_state.year == 2055


def test_run_cycle_flips_mcb_off_after_mcb_on_segment(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.009", stage=Stage.MCB_ON,
        branch_number=9, year=2054,
    ))
    monkeypatch.setattr(jobs, "flip_mcb_off", lambda casedir: None)
    monkeypatch.setattr(jobs, "resubmit_case", lambda casedir, stop_n: "33333")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(str(state_path), config_file)

    new_state = load_state(str(state_path))
    assert new_state.stage == Stage.MCB_COOLDOWN
    assert new_state.year == 2054


def test_run_cycle_stops_and_marks_done_past_end_year(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.008", stage=Stage.RUNNING,
        branch_number=8, year=2100,
    ))
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2100, "anomaly_c": 0.1, "warming": False})
    submitted_self = []
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: submitted_self.append(True))

    orch.run_cycle(str(state_path), config_file)

    new_state = load_state(str(state_path))
    assert new_state.stage == Stage.DONE
    assert submitted_self == []


def test_run_cycle_does_nothing_for_terminal_states(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.008", stage=Stage.FAILED,
        branch_number=8, year=2060,
    ))
    calls = []
    monkeypatch.setattr(jobs, "run_check_warming", lambda *a, **k: calls.append("check") or {})

    orch.run_cycle(str(state_path), config_file)

    assert calls == []


def test_bootstrap_creates_initial_state_and_submits_first_segment(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "bootstrap_state.json"
    calls = []
    monkeypatch.setattr(jobs, "set_batch_mail",
                         lambda casedir, email: calls.append(("set_batch_mail", casedir, email)))
    monkeypatch.setattr(jobs, "resubmit_case",
                         lambda casedir, stop_n: calls.append(("resubmit_case", casedir, stop_n)) or "44444")
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email: submitted_self.update(job_id=job_id))

    orch.bootstrap(str(state_path), config_file, "enso_mcb_1051", "initial-case", 2050)

    new_state = load_state(str(state_path))
    assert new_state.lineage_name == "enso_mcb_1051"
    assert new_state.case_name == "initial-case"
    assert new_state.stage == Stage.RUNNING
    assert new_state.branch_number == 0
    assert new_state.year == 2050
    assert calls[0][0] == "set_batch_mail"
    assert calls[0][2] == "walkerl@example.edu"
    assert calls[1] == ("resubmit_case", calls[1][1], 12)
    assert submitted_self["job_id"] == "44444"


def test_main_marks_failed_and_does_not_resubmit_on_error(monkeypatch, config_file, state_file):
    def boom(*a, **k):
        raise RuntimeError("case.submit blew up")

    monkeypatch.setattr(jobs, "run_check_warming", boom)
    submitted_self = []
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: submitted_self.append(True))
    monkeypatch.setattr(
        "sys.argv",
        ["enso_mcb_orchestrator.py", "--state-file", state_file, "--config-file", config_file],
    )

    with pytest.raises(SystemExit) as exc_info:
        orch.main()

    assert exc_info.value.code == 1
    new_state = load_state(state_file)
    assert new_state.stage == Stage.FAILED
    assert submitted_self == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_enso_mcb_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'enso_mcb_orchestrator'`

- [ ] **Step 3: Implement `enso_mcb_orchestrator.py`**

```python
#!/usr/bin/env python3
import argparse
import logging
import os
import sys

import enso_mcb_jobs as jobs
from enso_mcb_config import load_config
from enso_mcb_decision import decide_transition
from enso_mcb_state import CycleState, Stage, load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enso_mcb_orchestrator")


def history_file_path(config: dict, case_name: str, year: int) -> str:
    return os.path.join(
        config["scratchroot"], "archive", case_name, "ocn", "hist",
        f"{case_name}.pop.h.{year:04d}-06.nc",
    )


def run_cycle(state_file: str, config_file: str) -> None:
    config = load_config(config_file)
    state = load_state(state_file)

    if state.stage in (Stage.FAILED, Stage.DONE):
        log.info("Lineage %s is in terminal stage %s; nothing to do.", state.lineage_name, state.stage)
        return

    warming_result = None
    if state.stage == Stage.RUNNING:
        warming_result = jobs.run_check_warming(
            config["python_exe"], config["check_warming_script"],
            history_file_path(config, state.case_name, state.year),
            config["climatology_file"], state.year, config["warming_threshold_c"],
        )
        log.info("Warming check for %s year %s: %s", state.case_name, state.year, warming_result)

    transition = decide_transition(state, warming_result, config["end_year"])

    if transition.action == "stop":
        state.stage = Stage.DONE
        save_state(state_file, state)
        log.info("Reached end year %s; lineage %s complete.", config["end_year"], state.lineage_name)
        return

    if transition.action == "branch_mcb_on":
        casedir = jobs.create_branch_case(
            config["create_branch_case_script"], config["ens"], transition.ref_case,
            transition.next_branch_number, transition.start_date, transition.stop_n,
            transition.mcb_on, config["caseroot"], config["notification_email"],
        )
        job_id = jobs.submit_case(casedir)
        state.case_name = os.path.basename(casedir)
        state.branch_number = transition.next_branch_number
    elif transition.action == "flip_mcb_off_resubmit":
        casedir = os.path.join(config["caseroot"], state.case_name)
        jobs.flip_mcb_off(casedir)
        job_id = jobs.resubmit_case(casedir, transition.stop_n)
    elif transition.action == "resubmit_running":
        casedir = os.path.join(config["caseroot"], state.case_name)
        job_id = jobs.resubmit_case(casedir, transition.stop_n)
    else:
        raise ValueError(f"Unknown transition action: {transition.action}")

    state.stage = transition.next_stage
    state.year = transition.next_year
    save_state(state_file, state)

    jobs.submit_orchestrator_self(
        config["orchestrator_wrapper_script"], job_id, state_file, config["notification_email"],
    )


def bootstrap(state_file: str, config_file: str, lineage_name: str,
              initial_refcase: str, start_year: int) -> None:
    config = load_config(config_file)
    state = CycleState(
        lineage_name=lineage_name, case_name=initial_refcase,
        stage=Stage.RUNNING, branch_number=0, year=start_year,
    )
    save_state(state_file, state)

    casedir = os.path.join(config["caseroot"], initial_refcase)
    jobs.set_batch_mail(casedir, config["notification_email"])
    job_id = jobs.resubmit_case(casedir, 12)
    jobs.submit_orchestrator_self(
        config["orchestrator_wrapper_script"], job_id, state_file, config["notification_email"],
    )


def mark_failed(state_file: str) -> None:
    try:
        state = load_state(state_file)
        state.stage = Stage.FAILED
        save_state(state_file, state)
    except Exception:
        log.exception("Could not record FAILED state for %s", state_file)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--config-file", default="enso_mcb_config.yaml")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--lineage-name")
    parser.add_argument("--initial-refcase")
    parser.add_argument("--start-year", type=int)
    args = parser.parse_args()

    try:
        if args.bootstrap:
            if not (args.lineage_name and args.initial_refcase and args.start_year):
                parser.error("--bootstrap requires --lineage-name, --initial-refcase, and --start-year")
            bootstrap(args.state_file, args.config_file, args.lineage_name,
                      args.initial_refcase, args.start_year)
        else:
            run_cycle(args.state_file, args.config_file)
    except Exception:
        log.exception("Cycle failed for state file %s; halting chain.", args.state_file)
        mark_failed(args.state_file)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

`orchestrator_wrapper.sh` (the PBS job script `submit_orchestrator_self` submits):
```bash
#!/usr/bin/env bash
#PBS -N enso_mcb_orchestrator
#PBS -A UCSD0083
#PBS -l select=1:ncpus=1
#PBS -l walltime=00:10:00
#PBS -q main
#PBS -j oe

set -euo pipefail

cd "$PBS_O_WORKDIR"

: "${STATE_FILE:?STATE_FILE must be set (pass via qsub -v STATE_FILE=...)}"

python3 enso_mcb_orchestrator.py --state-file "$STATE_FILE" --config-file enso_mcb_config.yaml
```

- [ ] **Step 4: Make the wrapper executable, check its syntax, and run tests to verify they pass**

Run:
```bash
chmod +x orchestrator_wrapper.sh
bash -n orchestrator_wrapper.sh
.venv/bin/pytest tests/test_enso_mcb_orchestrator.py -v
```
Expected: `bash -n` prints nothing (valid syntax); pytest PASS (7 tests)

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all tests across every task)

- [ ] **Step 6: Commit**

```bash
git add enso_mcb_orchestrator.py orchestrator_wrapper.sh tests/test_enso_mcb_orchestrator.py
git commit -m "Add orchestrator entrypoint and PBS wrapper script"
```

---

## Task 8: Operator runbook

**Files:**
- Create: `docs/RUNBOOK.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Write the runbook**

`docs/RUNBOOK.md`:
```markdown
# ENSO-MCB Automation Runbook

This is the operator's guide to bootstrapping, monitoring, and recovering
the automated ENSO-MCB PBS job chain. See
`docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md` for the
full design.

## Pre-flight checklist (do this once, before the first bootstrap)

1. Fill in `enso_mcb_config.yaml`:
   - `climatology_file`: path to the fixed Nino3.4 June climatology
     reference file. This is currently a placeholder — the pipeline will
     fail loudly (not silently) if it's left pointing at a nonexistent
     file, but confirm it's set correctly before bootstrapping.
   - `notification_email`: where PBS should send failure/abort emails.
   - Confirm `caseroot`, `scratchroot`, `srcdir`, `tagdir` match your
     actual Derecho paths.

2. Verify short-term archiving is on for your initial reference case
   (the case you'll pass as `--initial-refcase`):
   ```bash
   cd /glade/work/walkerl/cases/<initial-refcase>
   ./xmlquery DOUT_S
   ```
   This must print `TRUE`. The orchestrator's self-resubmission depends
   on the archive (`st_archive`) job, not just the run job — if
   archiving is off, the dependency chain has nothing to depend on.

3. Verify how `case.submit` reports job IDs on this system, and how POP
   writes monthly-mean history file paths/names, against a real case:
   ```bash
   cd /glade/work/walkerl/cases/<initial-refcase>
   ./case.submit
   # note the job ID format printed for the run job vs. the st_archive job
   ls /glade/derecho/scratch/walkerl/archive/<initial-refcase>/ocn/hist/
   ```
   `enso_mcb_jobs.parse_last_job_id` and
   `enso_mcb_orchestrator.history_file_path` assume a specific format
   (see the spec's "Open item" notes). If what you see differs, adjust
   `JOB_ID_RE` in `enso_mcb_jobs.py` or the path template in
   `history_file_path` before bootstrapping.

## Bootstrapping a new lineage

```bash
cd /glade/work/walkerl/enso_mcb_automation   # wherever this repo is checked out on Derecho
python3 enso_mcb_orchestrator.py \
    --state-file /glade/work/walkerl/enso_mcb_automation/state/enso_mcb_1051.json \
    --config-file enso_mcb_config.yaml \
    --bootstrap \
    --lineage-name enso_mcb_1051 \
    --initial-refcase <your-existing-case-name> \
    --start-year <year-of-the-first-check>
```

This resubmits the initial case for a 12-month segment and chains the
first orchestrator job dependent on its archive job. From here, the
chain runs itself.

## Monitoring

- `qstat -u $USER` shows the currently queued/running job in the chain
  (either a CESM run/archive job pair, or the orchestrator job).
- `cat /glade/work/walkerl/enso_mcb_automation/state/<lineage>.json` shows
  the current stage, case, branch number, and year — this is the single
  source of truth for where the lineage is.
- Each orchestrator invocation logs to its PBS job's stdout/stderr file
  (`enso_mcb_orchestrator.o<jobid>`), including the warming check result
  whenever one was performed.

## Recovering from a failure

A `"stage": "FAILED"` in the state file means the chain has stopped
resubmitting itself — nothing is silently retrying.

1. Read the failing orchestrator job's log
   (`enso_mcb_orchestrator.o<jobid>`) for the exception traceback.
2. Fix the underlying issue (missing file, bad path, CIME error, etc.).
3. Manually edit the state file's `"stage"` back to the state it should
   resume from (e.g. `"RUNNING"`, `"MCB_ON"`, `"MCB_COOLDOWN"`) if the
   failure happened before that state was actually reached on disk.
4. Resume by resubmitting the orchestrator directly:
   ```bash
   python3 enso_mcb_orchestrator.py --state-file <path> --config-file enso_mcb_config.yaml
   ```

## Stopping a lineage early

Cancel the currently queued/running job for that lineage
(`qdel <jobid>`) — since each stage only chains the *next* job after
finishing, cancelling one job stops the chain without needing to touch
the state file. Resume later by resubmitting the orchestrator manually
as in step 4 above.
```

- [ ] **Step 2: Verify every path/command referenced in the runbook matches what the code actually does**

Run:
```bash
grep -n "climatology_file\|notification_email\|caseroot\|scratchroot" enso_mcb_config.yaml
grep -n "DOUT_S" create_branch_case.sh
grep -n "def history_file_path\|def parse_last_job_id" enso_mcb_orchestrator.py enso_mcb_jobs.py
grep -n "bootstrap\|state-file\|config-file" enso_mcb_orchestrator.py
```
Expected: every symbol/flag named in the runbook (`climatology_file`, `notification_email`, `caseroot`, `scratchroot`, `DOUT_S`, `history_file_path`, `parse_last_job_id`, `--bootstrap`, `--state-file`, `--config-file`) appears in the grep output — confirming the runbook doesn't reference anything that doesn't exist in the code.

- [ ] **Step 3: Commit**

```bash
git add docs/RUNBOOK.md
git commit -m "Add operator runbook for the ENSO-MCB automation"
```

---

## Post-implementation note

This plan implements everything the spec covers except the two items the
spec explicitly flagged as unverifiable without HPC access: the exact
`case.submit` job-ID stdout format and the exact POP history file
path/naming convention. Task 8's pre-flight checklist tells the operator
how to verify both against a real Derecho case and where to adjust the
code (`JOB_ID_RE` in `enso_mcb_jobs.py`, `history_file_path` in
`enso_mcb_orchestrator.py`) if reality differs from what's implemented.
