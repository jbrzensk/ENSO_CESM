import os
import pathlib
import subprocess

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "create_branch_case.sh")

BASE_ENV = {
    "ENS": "1051",
    "REFCASE": "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
    "BRANCH_NUMBER": "9",
    "STARTDATE": "2054-06-01",
    "STOP_N": "3",
    "MCB_ON": "1",
}


def run_script(env_overrides):
    env = os.environ.copy()
    env["DRY_RUN"] = "1"
    env.update(env_overrides)
    return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)


def test_dry_run_reports_correct_branch_name_and_refcase():
    result = run_script(BASE_ENV)

    assert result.returncode == 0, result.stderr
    assert "branch.009" in result.stdout
    assert "RUN_REFCASE=b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008" in result.stdout


def test_dry_run_sets_stop_n_resubmit_zero_and_dout_s():
    result = run_script(BASE_ENV)

    assert "STOP_N=3" in result.stdout
    assert "RESUBMIT=0" in result.stdout
    assert "DOUT_S=TRUE" in result.stdout


def test_dry_run_sets_batch_mail_when_notification_email_provided():
    env = dict(BASE_ENV, NOTIFICATION_EMAIL="walkerl@example.edu")

    result = run_script(env)

    assert "BATCH_MAIL_TO=walkerl@example.edu" in result.stdout
    assert "BATCH_MAIL_TYPE=begin,end,fail" in result.stdout


def test_dry_run_skips_batch_mail_when_notification_email_unset():
    result = run_script(BASE_ENV)

    assert "BATCH_MAIL_TO" not in result.stdout
    assert "BATCH_MAIL_TYPE" not in result.stdout


def test_dry_run_appends_mcb_line_when_mcb_on():
    result = run_script(BASE_ENV)

    assert "MCB_seeding_amt = 1" in result.stdout


def test_dry_run_skips_mcb_line_when_mcb_off():
    env = dict(BASE_ENV, MCB_ON="0")

    result = run_script(env)

    assert "MCB_seeding_amt" not in result.stdout


def test_prints_casedir_as_last_line():
    result = run_script(BASE_ENV)

    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines[-1].startswith("CASEDIR=")
    assert "branch.009" in lines[-1]


def test_fails_clearly_when_required_var_missing():
    env = dict(BASE_ENV)
    del env["REFCASE"]

    result = run_script(env)

    assert result.returncode != 0
    assert "REFCASE" in result.stderr
