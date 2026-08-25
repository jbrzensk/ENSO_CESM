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
