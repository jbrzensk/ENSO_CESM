#!/usr/bin/env bash
#PBS -N enso_mcb_orchestrator
#PBS -A UCSD0083
#PBS -l select=1:ncpus=16
#PBS -l walltime=00:20:00
#PBS -q main
#PBS -j oe

# ncpus/walltime confirmed against a real timed case.build on Derecho on
# 2026-09-08 (this experiment's compset/resolution, LE2-1091.005 hybrid
# case): 500s wallclock. ncpus=16 matches GMAKE_J=16 (`./xmlquery GMAKE_J`
# in a built case) — CIME's actual build parallelism, independent of
# whatever ncpus a PBS job happens to request; requesting fewer than
# GMAKE_J undersubscribes the build and requesting more doesn't speed it
# up (see the pre-flight checklist in docs/RUNBOOK.md). walltime=20min is
# ~2.4x the measured time, comfortable headroom over the 1.5x minimum.
#
# A typical orchestrator invocation (no branch cycle) takes about a minute
# and only needs one core, but this same job/resource request covers the
# rarer cycle where warming is detected and create_branch_case.sh runs
# ./case.build synchronously inside this job — hence sizing for the build,
# not the common case.
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
