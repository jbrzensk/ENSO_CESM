#!/usr/bin/env bash
#PBS -N enso_mcb_orchestrator
#PBS -A UCSD0083
#PBS -l select=1:ncpus=8
#PBS -l walltime=02:00:00
#PBS -q main
#PBS -j oe

# !! THE ncpus/walltime VALUES ABOVE ARE A STARTING GUESS AND MUST BE
# !! CONFIRMED AGAINST A REAL TIMED BUILD ON DERECHO BEFORE PRODUCTION USE.
# !! See the pre-flight checklist in docs/RUNBOOK.md.
#
# A typical orchestrator invocation takes about a minute and needs one core.
# But on the cycle where warming is detected, this job runs
# create_branch_case.sh synchronously, and that script builds the new CESM case
# (./case.build) inside this job. A parallel CESM2 build wants several cores
# and can take well over an hour depending on machine load and compset, so a
# single core and a one-hour walltime would risk killing the orchestrator
# mid-build and breaking the chain. Nobody has timed a real build on this
# system yet, hence: measure it, then set these to the measured time plus
# generous headroom.
#
# The -A (project) and -q (queue) values above are defaults; the orchestrator
# passes `qsub -A <project> -q <orchestrator_queue>` from enso_mcb_config.yaml
# when chaining the next job, which overrides these lines.

set -euo pipefail

cd "$PBS_O_WORKDIR"

: "${STATE_FILE:?STATE_FILE must be set (pass via qsub -v STATE_FILE=...)}"

# The pipeline needs xarray/netCDF4/PyYAML, which live in the "ENSO_Control"
# conda environment, not the bare system python3. Load the conda module and
# activate it before invoking the orchestrator; `python3` on PATH then
# resolves to this environment's interpreter.
module load conda
conda activate ENSO_Control

python3 enso_mcb_orchestrator.py --state-file "$STATE_FILE" --config-file enso_mcb_config.yaml
