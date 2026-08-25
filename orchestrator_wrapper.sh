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
