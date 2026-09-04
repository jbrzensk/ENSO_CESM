# Script to create an SSP3-7.0 (CESM2-LE) case which will eventually have MCB used to modulate ENSO

ens='1051'

runname='b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.'$ens'.branch.009'

##### choose whether we're creating a whole new ensemble member, or a new branch #####

# for a new ensemble member:
#refcase='b.e21.BSSP370smbb.f09_g17.LE2-1011.001'
#runtype='hybrid'
#stopn=2

# for a new branch:
refcase='b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.'$ens'.branch.008'
runtype='branch'
stopn=3

##### #####

startdate='2049-06-01'

#icsdir='/glade/campaign/cgd/cesm/CESM2-LE/restarts/'$refcase'/rest/'$refdate'-00000'
icsdir='/glade/derecho/scratch/jabrzenski/archive/'$refcase'/rest/'$startdate'-00000'

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

cd $tagdir/cime/scripts

echo "##### creating case #####"

./create_newcase --case $casedir --res $resoln --compset $compset --project $project

echo "##### create_newcase complete #####"

##### Change xml values

cd $casedir

echo "##### changing xml values #####"

./xmlchange JOB_WALLCLOCK_TIME=1:15:00 --subgroup case.run
./xmlchange RUN_TYPE=$runtype
./xmlchange GET_REFCASE=FALSE
./xmlchange RUN_REFCASE=$refcase
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

mkdir -p $rundir

echo "##### copying initial conditions #####"

cp $icsdir/* $rundir/.

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
