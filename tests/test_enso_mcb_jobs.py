import json
import subprocess

import pytest

import enso_mcb_jobs as jobs


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def make_fake_run(calls, handler=None):
    """Build a subprocess.run stand-in matching how enso_mcb_jobs calls it."""

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        calls.append((cmd, cwd))
        if handler is not None:
            return handler(cmd, cwd, env)
        return FakeCompletedProcess()

    return fake_run


CREATE_BRANCH_ARGS = (
    "create_branch_case.sh", "1051", "refcase-1", 9, "2054-06-01", 3, True,
    "/glade/work/walkerl/cases", "walkerl@example.edu",
    "f09_g17", "BSSP370smbb", "UCSD0083",
    "/glade/work/walkerl/MCB_mods", "/glade/work/walkerl/cesm_tags/cesm2.1.5",
    "/glade/derecho/scratch/walkerl",
)


def test_parse_last_job_id_extracts_numeric_id():
    assert jobs.parse_last_job_id("12345.desched1\n") == "12345"


def test_parse_last_job_id_raises_on_empty_output():
    with pytest.raises(ValueError, match="no output"):
        jobs.parse_last_job_id("")


def test_parse_last_job_id_raises_on_unparseable_line():
    with pytest.raises(ValueError, match="could not parse"):
        jobs.parse_last_job_id("submission failed\n")


def test_parse_last_job_id_prefers_archive_line_over_later_lines():
    output = (
        "Submitting job script case.run\n"
        "Submitted job case.run with id 12345.desched1\n"
        "Submitting job script case.st_archive\n"
        "Submitted job case.st_archive with id 12346.desched1\n"
        "Submitted job case.run with id 12345.desched1\n"
    )

    # The archive job's ID wins even though it is not the last line: depending
    # on the run job would let the orchestrator start before archiving is done.
    assert jobs.parse_last_job_id(output) == "12346"


def test_parse_last_job_id_uses_archive_line_when_it_is_last():
    output = (
        "Submitted job case.run with id 12345.desched1\n"
        "Submitted job case.st_archive with id 12346.desched1\n"
    )

    assert jobs.parse_last_job_id(output) == "12346"


def test_parse_last_job_id_falls_back_to_last_line_without_archive_line():
    output = "Submitting job script case.run\n55555.desched1\n"

    assert jobs.parse_last_job_id(output) == "55555"


def test_parse_last_job_id_ignores_archive_paths_in_non_submission_lines():
    output = (
        "Setting DOUT_S_ROOT to /glade/derecho/scratch/walkerl/archive/"
        "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.009\n"
        "Submitted job id is 12346.desched1\n"
    )

    # The DOUT_S_ROOT line contains "archive" only as a path component, and
    # JOB_ID_RE would match "21" out of "b.e21." if it were treated as a
    # candidate. The real job ID is on the following line.
    assert jobs.parse_last_job_id(output) == "12346"


def test_parse_last_job_id_prefers_st_archive_line_despite_archive_paths():
    output = (
        "Setting DOUT_S_ROOT to /glade/derecho/scratch/walkerl/archive/"
        "b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.009\n"
        "Submitted job case.run with id 12345.desched1\n"
        "Submitted job case.st_archive with id 12346.desched1\n"
        "Submitting job script case.run\n"
    )

    assert jobs.parse_last_job_id(output) == "12346"


def test_submit_case_returns_parsed_job_id(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(
        calls, lambda cmd, cwd, env: FakeCompletedProcess(
            stdout="Submitted job: 55555.derecho\n"),
    ))

    assert jobs.submit_case("/fake/case") == "55555"
    assert calls == [(["./case.submit"], "/fake/case")]


def test_resubmit_case_sets_stop_n_and_continue_run_then_submits(monkeypatch):
    calls = []

    def handler(cmd, cwd, env):
        if cmd[0] == "./case.submit":
            return FakeCompletedProcess(stdout="99999.derecho\n")
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", make_fake_run(calls, handler))

    job_id = jobs.resubmit_case("/fake/case", 12)

    assert [cmd for cmd, _ in calls] == [
        ["./xmlchange", "STOP_N=12"],
        ["./xmlchange", "CONTINUE_RUN=TRUE"],
        ["./case.submit"],
    ]
    assert all(cwd == "/fake/case" for _, cwd in calls)
    assert job_id == "99999"


def test_set_continue_run_false_sets_false(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(calls))

    jobs.set_continue_run("/fake/case", False)

    assert calls == [(["./xmlchange", "CONTINUE_RUN=FALSE"], "/fake/case")]


def test_configure_case_for_orchestration_forces_pipeline_xml_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(calls))

    jobs.configure_case_for_orchestration("/fake/case")

    assert [cmd for cmd, _ in calls] == [
        ["./xmlchange", "RESUBMIT=0"],
        ["./xmlchange", "STOP_OPTION=nmonths"],
        ["./xmlchange", "DOUT_S=TRUE"],
        ["./xmlchange", "REST_OPTION=nmonths"],
        ["./xmlchange", "REST_N=1"],
    ]
    assert all(cwd == "/fake/case" for _, cwd in calls)


def test_configure_case_for_orchestration_leaves_continue_run_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(calls))

    jobs.configure_case_for_orchestration("/fake/case")

    # An adopted case has run history, so CONTINUE_RUN must end up TRUE.
    # resubmit_case sets it; forcing FALSE here would leave a window where
    # the case is configured to re-initialize over that history.
    assert not any("CONTINUE_RUN" in arg for cmd, _ in calls for arg in cmd)


def test_flip_mcb_off_replaces_namelist_line(tmp_path, monkeypatch):
    nl_path = tmp_path / "user_nl_cam"
    nl_path.write_text("some_other_var = 1\nMCB_seeding_amt = 1\n")

    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(calls))

    jobs.flip_mcb_off(str(tmp_path))

    content = nl_path.read_text()
    assert "MCB_seeding_amt = 0" in content
    assert content.count("MCB_seeding_amt") == 1
    assert "some_other_var = 1" in content
    assert calls == [(["./preview_namelists"], str(tmp_path))]


def test_set_batch_mail_runs_expected_xmlchange_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", make_fake_run(calls))

    jobs.set_batch_mail("/fake/case", "walkerl@example.edu")

    assert calls == [
        (["./xmlchange", "BATCH_MAIL_TO=walkerl@example.edu"], "/fake/case"),
        (["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], "/fake/case"),
    ]


def test_failed_command_error_includes_captured_stdout_and_stderr(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        raise subprocess.CalledProcessError(
            2, cmd,
            output="ERROR: xmlchange output detail\n",
            stderr="ERROR: STOP_N is not a valid xml id\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        jobs.set_stop_n("/fake/case", 12)

    message = str(exc_info.value)
    assert "STOP_N is not a valid xml id" in message
    assert "xmlchange output detail" in message
    assert "exit status 2" in message
    assert "/fake/case" in message


def test_submit_case_failure_error_includes_captured_output(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        raise subprocess.CalledProcessError(
            1, cmd, output="", stderr="ERROR: Case is not built\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Case is not built"):
        jobs.submit_case("/fake/case")


def test_create_branch_case_failure_error_includes_build_log(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        raise subprocess.CalledProcessError(
            1, cmd, output="##### setting up case #####\nBuild failed in cam\n", stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Build failed in cam"):
        jobs.create_branch_case(*CREATE_BRANCH_ARGS)


def test_submit_orchestrator_self_failure_error_includes_qsub_stderr(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        raise subprocess.CalledProcessError(
            1, cmd, output="", stderr="qsub: Unknown queue\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Unknown queue"):
        jobs.submit_orchestrator_self(
            "orchestrator_wrapper.sh", "55555", "/glade/work/state.json", "w@example.edu",
        )


def test_run_check_warming_parses_json_stdout(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(
            stdout=json.dumps({"year": 2054, "anomaly_c": 1.3, "warming": True}),
            returncode=0,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = jobs.run_check_warming("python3", "check_warming.py", "hist.nc", "clim.nc", 2054, 1.0)

    assert result == {"year": 2054, "anomaly_c": 1.3, "warming": True}


def test_run_check_warming_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(stderr="boom", returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        jobs.run_check_warming("python3", "check_warming.py", "hist.nc", "clim.nc", 2054, 1.0)


def test_create_branch_case_returns_parsed_casedir(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        captured["env"] = env
        return FakeCompletedProcess(
            stdout="##### done #####\nCASEDIR=/glade/work/walkerl/cases/branch.009\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    casedir = jobs.create_branch_case(*CREATE_BRANCH_ARGS)

    assert casedir == "/glade/work/walkerl/cases/branch.009"
    env = captured["env"]
    assert env["REFCASE"] == "refcase-1"
    assert env["MCB_ON"] == "1"
    assert env["NOTIFICATION_EMAIL"] == "walkerl@example.edu"


def test_create_branch_case_passes_every_configurable_variable(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        captured["env"] = env
        return FakeCompletedProcess(stdout="CASEDIR=/cases/branch.009\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.create_branch_case(*CREATE_BRANCH_ARGS)

    env = captured["env"]
    assert env["ENS"] == "1051"
    assert env["BRANCH_NUMBER"] == "9"
    assert env["STARTDATE"] == "2054-06-01"
    assert env["STOP_N"] == "3"
    assert env["RESOLN"] == "f09_g17"
    assert env["COMPSET"] == "BSSP370smbb"
    assert env["PROJECT"] == "UCSD0083"
    assert env["SRCDIR"] == "/glade/work/walkerl/MCB_mods"
    assert env["TAGDIR"] == "/glade/work/walkerl/cesm_tags/cesm2.1.5"
    assert env["CASEROOT"] == "/glade/work/walkerl/cases"
    assert env["SCRATCHROOT"] == "/glade/derecho/scratch/walkerl"


def test_create_branch_case_does_not_leak_ambient_environment(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        captured["env"] = env
        return FakeCompletedProcess(stdout="CASEDIR=/cases/branch.009\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # A stray PROJECT/CASEROOT in the PBS job environment must not reach the
    # script; only the explicitly configured values may.
    monkeypatch.setenv("PROJECT", "SOMEONE_ELSES_ALLOCATION")
    monkeypatch.setenv("CASEROOT", "/wrong/caseroot")
    monkeypatch.setenv("MCB_ON", "0")
    monkeypatch.setenv("STRAY_VARIABLE", "leaked")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    jobs.create_branch_case(*CREATE_BRANCH_ARGS)

    env = captured["env"]
    assert env["PROJECT"] == "UCSD0083"
    assert env["CASEROOT"] == "/glade/work/walkerl/cases"
    assert env["MCB_ON"] == "1"
    assert "STRAY_VARIABLE" not in env
    # PATH is passed through deliberately: the script needs it to find bash,
    # cp, and the CIME tooling.
    assert env["PATH"] == "/usr/bin:/bin"


def test_create_branch_case_raises_when_no_casedir_reported(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        return FakeCompletedProcess(stdout="no casedir here\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="did not report a CASEDIR"):
        jobs.create_branch_case(*CREATE_BRANCH_ARGS)


def test_submit_orchestrator_self_builds_qsub_dependency_command(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return FakeCompletedProcess(stdout="66666.derecho\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    job_id = jobs.submit_orchestrator_self(
        "orchestrator_wrapper.sh", "55555", "/glade/work/state.json", "walkerl@example.edu",
    )

    assert captured["cmd"] == [
        "qsub", "-W", "depend=afterok:55555", "-m", "ae", "-M", "walkerl@example.edu",
        "-v", "STATE_FILE=/glade/work/state.json", "orchestrator_wrapper.sh",
    ]
    assert job_id == "66666.derecho"


def test_submit_orchestrator_self_passes_project_and_queue_when_given(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=False, text=False, check=False):
        captured["cmd"] = cmd
        return FakeCompletedProcess(stdout="66666.derecho\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.submit_orchestrator_self(
        "orchestrator_wrapper.sh", "55555", "/glade/work/state.json", "walkerl@example.edu",
        project="UCSD0083", queue="develop",
    )

    assert captured["cmd"] == [
        "qsub", "-W", "depend=afterok:55555", "-m", "ae", "-M", "walkerl@example.edu",
        "-A", "UCSD0083", "-q", "develop",
        "-v", "STATE_FILE=/glade/work/state.json", "orchestrator_wrapper.sh",
    ]
