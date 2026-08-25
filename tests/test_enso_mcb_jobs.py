import json
import subprocess

import pytest

import enso_mcb_jobs as jobs


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_parse_last_job_id_extracts_numeric_id():
    assert jobs.parse_last_job_id("12345.desched1\n") == "12345"


def test_parse_last_job_id_raises_on_empty_output():
    with pytest.raises(ValueError, match="no output"):
        jobs.parse_last_job_id("")


def test_parse_last_job_id_raises_on_unparseable_line():
    with pytest.raises(ValueError, match="could not parse"):
        jobs.parse_last_job_id("submission failed\n")


def test_submit_case_returns_parsed_job_id(monkeypatch):
    def fake_run(cmd, cwd, capture_output, text, check):
        assert cmd == ["./case.submit"]
        assert cwd == "/fake/case"
        return FakeCompletedProcess(stdout="Submitted job: 55555.derecho\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert jobs.submit_case("/fake/case") == "55555"


def test_resubmit_case_sets_stop_n_then_submits(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, check=None, capture_output=False, text=False):
        calls.append(cmd)
        if cmd[0] == "./case.submit":
            return FakeCompletedProcess(stdout="99999.derecho\n")
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    job_id = jobs.resubmit_case("/fake/case", 12)

    assert calls[0] == ["./xmlchange", "STOP_N=12"]
    assert calls[1] == ["./case.submit"]
    assert job_id == "99999"


def test_flip_mcb_off_replaces_namelist_line(tmp_path, monkeypatch):
    nl_path = tmp_path / "user_nl_cam"
    nl_path.write_text("some_other_var = 1\nMCB_seeding_amt = 1\n")

    calls = []

    def fake_run(cmd, cwd=None, check=None):
        calls.append((cmd, cwd))
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.flip_mcb_off(str(tmp_path))

    content = nl_path.read_text()
    assert "MCB_seeding_amt = 0" in content
    assert content.count("MCB_seeding_amt") == 1
    assert "some_other_var = 1" in content
    assert calls == [(["./preview_namelists"], str(tmp_path))]


def test_set_batch_mail_runs_expected_xmlchange_calls(monkeypatch):
    calls = []

    def fake_run(cmd, cwd=None, check=None):
        calls.append((cmd, cwd))
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    jobs.set_batch_mail("/fake/case", "walkerl@example.edu")

    assert calls == [
        (["./xmlchange", "BATCH_MAIL_TO=walkerl@example.edu"], "/fake/case"),
        (["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], "/fake/case"),
    ]


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
    def fake_run(cmd, env, capture_output, text, check):
        assert env["REFCASE"] == "refcase-1"
        assert env["MCB_ON"] == "1"
        assert env["NOTIFICATION_EMAIL"] == "walkerl@example.edu"
        return FakeCompletedProcess(
            stdout="##### done #####\nCASEDIR=/glade/work/walkerl/cases/branch.009\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    casedir = jobs.create_branch_case(
        "create_branch_case.sh", "1051", "refcase-1", 9, "2054-06-01", 3, True,
        "/glade/work/walkerl/cases", "walkerl@example.edu",
    )

    assert casedir == "/glade/work/walkerl/cases/branch.009"


def test_create_branch_case_raises_when_no_casedir_reported(monkeypatch):
    def fake_run(cmd, env, capture_output, text, check):
        return FakeCompletedProcess(stdout="no casedir here\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="did not report a CASEDIR"):
        jobs.create_branch_case(
            "create_branch_case.sh", "1051", "refcase-1", 9, "2054-06-01", 3, True,
            "/glade/work/walkerl/cases", "walkerl@example.edu",
        )


def test_submit_orchestrator_self_builds_qsub_dependency_command(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, check):
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
