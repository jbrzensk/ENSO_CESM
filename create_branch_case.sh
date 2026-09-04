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
#
# Creates, configures and *builds* the case. On success, prints
# "CASEDIR=<path>" as the last line of stdout.
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
SRCDIR="${SRCDIR:-/glade/work/jabrzenski/cases/ENSO_walker/MCB_mods}"
TAGDIR="${TAGDIR:-/glade/u/home/jabrzenski/CESM/CESM2.1.5}"
CASEROOT="${CASEROOT:-/glade/work/jabrzenski/cases/ENSO_walker}"
SCRATCHROOT="${SCRATCHROOT:-/glade/derecho/scratch/jabrzenski}"

# 10# forces base-10: an already-zero-padded BRANCH_NUMBER like "009" would
# otherwise be parsed as octal (and "008"/"009" are invalid octal, a hard error).
BRANCH_SUFFIX=$(printf "%03d" "$((10#$BRANCH_NUMBER))")
RUNNAME="b.e21.${COMPSET}.${RESOLN}.ENSO_JJASONDJF_375cm3.${ENS}.branch.${BRANCH_SUFFIX}"

CASEDIR="$CASEROOT/$RUNNAME"
RUNDIR="$SCRATCHROOT/$RUNNAME/run"
ARCHIVEDIR="$SCRATCHROOT/archive/$RUNNAME/"
ICSDIR="$SCRATCHROOT/archive/$REFCASE/rest/${STARTDATE}-00000"

# Fail before mutating anything if the case directory already exists. This
# script is not resumable: a re-run against a half-created case would
# otherwise die deep inside CIME with a confusing error.
if [ -e "$CASEDIR" ]; then
  echo "ERROR: case directory already exists: $CASEDIR" >&2
  echo "       This script cannot resume a partially-created case. Inspect it," >&2
  echo "       and if it is an incomplete leftover, 'rm -rf $CASEDIR' (and the" >&2
  echo "       matching run directory $RUNDIR) before retrying." >&2
  exit 1
fi

run() {
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "DRYRUN: $*"
  else
    "$@"
  fi
}

echo "##### setting up case $RUNNAME #####"

(
  if [ "${DRY_RUN:-0}" != "1" ]; then
    cd "$TAGDIR/cime/scripts"
  fi
  run ./create_newcase --case "$CASEDIR" --res "$RESOLN" --compset "$COMPSET" --project "$PROJECT"
)

(
  if [ "${DRY_RUN:-0}" != "1" ]; then
    cd "$CASEDIR"
  fi

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
  # Monthly restarts. The next MCB branch case branches from the June 1
  # restart of a RUNNING segment; with only the default end-of-segment
  # restart, no June 1 restart file would ever exist to copy from.
  run ./xmlchange REST_OPTION=nmonths
  run ./xmlchange REST_N=1

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

  # Build the case here: nothing else in the automated chain ever calls
  # case.build, and case.submit on an unbuilt case fails. Nobody has timed
  # a real build on this system yet — it may take well over an hour — and
  # the orchestrator blocks on it; see the walltime note in
  # orchestrator_wrapper.sh and RUNBOOK.md pre-flight item 6.
  run ./case.build
)

echo "##### script finished, case built #####"
echo "CASEDIR=$CASEDIR"
