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
   `xarray`/`netCDF4`/`PyYAML` installed — `orchestrator_wrapper.sh` runs
   `module load conda && conda activate ENSO_Control` before invoking the
   orchestrator:
   ```bash
   module load conda
   conda activate ENSO_Control
   python3 -c "import xarray, netCDF4, yaml"
   ```

   If the environment doesn't exist yet, create it (e.g. `conda create -n
   ENSO_Control -c conda-forge python xarray netcdf4 pyyaml`) before the
   first bootstrap.

6. **Time one real `case.build` and size the orchestrator's PBS job to
   match.** On the cycle where warming is detected, the orchestrator job
   runs `create_branch_case.sh` synchronously, and that script's
   `./case.build` step runs *inside the orchestrator's own PBS job*. The
   `#PBS -l select=1:ncpus=8` and `#PBS -l walltime=02:00:00` lines at the
   top of `orchestrator_wrapper.sh` (lines 4-5) are **a guess** — no real
   build has been timed on Derecho. If the build overruns the walltime,
   PBS kills the orchestrator mid-build and the chain stops (this looks
   like Signature B below, with a partially-created case to clean up).

   Do one timed trial invocation before the first production bootstrap
   (this builds a real case — pick a throwaway branch number). `STARTDATE`
   must be a date for which `<refcase>` already has an archived restart set
   — i.e. `$SCRATCHROOT/archive/<refcase>/rest/<STARTDATE>-00000/` must
   exist — otherwise the restart-copy step fails before `case.build` ever
   runs and you get no timing data:
   ```bash
   cd /glade/u/home/jabrzenski/github/ENSO_CESM
   time env ENS=1051 REFCASE=<an-existing-case> BRANCH_NUMBER=999 \
       STARTDATE=<YYYY-MM-DD-with-an-existing-restart> STOP_N=3 MCB_ON=1 \
       bash create_branch_case.sh
   ```

   Note the wallclock time and how many cores the build actually used
   (Derecho builds are parallel), then edit the two `#PBS -l` lines in
   `orchestrator_wrapper.sh` to the measured time plus generous headroom
   (at least 1.5x) and a matching `ncpus`. Build parallelism is controlled
   by CIME's `GMAKE_J` setting (`./xmlquery GMAKE_J` in the case directory),
   not directly by the PBS `ncpus` request — if the build only used a
   handful of cores while `ncpus` requests more, check `GMAKE_J` before
   assuming more `ncpus` will speed anything up. Delete the throwaway
   `branch.999` case directory and its run directory afterwards.

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

```bash
cd /glade/u/home/jabrzenski/github/ENSO_CESM   # wherever this repo is checked out on Derecho
module load conda && conda activate ENSO_Control
python3 enso_mcb_orchestrator.py \
    --state-file /glade/u/home/jabrzenski/github/ENSO_CESM/state/enso_mcb_1051.json \
    --config-file enso_mcb_config.yaml \
    --bootstrap \
    --lineage-name enso_mcb_1051 \
    --initial-refcase <your-existing-case-name> \
    --start-year <year-of-the-first-check> \
    --branch-number <branch number of that existing case>
```

`--branch-number` must be the branch number of `--initial-refcase` (e.g.
`9` for `...branch.009`); the first MCB branch case this lineage creates
will be that number + 1. It defaults to `0`, which would collide with the
existing `branch.008`/`branch.009` cases of this lineage — pass it
explicitly.

Bootstrapping forces the XML settings the pipeline requires onto the
adopted case (`RESUBMIT=0`, `STOP_OPTION=nmonths`, `DOUT_S=TRUE`,
`REST_OPTION=nmonths`, `REST_N=1`), resubmits the case for a 12-month
segment, and chains the first orchestrator job dependent on its archive
job. From here, the chain runs itself.

`RESUBMIT=0` matters: the manual `create_ENSO_controller_case.sh` sets
`RESUBMIT=3`, and if that were left in place CIME's own auto-resubmit
would advance the case concurrently with the orchestrator's explicit
resubmissions — two chains driving one case.

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
Typical causes: missing climatology/history file, an `xmlchange` that
failed, `case.submit`/`qsub` rejecting the job, a `case.build` failure.

1. Read `"failure_reason"` in the state file, and the failing
   orchestrator job's log (`enso_mcb_orchestrator.o<jobid>`) for the full
   traceback. Failures of subprocesses (CIME, qsub, the branch-case
   script) include the command's captured stdout/stderr in the message.
2. Fix the underlying issue (missing file, bad path, CIME error, etc.).
3. Set `"stage"` back to the value in `"failed_from_stage"` — that is
   the stage to resume from — and clear `"failed_from_stage"` and
   `"failure_reason"`. Double-check `"case_name"`/`"year"` against what
   actually happened on disk: the orchestrator only advances them after
   the corresponding submission succeeded.
4. Resume by running the orchestrator directly:
   ```bash
   cd /glade/u/home/jabrzenski/github/ENSO_CESM
   module load conda && conda activate ENSO_Control
   python3 enso_mcb_orchestrator.py --state-file <path> --config-file enso_mcb_config.yaml
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
   (`cd $CASEDIR && ./case.submit`) and chain the orchestrator to its
   archive job, or simply re-run the orchestrator directly as in
   Signature A step 4 once the segment has completed.

### A partially-created branch case

`create_branch_case.sh` is not resumable. If a branch cycle failed
partway through case creation (or during `case.build`), a partial case
directory is left behind, and re-running the orchestrator will fail
immediately with `ERROR: case directory already exists: <path>`. Inspect
that directory; if it is an incomplete leftover, `rm -rf` it (and the
matching run directory under `$SCRATCHROOT/<casename>/run`) before
retrying.

## Stopping a lineage early

Cancel the currently queued/running job for that lineage
(`qdel <jobid>`) — since each stage only chains the *next* job after
finishing, cancelling one job stops the chain without needing to touch
the state file. Resume later by resubmitting the orchestrator manually
as in Signature A step 4 above.

Note that a deliberately cancelled lineage looks exactly like Signature B
(non-terminal stage, empty queue), so leave yourself a note if you intend
to resume it later.
