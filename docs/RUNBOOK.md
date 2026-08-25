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
