# ENSO-MCB Automation Runbook

This is the operator's guide to bootstrapping, monitoring, and recovering
the automated ENSO-MCB PBS job chain. See
`docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md` for the
full design.

## Pre-flight checklist (do this once, before the first bootstrap)

1. Fill in `enso_mcb_config.yaml`:
   - `climatology_sst_dir`: confirmed to be
     `/glade/campaign/collections/gdex/data/d651056/CESM2-LE/ocn/proc/tseries/month_1/SST`
     — the CESM2-LE archive of monthly SST tseries files (one file per
     ensemble member per ~10-year chunk, both historical and SSP370
     scenario phases live in this same directory). `build_climatology.py`
     builds each cycle's rolling 30-year June climatology from here, for
     the ensemble member matching this lineage's `ens` and
     `climatology_member_ordinal` (`LE2-{ens}.{climatology_member_ordinal}`).
     A real file's `ncdump -h` confirms `SST`/`TAREA`/`TLAT`/`TLONG` are
     present in exactly the shape `check_warming.py` expects, so no
     variable-name overrides are needed for this data source — **but a
     header dump cannot confirm the time-stamp convention** (see the
     verification step below, which is the one part of this that
     genuinely needed checking against real data, not just the header).
   - `climatology_forcing_variant`: CESM2-LE ships two forcing ensembles
     under the same member numbers ("cmip6", the full ensemble, and
     "smbb", the biomass-burning variant this experiment actually uses —
     matching `compset: BSSP370smbb` above and the refcase in
     `create_ENSO_controller_case.sh`). **Before first use, `ls` the
     `climatology_sst_dir` for each of this deployment's `ens` values and
     confirm an `LE2-{ens}.{ordinal}` member matching the `smbb` variant
     actually exists** — CESM2-LE's macro-initialization scheme pairs
     specific member ordinals with specific initialization years, so the
     ordinal is *not* guaranteed to be `001` for every `ens` and needs a
     real directory listing to confirm, not an assumption from the
     member-numbering pattern alone. Set the confirmed ordinal in
     `climatology_member_ordinal` — every lineage needs this set from its
     own real directory listing, since `build_climatology.py` only ever
     tries `LE2-{ens}.{climatology_member_ordinal}`. Confirmed against a
     real listing on 2026-09-04: `ens` 1011→ordinal `001`, 1031→`002`,
     1051→`003`, 1071→`004`, 1091→`005`, 1111→`006`, 1131→`007`,
     1151→`008`, 1171→`009` — but confirm again for any `ens` not in this
     list rather than extrapolating the pattern.
   - **Verify the time-stamp convention** on one real SST tseries file
     before trusting any climatology this produces:
     ```bash
     ncdump -v time,time_bound b.e21.BSSP370smbb.f09_g17.LE2-1011.001.pop.h.SST.<some-range>.nc | tail -30
     ```
     POP conventionally stamps a monthly mean's `time` value at the *end*
     of its averaging interval (a June mean's raw `time` can fall on
     July 1) rather than within the averaged month — `build_climatology.py`
     accounts for this by using `time_bound`'s interval start (which lands
     exactly on the 1st of the true averaged month) whenever `time_bound`
     is present, falling back to the raw `time` value only if it is
     absent. Confirm the file actually has `time:bounds = "time_bound"`
     and that `time_bound`'s first column for a known June entry reads
     `<year>-06-01` — if the real convention differs from this, the
     climatology will be silently off by one month, which biases every
     year's anomaly low against the warming threshold without any error
     or symptom. Confirmed against a real `LE2-1011.001` file's
     204501-205412 chunk on 2026-09-04: `time_bound`'s June-2045 entry
     starts exactly on 2045-06-01, matching this convention.
   - `climatology_cache_dir`: where per-year built climatology files are
     cached. Needs to exist or be creatable by the orchestrator's PBS job
     user; it's created automatically on first use if missing. Cached
     files are keyed on `(forcing_variant, member, year)`, so fixing a
     mistake in either of the two verification steps above requires
     deleting any already-built files in this directory before the next
     cycle — nothing detects staleness automatically.
   - Confirm `caseroot`, `scratchroot`, `srcdir`, `tagdir` match your
     actual Derecho paths.

2. Verify short-term archiving is on for your initial reference case
   (the case you'll pass as `--initial-refcase`):

   ```bash
   cd /glade/work/jabrzenski/cases/ENSO_walker/<initial-refcase>
   ./xmlquery DOUT_S

   DOUT_S: TRUE
   ```

   This must print `TRUE`. The orchestrator's self-resubmission depends
   on the archive (`st_archive`) job, not just the run job — if
   archiving is off, the dependency chain has nothing to depend on.

3. Verify how `case.submit` reports job IDs on this system, and how POP
   writes monthly-mean history file paths/names, against a real case:

   ```bash
   cd /glade/work/jabrzenski/cases/ENSO_walker/<initial-refcase>
   ./case.submit
   # note the job ID format printed for the run job vs. the st_archive job
   ls /glade/derecho/scratch/jabrzenski/archive/<initial-refcase>/ocn/hist/
   ```

   `enso_mcb_jobs.parse_last_job_id` and
   `enso_mcb_orchestrator.history_file_path` assume a specific format
   (see the spec's "Open item" notes). If what you see differs, adjust
   `JOB_ID_RE` in `enso_mcb_jobs.py` or the path template in
   `history_file_path` before bootstrapping.

   `parse_last_job_id` prefers a line naming `st_archive` (CIME's archive
   job name) and only falls back to the last line of output, so also
   confirm that the archive job's ID actually appears on a line that names
   `st_archive`. It deliberately ignores lines that merely contain the word
   "archive" as part of a path (e.g. the `DOUT_S_ROOT` line), because a job
   ID cannot be parsed reliably out of a case-name path.

   **Job-ID parsing confirmed on 2026-09-08** against a real `case.submit`
   on the `LE2-1091.005` hybrid case: output included both
   `Submitted job id is 7353996.desched1` (case.run) and
   `Submitted job case.st_archive with id 7353997.desched1`.
   `parse_last_job_id` correctly returned `7353997` (the archive job), even
   with an earlier line containing `depend=afterok:7353996.desched1` — the
   trailing-anchor in `JOB_ID_RE` correctly ignores mid-line digit
   sequences. No code change needed.

   **POP history file naming confirmed on 2026-09-10** against the same
   case's first archived segment: the archive directory landed exactly at
   `history_file_path`'s expected
   `$SCRATCHROOT/archive/<case_name>/ocn/hist/`, and the monthly file was
   named `b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1091.branch.000.pop.h.2030-01.nc`
   — an exact match for `<case_name>.pop.h.<YYYY>-<MM>.nc`. (POP also
   writes a separate daily-mean stream, `*.pop.h.nday1.<YYYY>-<MM>-<DD>.nc`,
   which the pipeline never references — no collision risk, since
   `history_file_path` builds an exact filename rather than a glob.) No
   code change needed.

4. Confirm the PBS queue for the orchestrator job itself
   (`orchestrator_queue` in `enso_mcb_config.yaml`, default `main`).
   The orchestrator job is short (about a minute, except on branch cycles
   where it blocks on `case.build` — see item 6) but runs once per
   cycle for decades. Check NCAR/Derecho's **current** queue and billing
   policies for short, frequent, small jobs (the wrapper currently requests
   8 cores so the branch-cycle build has cores to use) — this repo cannot
   verify them — and set `orchestrator_queue` accordingly. It is passed
   as `qsub -q`, overriding the `#PBS -q` line in
   `orchestrator_wrapper.sh`, so no script edit is needed. The same
   applies to `project`, passed as `qsub -A`.

5. Confirm the `ENSO_Control` conda environment exists on Derecho and has
   `xarray`/`netCDF4`/`PyYAML` installed. `orchestrator_wrapper.sh` and
   `python_exe` in `enso_mcb_config.yaml` both run this environment's
   interpreter **by absolute path, without activating it**:
   ```bash
   /glade/work/jabrzenski/conda-envs/ENSO_Control/bin/python3 -c "import xarray, netCDF4, yaml"
   ```

   Never `conda activate ENSO_Control` in the shell you bootstrap or resume
   from. Activation puts the environment's Python 3.12 first on `PATH`,
   every CIME script the orchestrator spawns picks it up, and CESM 2.1.5's
   CIME fails under 3.12 with `ModuleNotFoundError: No module named 'imp'`.
   Also confirm the shell's default Python (what CIME will use) can run CIME:
   ```bash
   which python python3            # must NOT point into conda-envs/ENSO_Control
   python3 -c "import imp"         # must succeed (only a DeprecationWarning)
   ```

   If the environment doesn't exist yet, create it (e.g. `conda create -n
   ENSO_Control -c conda-forge python xarray netcdf4 pyyaml`) before the
   first bootstrap.

6. **Time one real `case.build` and size the orchestrator's PBS job to
   match.** On the cycle where warming is detected, the orchestrator job
   runs `create_branch_case.sh` synchronously, and that script's
   `./case.build` step runs *inside the orchestrator's own PBS job*. If the
   build overruns the walltime, PBS kills the orchestrator mid-build and
   the chain stops (this looks like Signature B below, with a
   partially-created case to clean up).

   **Confirmed on 2026-09-08**, from the initial `LE2-1091.005` hybrid
   case's real `./case.build` (same compset/resolution `create_branch_case.sh`
   builds for every MCB branch, so representative): **500s wallclock**,
   `GMAKE_J=16` (`./xmlquery GMAKE_J` in the built case — this is CIME's
   actual build parallelism, independent of whatever `ncpus` a PBS job
   happens to request; requesting fewer than `GMAKE_J` undersubscribes the
   build, requesting more doesn't speed it up). `orchestrator_wrapper.sh`
   is now set to `ncpus=16` (matching `GMAKE_J`) and `walltime=00:20:00`
   (~2.4x the measured time).

   If this deployment's compset/resolution ever changes, redo this trial:
   pick a throwaway branch number, and `STARTDATE` must be a date for which
   `<refcase>` already has an archived restart set — i.e.
   `$SCRATCHROOT/archive/<refcase>/rest/<STARTDATE>-00000/` must exist —
   otherwise the restart-copy step fails before `case.build` ever runs:

   ```bash
   cd /glade/u/home/jabrzenski/github/ENSO_CESM
   time env ENS=1091 REFCASE=<an-existing-case> BRANCH_NUMBER=999 \
       STARTDATE=<YYYY-MM-DD-with-an-existing-restart> STOP_N=3 MCB_ON=1 \
       bash create_branch_case.sh
   ```

   Then re-edit the two `#PBS -l` lines in `orchestrator_wrapper.sh` to the
   newly measured time plus generous headroom (at least 1.5x) and a
   matching `ncpus`, and delete the throwaway `branch.999` case/run
   directories afterwards.

7. **Know where to look if a live build or submit fails on the
   environment.** `create_branch_case.sh` is not run with the full ambient
   environment: `enso_mcb_jobs.create_branch_case()` builds the subprocess
   env from an explicit allowlist, `PASSTHROUGH_ENV_VARS` (top of
   `enso_mcb_jobs.py`), plus the pipeline's own configured variables. This
   deliberately stops a stray `PROJECT`/`CASEROOT`/`SCRATCHROOT` in the PBS
   job environment from overriding the configured values — but it also
   means anything CIME needs that is not on the list is simply absent.

   Currently allowed through: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`,
   `LANG`, `LC_ALL`, `TMPDIR`, `LD_LIBRARY_PATH`, `PYTHONPATH`, and the
   Lmod module-system variables (`MODULEPATH`, `MODULESHOME`, `LMOD_CMD`,
   `LMOD_PKG`, `LMOD_SYSTEM_NAME`). If a live `case.build` or `case.submit`
   fails with an environment-shaped error — `module: command not found`, a
   missing compiler/MPI wrapper, an unresolved shared library, a missing
   NetCDF/ESMF path — **check `PASSTHROUGH_ENV_VARS` first** and add the
   missing variable there. Compare against a working interactive shell
   (`env | sort`) to find what the build actually depends on.

## Bootstrapping a new lineage

Bootstrapping hands an existing case over to the orchestrator. Before you
run it:

1. **The case must already be built and have finished one run.** Create it
   with `create_ENSO_controller_case.sh`, then in the case directory run
   `./case.build` and `./case.submit`. Bootstrap does neither. It sets
   `CONTINUE_RUN=TRUE`, which continues from the case's own last restart,
   and a case that has never run has none.
2. **Nothing for the case may be queued or running.**
   `create_ENSO_controller_case.sh` sets `RESUBMIT=3`, so CIME queues
   follow-on segments by itself; wait until `qstat -u $USER` shows none of
   them. Bootstrapping while one is in flight puts two jobs on one run
   directory.
3. **Find where the case stopped**, to choose `--start-year` (below). The
   last date listed is where bootstrap's segment will start:

   ```bash
   ls /glade/derecho/scratch/jabrzenski/archive/<initial-refcase>/rest/
   ```

Bootstrap refuses to run if the state file already exists, since a second
bootstrap would start a second segment and a second orchestrator chain on
the same case. The only time to delete a state file and bootstrap again is
after a failed bootstrap (see [If bootstrap fails](#if-bootstrap-fails)).
The `state/` directory is created automatically.

```bash
cd /glade/u/home/jabrzenski/github/ENSO_CESM   # the repo checkout: queued jobs run relative paths from here
# No `conda activate` — see pre-flight item 5.
/glade/work/jabrzenski/conda-envs/ENSO_Control/bin/python3 enso_mcb_orchestrator.py \
    --state-file /glade/u/home/jabrzenski/github/ENSO_CESM/state/enso_mcb_1091.json \
    --config-file enso_mcb_config.yaml \
    --bootstrap \
    --lineage-name enso_mcb_1091 \
    --initial-refcase b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1091.branch.000 \
    --start-year <see below> \
    --branch-number 0
```

These values are for the current deployment (`ens: "1091"` in
`enso_mcb_config.yaml`); for another lineage, change the `1091`s.

- `--initial-refcase` is the full name of the case being adopted: the
  directory under `caseroot` that `create_ENSO_controller_case.sh` created
  (its `runname`). It is **not** the CESM2-LE member that case was started
  from (`b.e21.BSSP370smbb.f09_g17.LE2-1091.005`), which is only a source
  of restart files, not a case directory bootstrap can change.
- `--branch-number` is the branch number of `--initial-refcase`: `0` for
  `...branch.000`, `9` for `...branch.009`. The first MCB branch this
  lineage creates is that number + 1. It defaults to `0`, which is right
  for a case made by `create_ENSO_controller_case.sh` as currently
  configured. When adopting a case with any other suffix, pass it
  explicitly, or the first MCB branch would be `branch.001` and could
  collide with an existing case.
- `--start-year` is the year of the first June inside the 12-month segment
  bootstrap submits, which starts where the case stopped (step 3). For
  example, `create_ENSO_controller_case.sh` as configured starts on
  2030-01-01 and runs four 2-month segments (`STOP_N=2`, `RESUBMIT=3`),
  stopping at 2030-09-01. Bootstrap's segment then runs to 2031-09-01, so
  use `--start-year 2031`. A year too early (2030 here) makes the first
  check read the June file left over from the initial run, and every later
  check a year behind the simulation.

Bootstrap writes the state file first, then forces the XML settings the
pipeline requires onto the adopted case (`RESUBMIT=0`,
`STOP_OPTION=nmonths`, `DOUT_S=TRUE`, `REST_OPTION=nmonths`, `REST_N=1`),
sets `STOP_N=12` and `CONTINUE_RUN=TRUE`, runs `case.submit`, and queues
the first orchestrator job dependent on that segment's archive job. It
returns in a minute or two; from here, the chain runs itself as PBS jobs.

`RESUBMIT=0` matters: the manual `create_ENSO_controller_case.sh` sets
`RESUBMIT=3`, and if that were left in place CIME's own auto-resubmit
would advance the case concurrently with the orchestrator's explicit
resubmissions — two chains driving one case.

To confirm it worked: the state file shows `"stage": "RUNNING"` with your
start year and no `failure_reason`, and `qstat -u $USER` shows the run
job, the `st_archive` job, and a held (`H`) `enso_mcb_orchestrator` job.

### If bootstrap fails

A failed bootstrap prints its traceback in your terminal and leaves the
state file at `"stage": "FAILED"` with `"failed_from_stage": "RUNNING"`.
**Don't follow Signature A below.** Setting the stage back to `RUNNING`
and running the orchestrator would start a normal cycle, which runs the
warming check for a year whose history file doesn't exist yet. What to do
depends on how far bootstrap got, which `failure_reason` shows:

- **`./xmlchange` failed:** nothing was submitted. Fix the cause, delete
  the state file, and run the same `--bootstrap` command again (bootstrap
  refuses to run while the state file exists).
- **`./case.submit` failed:** check `qstat -u $USER` and `qdel` anything it
  did queue for the case. Then fix the cause, delete the state file, and
  run `--bootstrap` again.
- **`qsub` failed** (the reason names `orchestrator_wrapper.sh`): the
  12-month segment **is already queued**. Keep the state file and don't
  run `--bootstrap` again, which would submit the segment a second time.
  Fix the `qsub` problem, edit the
  state file to `"stage": "RUNNING"` with `"failed_from_stage"` and
  `"failure_reason"` set to `null`, and
  [queue the orchestrator by hand](#queuing-the-orchestrator-by-hand)
  against the segment's `st_archive` job.

## Monitoring

- `qstat -u $USER` shows the currently queued/running job in the chain
  (either a CESM run/archive job pair, or the orchestrator job).
- `cat /glade/u/home/jabrzenski/github/ENSO_CESM/state/<lineage>.json` shows
  the current stage, case, branch number, and year — it records where the
  lineage got to, but see the warning below: it is **not** updated when a
  CESM job fails, so "state file plus `qstat`" together are the real
  picture.
- Each orchestrator invocation logs to its PBS job's stdout/stderr file
  (`enso_mcb_orchestrator.o<jobid>`), including the warming check result
  whenever one was performed.

## Recovering from a failure

There are two distinct failure signatures, and only one of them writes
`FAILED` to the state file. **Neither retries automatically.**

### Signature A — the orchestrator's own Python failed

Symptoms: the state file says `"stage": "FAILED"`, plus
`"failed_from_stage"` (the stage it was in when it failed) and
`"failure_reason"` (the exception). The orchestrator caught the
exception, recorded it, and exited non-zero without chaining a next job.
Typical causes: missing SST or history data, an `xmlchange` that failed,
`case.submit`/`qsub` rejecting the job, a `case.build` failure.

If the failure came from a `--bootstrap` run (the traceback was in your
terminal), use [If bootstrap fails](#if-bootstrap-fails) instead. These
steps are for a lineage that was already running.

1. Read `"failure_reason"` in the state file, and the failing
   orchestrator job's log (`enso_mcb_orchestrator.o<jobid>`) for the full
   traceback. Failures of subprocesses (CIME, qsub, the branch-case
   script) include the command's captured stdout/stderr in the message.
2. Fix the underlying issue (missing file, bad path, CIME error, etc.).
3. **Check `qstat -u $USER` before resuming.** The orchestrator submits
   the CESM segment and saves the advanced state *before* its last step,
   queuing the next orchestrator job. So if `failure_reason` starts with
   `RuntimeError: Command qsub`, that segment is already queued or
   running, and the state file (including `"failed_from_stage"`) already
   describes it. Running the orchestrator now would act on a segment that
   hasn't finished.
4. Set `"stage"` back to the value in `"failed_from_stage"` — that is
   the stage to resume from — and set `"failed_from_stage"` and
   `"failure_reason"` to `null`. Double-check `"case_name"`/`"year"`
   against what actually happened on disk: the orchestrator only advances
   them after the corresponding submission succeeded.
5. Resume:
   - If a CESM segment for this lineage is still queued or running (the
     `qsub` case in step 3),
     [queue the orchestrator by hand](#queuing-the-orchestrator-by-hand)
     against its `st_archive` job.
   - Otherwise, run the orchestrator directly:

     ```bash
     cd /glade/u/home/jabrzenski/github/ENSO_CESM
     # No `conda activate` — see pre-flight item 5.
     /glade/work/jabrzenski/conda-envs/ENSO_Control/bin/python3 enso_mcb_orchestrator.py --state-file <path> --config-file enso_mcb_config.yaml
     ```

### Signature B — a CESM run or archive job failed

Symptoms: **the state file still shows a normal, non-terminal stage**
(`RUNNING`/`MCB_ON`/`MCB_COOLDOWN`) and never changes; `qstat -u $USER`
shows nothing for this lineage; you received a PBS abort email for the
CESM job.

This is the case the state file cannot report. The orchestrator submits
the CESM segment and exits immediately — it never observes that job's
exit status. When the segment fails, PBS's `depend=afterok` dependency
means the *next* orchestrator job is never released: PBS holds it and
eventually deletes it. So nothing marks the state `FAILED`; the lineage
simply stops, frozen at its last stage, forever.

Recognizing it: if the state file has not changed for longer than a
segment should take, run `qstat -u $USER`. **An empty queue with a
non-terminal stage in the state file means the chain is dead.**
(`qstat -s` on the held orchestrator job, if it still exists, shows the
unsatisfied dependency.)

1. Find the failed CESM job's logs in the case directory
   (`$CASEDIR/CaseStatus`, and the `cesm.log.*`/`atm.log.*` files in the
   run directory) and fix the cause.
2. Delete any leftover held orchestrator job (`qdel <jobid>`) so it does
   not fire unexpectedly.
3. The state file's stage is still correct for *what was submitted* —
   the failed segment is the one belonging to the recorded stage — so
   after fixing the case, resubmit that segment by hand
   (`cd $CASEDIR && ./case.submit`) and
   [queue the orchestrator by hand](#queuing-the-orchestrator-by-hand)
   against its archive job, or simply re-run the orchestrator directly as
   in Signature A step 5 once the segment has completed.

### Queuing the orchestrator by hand

When a CESM segment is queued or running but no orchestrator job is
waiting for it, queue one the same way the orchestrator does. Submit from
the repo checkout: the job runs relative paths from the directory it was
submitted from.

```bash
cd /glade/u/home/jabrzenski/github/ENSO_CESM
qstat -u $USER                     # note the st_archive job's ID
qsub -W depend=afterok:<st_archive-job-id> -A UCSD0083 -q main \
     -v STATE_FILE=/glade/u/home/jabrzenski/github/ENSO_CESM/state/<lineage>.json \
     orchestrator_wrapper.sh
```

`-A` and `-q` are `project` and `orchestrator_queue` from
`enso_mcb_config.yaml`. If the segment has already finished, there is
nothing to wait for: run the orchestrator directly as in Signature A
step 5 instead.

### A partially-created branch case

`create_branch_case.sh` is not resumable. If a branch cycle failed
partway through case creation (or during `case.build`), a partial case
directory is left behind, and re-running the orchestrator will fail
immediately with `ERROR: case directory already exists: <path>`. Inspect
that directory; if it is an incomplete leftover, `rm -rf` it (and the
matching run directory under `$SCRATCHROOT/<casename>/run`) before
retrying.

## Stopping a lineage early

The clean way to stop is to cancel only the held `enso_mcb_orchestrator`
job (`qstat -u $USER`, then `qdel <jobid>`) and let the CESM segment that
is already running, and its `st_archive` job, finish. The state file then
matches a completed segment, so resuming later is just running the
orchestrator directly as in Signature A step 5.

If you also cancel the CESM run or `st_archive` job, that segment is left
unfinished, and it has to be completed before the orchestrator runs
again. Running the orchestrator straight away would treat it as finished
(an `MCB_ON` case, for example, would have seeding turned off partway
through June–August). Resume as in Signature B step 3 instead.

Either way, a deliberately stopped lineage looks exactly like Signature B
(non-terminal stage, empty queue), so leave yourself a note if you intend
to resume it later.
