# ENSO-MCB Automated Cycle: Design Spec

## Problem

`create_ENSO_controller_case.sh` automates creating a single CESM branch case
with Marine Cloud Brightening (MCB) turned on. Today, running the full
experiment cycle is manual: a person watches the queue, downloads June ocean
output off the HPC system, runs a Python script to check for central Pacific
(Niño3.4) warming, and — if warming is detected — hand-edits and re-runs the
`.sh` script to create the next branch case with MCB turned on.

This spec covers automating the full cycle so it runs unattended on the HPC
system (Derecho), as a chain of PBS jobs, for the life of the experiment
(through year 2100).

## Experiment cycle (confirmed with user)

A single lineage of CESM cases advances through three states:

- **`RUNNING`** — a case advancing one full calendar year at a time
  (`STOP_N=12`, `STOP_OPTION=nmonths`, `RESUBMIT=0`). The orchestrator
  explicitly resubmits each year itself (rather than relying on CIME's
  `RESUBMIT`), so it regains control after every segment to check for
  warming.
- **`MCB_ON`** — a *new branch case*, created off that year's June 1 restart,
  running Jun–Aug (`STOP_N=3`) with MCB seeding on
  (`MCB_seeding_amt=1`, MCB source mods applied).
- **`MCB_COOLDOWN`** — the *same* case as `MCB_ON`, with the namelist flipped
  (`MCB_seeding_amt=0`) and resubmitted Sep–Dec (`STOP_N=4`) to finish out
  the branch year and land back on Jan 1.

Transitions, evaluated once per completed segment (after the run + archive
job finishes):

```
RUNNING (year Y finishes in December)
  → compute Niño3.4 SST anomaly using year Y's June ocean history output
  → anomaly ≥ threshold (default 1.0°C):
        create branch case, RUN_REFDATE=Y-06-01, MCB on, STOP_N=3
        → state MCB_ON
  → anomaly < threshold:
        resubmit same case, STOP_N=12, for year Y+1
        → state RUNNING

MCB_ON (Jun–Aug finishes)
  → flip MCB_seeding_amt to 0 in same case, preview_namelists,
    resubmit same case, STOP_N=4 (Sep–Dec)
    → state MCB_COOLDOWN

MCB_COOLDOWN (Sep–Dec finishes)
  → resubmit same case, STOP_N=12, for year Y+1
    → state RUNNING
```

The chain stops resubmitting once a completed segment's end year reaches the
configured end year (2100).

Branch/case naming is fully mechanical for this automated lineage (confirmed
with user — no per-cycle human judgment call): branch number always
increments by 1 from the previous case in the lineage; `refcase` is always
the case that just finished; `startdate` is always computed from the current
state (`Y-06-01` for the MCB branch, `Y-01-01` implicitly continuing within
the same case otherwise).

## Components

All files live in this repo and are run from the HPC system (Derecho),
alongside the existing script.

### `enso_mcb_orchestrator.py`

The state machine described above. Runs as a PBS job. On each invocation:

1. Reads the lineage's state file.
2. Performs exactly one transition (see above) — including, for the
   `RUNNING` transition, invoking `check_warming.py` and parsing its result.
3. Submits the next CESM segment via `case.submit` (or, for `MCB_ON`,
   `create_branch_case.sh` then `case.submit`), capturing the job ID of the
   last job in that submission's internal chain (the `st_archive` job — see
   "PBS dependency mechanics" below).
4. Writes the updated state back to the state file.
5. Resubmits itself as a new PBS job, `qsub -W depend=afterok:<st_archive_jobid>`.
6. Exits. It does not poll or wait.

On any failure in steps 1–4 (non-zero exit from a CESM job, a failed
`check_warming.py` run, a failed case-creation), the orchestrator writes a
`FAILED` state and a clear log message, and does **not** perform step 5 —
the chain halts and requires manual intervention.

The orchestrator also supports a `--bootstrap` mode to seed the very first
cycle: given an initial reference case (the CESM2-LE ensemble member to
branch the whole experiment from), it creates the initial state file and
kicks off the first `RUNNING` segment.

### `check_warming.py`

- **Input:** the archive directory for the just-finished year
  (`$DOUT_S_ROOT/ocn/hist/`, POP monthly-mean files, June's file), plus a
  fixed climatology reference file path (from config).
- **Computation:** area-weighted mean SST over the Niño3.4 box
  (5°S–5°N, 170°W–120°W) using the ocean grid's cell-area variable, minus
  the reference climatology's June Niño3.4 value.
- **Output:** JSON to stdout —
  `{"year": 2054, "anomaly_c": 1.34, "warming": true}`.
  Non-zero exit code only on genuine failure (missing/corrupt file) — "no
  warming" is a normal result communicated via the JSON, not a failure.
- **Threshold:** read from config (default 1.0°C), not hardcoded.

> **Open item:** the exact Niño3.4 climatology reference file path is TBD —
> the user will supply it before this runs for real. It's a config value,
> not something baked into code.

### `create_branch_case.sh`

Refactor of the existing `create_ENSO_controller_case.sh`: identical logic,
but `ens`, `refcase`, the branch number (via `runname`), `startdate`, and
`stopn` become parameters (env vars or CLI args) instead of hand-edited
constants, so the orchestrator can call it programmatically. The existing
script remains available for manual one-off use (or becomes a thin wrapper
around the parameterized version with the current hardcoded values as
defaults).

### `enso_mcb_config.yaml`

Fixed knobs that don't change per cycle:

- `ens`, `resoln`, `compset`, `project`
- `srcdir` / `tagdir` (MCB source mods location)
- Niño3.4 climatology reference file path (placeholder until supplied)
- Warming threshold in °C (default 1.0)
- End year (2100)
- Notification email address

### State file

One JSON file per lineage, stored outside any individual case directory
(since each branch creates a new case dir) — e.g.
`/glade/work/walkerl/enso_mcb_automation/state/<lineage_name>.json`. Tracks:
current case name, state (`RUNNING` / `MCB_ON` / `MCB_COOLDOWN` / `FAILED`),
current branch number, current year.

## PBS dependency mechanics

`case.submit` (CIME) already chains a run job followed by a short-term
archive (`st_archive`) job when `DOUT_S=TRUE` (already set in the existing
script). The orchestrator must depend on the **archive job**, not just the
run job, since `check_warming.py` reads from the archived output directory.

1. Orchestrator calls `case.submit`, captures stdout, parses out the job ID
   of the `st_archive` job (the last job in the chain).
2. Orchestrator submits itself: `qsub -W depend=afterok:<st_archive_jobid> orchestrator_wrapper.sh`.
   The wrapper takes no stage-specific arguments — the resubmitted
   orchestrator always re-reads current truth from the state file.
3. Current invocation exits without polling.

> **Open item:** the exact stdout format of `case.submit` for extracting job
> IDs, and the exact POP history file naming/path, depend on the CIME
> version and case configuration on Derecho. These need to be verified
> against a real case during implementation — this spec describes intent,
> not a guessed exact format.

## Error handling & notifications

- Any stage failure halts the chain (no resubmission of the orchestrator).
  State file records `FAILED` plus a reason; logs are written clearly enough
  to diagnose without re-running anything.
- PBS jobs (both CESM run jobs and the orchestrator job) are submitted with
  `-m ae -M <email>` so failures/aborts trigger an email, per user
  preference — no silent unattended failures.
- No automatic retries. A failed cycle requires a human to fix the issue and
  manually resume from the recorded state.

## Testing approach

Because this drives real HPC job submission, the goal is to make the
*decision logic* testable without touching PBS or `/glade`:

- `check_warming.py`'s anomaly computation and threshold logic: unit-tested
  against small synthetic NetCDF fixtures, not real model output.
- The orchestrator's state-transition logic (given a state + a warming
  result, what's the next state and what case-creation arguments get
  produced): unit-tested with `case.submit`/`qsub` calls mocked out —
  verifying decisions, not actual submission.
- Actual submission/dependency behavior can only be verified by running one
  real cycle on Derecho once implemented — this is a manual verification
  step, not something claimed as covered by automated tests.

## Out of scope

- Rewriting or improving the underlying CESM/MCB science configuration
  (source mods, compset, resolution) — these are inherited as-is from the
  existing script.
- A UI or dashboard for cycle status — the state file and PBS email
  notifications are the only visibility mechanism for now.
- Supporting multiple concurrent lineages from one orchestrator invocation
  — one state file, one lineage, one call chain at a time (multiple
  lineages could each get their own state file / independent chains, but
  that's not being built now).
