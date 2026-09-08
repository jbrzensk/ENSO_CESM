#!/usr/bin/env bash
# Script to create an SSP3-7.0 (CESM2-LE) case which will eventually have MCB used to modulate ENSO
set -euo pipefail

ens='1091'

# branch.000: the very first case in this lineage, so the orchestrator's
# later --branch-number 0 (its default) matches this case's own suffix and
# the first MCB branch it creates becomes branch.001.
runname='b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.'$ens'.branch.000'

##### choose whether we're creating a whole new ensemble member, or a new branch #####

# for a new ensemble member:
refcase='b.e21.BSSP370smbb.f09_g17.LE2-1091.005'
runtype='hybrid'
stopn=2

# for a new branch:
#refcase='b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.'$ens'.branch.008'
#runtype='branch'
#stopn=3

##### #####

# Must exactly match a directory under icsdir below (real CESM2-LE archive
# restart dumps are irregularly spaced — quarterly through 2030, then a few
# decadal snapshots, then quarterly again from 2080). Confirmed available
# dates on 2026-09-08:
#   ls /glade/campaign/cgd/cesm/CESM2-LE/restarts/b.e21.BSSP370smbb.f09_g17.LE2-1091.005/rest/
startdate='2030-01-01'

# Follows the hybrid/branch choice above: a new ensemble member's restart
# comes from the public CESM2-LE archive, but a new branch continues this
# lineage's own previously-archived case, not the public archive.
if [ "$runtype" = 'hybrid' ]; then
  icsdir='/glade/campaign/cgd/cesm/CESM2-LE/restarts/'$refcase'/rest/'$startdate'-00000'
else
  icsdir='/glade/derecho/scratch/jabrzenski/archive/'$refcase'/rest/'$startdate'-00000'
fi

resoln='f09_g17'
compset='BSSP370smbb'
project='UCSD0083'

srcdir='/glade/work/jabrzenski/cases/ENSO_walker/MCB_mods'
tagdir='/glade/u/home/jabrzenski/CESM/CESM2.1.5'

caseroot='/glade/work/jabrzenski/cases/ENSO_walker'

echo "##### setting up case "$runname" #####"

casedir=$caseroot/$runname
rundir=/glade/derecho/scratch/jabrzenski/$runname/run

##### Create case

echo "##### creating case #####"

if [ -d "$casedir" ]; then
  echo "##### $casedir already exists, skipping create_newcase (delete it first to force a recreate) #####"
else
  cd $tagdir/cime/scripts
  ./create_newcase --case $casedir --res $resoln --compset $compset --project $project
fi

echo "##### create_newcase complete #####"

##### Change xml values

cd $casedir

echo "##### changing xml values #####"

./xmlchange JOB_WALLCLOCK_TIME=1:15:00 --subgroup case.run
./xmlchange RUN_TYPE=$runtype
./xmlchange GET_REFCASE=FALSE
./xmlchange RUN_REFCASE=$refcase
if [ "$runtype" = 'hybrid' ]; then
  # "cesm2_init" is the public CESM2-LE archive's standard reference-restart
  # naming convention; a branch continuing this lineage's own case doesn't use it.
  ./xmlchange RUN_REFDIR=cesm2_init
fi
./xmlchange RUN_REFDATE=$startdate
./xmlchange RUN_STARTDATE=$startdate
./xmlchange DOUT_S_ROOT=/glade/derecho/scratch/jabrzenski/archive/$runname/
./xmlchange CIME_OUTPUT_ROOT=/glade/derecho/scratch/jabrzenski/
./xmlchange RUNDIR=$rundir/

./xmlchange PROJECT=$project
./xmlchange STOP_N=$stopn
./xmlchange STOP_OPTION=nmonths
./xmlchange RESUBMIT=3

echo "##### xmlchange complete #####"

##### Copy initial conditions

echo "##### copying initial conditions #####"

if [ -d "$rundir" ] && [ -n "$(ls -A "$rundir" 2>/dev/null)" ]; then
  echo "##### $rundir already has files, skipping copy (delete it first to force a recopy) #####"
else
  mkdir -p $rundir
  cp $icsdir/* $rundir/.
fi

echo "##### initial conditions copied #####"

##### Set up case, copy source mods and namelist

echo "##### executing case.setup --reset and preview_namelists #####"

./case.setup --reset
./preview_namelists

echo "##### case.setup --reset and preview_namelists complete #####"

echo "##### copying source mods #####"
cp $srcdir/* SourceMods/src.cam/.
echo "##### source mods copied #####"

echo "##### adding MCB amount code to user_nl_cam #####"
cat >> user_nl_cam << EOF
MCB_seeding_amt = 1
EOF
echo "##### MCB amount added #####"

echo "##### script finished, ready to build  #####"
