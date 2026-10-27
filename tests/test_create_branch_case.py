import os
import pathlib
import subprocess

import pytest

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "create_branch_case.sh")

BASE_ENV = {
    "ENS": "1051",
    "REFCASE": "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
    "BRANCH_NUMBER": "9",
    "STARTDATE": "2054-06-01",
    "STOP_N": "3",
    "MCB_ON": "1",
}


@pytest.fixture
def run_script(tmp_path):
    """Runs create_branch_case.sh in DRY_RUN mode, isolated under tmp_path.

    CASEROOT/SCRATCHROOT default to a tmp_path sandbox rather than the
    script's real hardcoded defaults (/glade/work/jabrzenski/...). Without
    this, a test's computed case name can collide with a real, already
    -existing case directory on the actual deployment host (Derecho) -
    the script's non-resumable existence guard then exits before printing
    anything, and every assertion on stdout fails. A test that needs to
    exercise a real collision (see
    test_fails_before_mutating_anything_when_case_dir_exists) can still
    override CASEROOT explicitly; env_overrides always wins.
    """
    def _run_script(env_overrides):
        env = os.environ.copy()
        env["DRY_RUN"] = "1"
        env["CASEROOT"] = str(tmp_path / "cases")
        env["SCRATCHROOT"] = str(tmp_path / "scratch")
        env.update(env_overrides)
        return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)
    return _run_script


def test_default_caseroot_is_isolated_from_the_real_filesystem(run_script, tmp_path):
    """Guards against reintroducing the Derecho collision: a test run must
    never depend on what does or doesn't exist at the script's real,
    hardcoded default CASEROOT."""
    result = run_script(BASE_ENV)

    assert result.returncode == 0, result.stderr
    casedir_line = [line for line in result.stdout.splitlines()
                    if line.startswith("CASEDIR=")][-1]
    assert casedir_line.startswith(f"CASEDIR={tmp_path}")


def test_dry_run_reports_correct_branch_name_and_refcase(run_script):
    result = run_script(BASE_ENV)

    assert result.returncode == 0, result.stderr
    assert "branch.009" in result.stdout
    assert "RUN_REFCASE=b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008" in result.stdout


def test_dry_run_sets_stop_n_resubmit_zero_and_dout_s(run_script):
    result = run_script(BASE_ENV)

    assert "STOP_N=3" in result.stdout
    assert "RESUBMIT=0" in result.stdout
    assert "DOUT_S=TRUE" in result.stdout


def test_dry_run_sets_monthly_restart_frequency(run_script):
    """The next branch case needs a June 1 restart to branch from."""
    result = run_script(BASE_ENV)

    assert "REST_OPTION=nmonths" in result.stdout
    assert "REST_N=1" in result.stdout


def test_dry_run_builds_the_case(run_script):
    result = run_script(BASE_ENV)

    assert "DRYRUN: ./case.build" in result.stdout


def test_dry_run_builds_after_sourcemods_and_namelists(run_script):
    result = run_script(BASE_ENV)
    lines = result.stdout.splitlines()

    build_index = next(i for i, line in enumerate(lines) if "./case.build" in line)
    setup_index = next(i for i, line in enumerate(lines) if "./case.setup" in line)
    sourcemods_index = next(i for i, line in enumerate(lines) if "SourceMods/src.cam" in line)
    mcb_index = next(i for i, line in enumerate(lines) if "MCB_seeding_amt" in line)

    assert build_index > setup_index
    assert build_index > sourcemods_index
    assert build_index > mcb_index


def test_run_name_uses_the_configured_compset_and_resolution(run_script):
    env = dict(BASE_ENV, COMPSET="BSSP245cmip6", RESOLN="f19_g17")

    result = run_script(env)

    assert result.returncode == 0, result.stderr
    casedir_line = [line for line in result.stdout.splitlines()
                    if line.startswith("CASEDIR=")][-1]
    # The case name must reflect the actual configuration, not the old defaults.
    assert casedir_line.endswith(
        "b.e21.BSSP245cmip6.f19_g17.ENSO_JJASONDJF_375cm3.1051.branch.009")
    assert "BSSP370smbb" not in casedir_line
    assert "f09_g17" not in casedir_line


def test_zero_padded_branch_number_is_parsed_as_base_ten(run_script):
    """'008'/'009' are invalid octal; printf must not try to parse them that way."""
    env = dict(BASE_ENV, BRANCH_NUMBER="009")

    result = run_script(env)

    assert result.returncode == 0, result.stderr
    assert "branch.009" in result.stdout


def test_fails_before_mutating_anything_when_case_dir_exists(run_script, tmp_path):
    caseroot = tmp_path / "cases"
    existing = caseroot / "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.009"
    existing.mkdir(parents=True)
    env = dict(BASE_ENV, CASEROOT=str(caseroot))

    result = run_script(env)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert str(existing) in result.stderr
    assert "create_newcase" not in result.stdout


def test_dry_run_appends_mcb_line_when_mcb_on(run_script):
    result = run_script(BASE_ENV)

    assert "MCB_seeding_amt = 1" in result.stdout


def test_dry_run_skips_mcb_line_when_mcb_off(run_script):
    env = dict(BASE_ENV, MCB_ON="0")

    result = run_script(env)

    assert "MCB_seeding_amt" not in result.stdout


def test_prints_casedir_as_last_line(run_script):
    result = run_script(BASE_ENV)

    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines[-1].startswith("CASEDIR=")
    assert "branch.009" in lines[-1]


def test_fails_clearly_when_required_var_missing(run_script):
    env = dict(BASE_ENV)
    del env["REFCASE"]

    result = run_script(env)

    assert result.returncode != 0
    assert "REFCASE" in result.stderr
