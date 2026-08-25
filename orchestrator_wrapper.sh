#!/usr/bin/env bash
#PBS -N enso_mcb_orchestrator
#PBS -A UCSD0083
#PBS -l select=1:ncpus=1
#PBS -l walltime=01:00:00
#PBS -q main
#PBS -j oe

# Walltime is an hour even though a typical orchestrator invocation takes about
# a minute: on the cycle where warming is detected, this job runs
# create_branch_case.sh synchronously, and that script builds the new CESM case
# (./case.build), which takes 20-30 minutes for a real CESM2 build. A shorter
# walltime would kill the orchestrator mid-build and break the chain.
#
# The -A (project) and -q (queue) values above are defaults; the orchestrator
# passes `qsub -A <project> -q <orchestrator_queue>` from enso_mcb_config.yaml
# when chaining the next job, which overrides these lines.

set -euo pipefail

cd "$PBS_O_WORKDIR"

: "${STATE_FILE:?STATE_FILE must be set (pass via qsub -v STATE_FILE=...)}"

# The pipeline needs xarray/netCDF4/PyYAML, which live in the repo's venv and
# are not available to a bare system python3. The venv is resolved relative to
# PBS_O_WORKDIR (the repo checkout we just cd'd into), not to $0 — PBS runs a
# spooled copy of this script, so $0's directory is not the repo.
VENV_PYTHON="$PWD/.venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "ERROR: no virtualenv interpreter at $VENV_PYTHON" >&2
  echo "       Create it with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

"$VENV_PYTHON" enso_mcb_orchestrator.py --state-file "$STATE_FILE" --config-file enso_mcb_config.yaml
