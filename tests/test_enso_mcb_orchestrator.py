import textwrap

import pytest

import enso_mcb_jobs as jobs
import enso_mcb_orchestrator as orch
from enso_mcb_state import CycleState, Stage, load_state, save_state


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(f"""\
        ens: "1051"
        resoln: "f09_g17"
        compset: "BSSP370smbb"
        project: "UCSD0083"
        srcdir: "/tmp/srcdir"
        tagdir: "/tmp/tagdir"
        caseroot: "{tmp_path}/cases"
        scratchroot: "{tmp_path}/scratch"
        climatology_sst_dir: "{tmp_path}/sst_tseries"
        climatology_cache_dir: "{tmp_path}/climatology_cache"
        climatology_forcing_variant: "smbb"
        climatology_member_ordinal: "003"
        build_climatology_script: "build_climatology.py"
        warming_threshold_c: 1.0
        end_year: 2100
        notification_email: "jabrzenski@ucsd.edu"
        python_exe: "python3"
        check_warming_script: "check_warming.py"
        create_branch_case_script: "create_branch_case.sh"
        orchestrator_wrapper_script: "orchestrator_wrapper.sh"
        orchestrator_queue: "main"
    """))
    return str(path)


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(str(path), CycleState(
        lineage_name="enso_mcb_1051", case_name="branch.008",
        stage=Stage.RUNNING, branch_number=8, year=2054,
    ))
    return str(path)


def test_run_cycle_branches_to_mcb_on_when_warming_detected(monkeypatch, config_file, state_file):
    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 1.4, "warming": True})
    branch_args = {}
    monkeypatch.setattr(jobs, "create_branch_case",
                         lambda *a, **k: branch_args.update(args=a, kwargs=k) or "/cases/branch.009")
    monkeypatch.setattr(jobs, "submit_case", lambda casedir: "11111")
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email, project=None, queue=None:
                             submitted_self.update(
                                 wrapper=wrapper, job_id=job_id, state_file=sf, email=email,
                                 project=project, queue=queue))

    orch.run_cycle(state_file, config_file)

    new_state = load_state(state_file)
    assert new_state.stage == Stage.MCB_ON
    assert new_state.case_name == "branch.009"
    assert new_state.branch_number == 9
    assert new_state.year == 2054
    assert submitted_self["job_id"] == "11111"
    assert submitted_self["project"] == "UCSD0083"
    assert submitted_self["queue"] == "main"


def test_run_cycle_derives_climatology_member_from_ens_and_ordinal_and_passes_result_through(
        monkeypatch, config_file, state_file):
    climatology_calls = {}
    monkeypatch.setattr(jobs, "build_climatology",
                         lambda *a, **k: climatology_calls.update(args=a) or "/cache/nino34_climatology.nc")
    warming_calls = {}
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: warming_calls.update(args=a) or
                             {"year": 2054, "anomaly_c": 0.2, "warming": False})
    monkeypatch.setattr(jobs, "resubmit_case", lambda casedir, stop_n: "22222")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(state_file, config_file)

    (python_exe, script, sst_dir, member, variant, year, cache_dir) = climatology_calls["args"]
    assert member == "LE2-1051.003"  # derived from config's ens "1051" + climatology_member_ordinal "003"
    assert variant == "smbb"
    assert year == 2054
    assert script == "build_climatology.py"

    (_, _, _, climatology_file_arg, _, _) = warming_calls["args"]
    assert climatology_file_arg == "/cache/nino34_climatology.nc"


def test_run_cycle_passes_every_configured_value_to_create_branch_case(
        monkeypatch, config_file, state_file, tmp_path):
    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 1.4, "warming": True})
    captured = {}
    monkeypatch.setattr(jobs, "create_branch_case",
                         lambda *a: captured.update(args=a) or "/cases/branch.009")
    monkeypatch.setattr(jobs, "submit_case", lambda casedir: "11111")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(state_file, config_file)

    (script, ens, refcase, branch_number, startdate, stop_n, mcb_on, caseroot,
     email, resoln, compset, project, srcdir, tagdir, scratchroot) = captured["args"]
    assert script == "create_branch_case.sh"
    assert ens == "1051"
    assert refcase == "branch.008"
    assert branch_number == 9
    assert startdate == "2054-06-01"
    assert (stop_n, mcb_on) == (3, True)
    assert caseroot == f"{tmp_path}/cases"
    assert email == "jabrzenski@ucsd.edu"
    assert resoln == "f09_g17"
    assert compset == "BSSP370smbb"
    assert project == "UCSD0083"
    assert srcdir == "/tmp/srcdir"
    assert tagdir == "/tmp/tagdir"
    assert scratchroot == f"{tmp_path}/scratch"


def test_run_cycle_resubmits_next_year_when_no_warming(monkeypatch, config_file, state_file):
    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 0.2, "warming": False})
    monkeypatch.setattr(jobs, "resubmit_case", lambda casedir, stop_n: "22222")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(state_file, config_file)

    new_state = load_state(state_file)
    assert new_state.stage == Stage.RUNNING
    assert new_state.case_name == "branch.008"
    assert new_state.year == 2055


def test_run_cycle_flips_mcb_off_after_mcb_on_segment(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.009", stage=Stage.MCB_ON,
        branch_number=9, year=2054,
    ))
    monkeypatch.setattr(jobs, "flip_mcb_off", lambda casedir: None)
    monkeypatch.setattr(jobs, "resubmit_case", lambda casedir, stop_n: "33333")
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.run_cycle(str(state_path), config_file)

    new_state = load_state(str(state_path))
    assert new_state.stage == Stage.MCB_COOLDOWN
    assert new_state.year == 2054


def test_run_cycle_stops_and_marks_done_past_end_year(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.008", stage=Stage.RUNNING,
        branch_number=8, year=2100,
    ))
    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2100, "anomaly_c": 0.1, "warming": False})
    submitted_self = []
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: submitted_self.append(True))

    orch.run_cycle(str(state_path), config_file)

    new_state = load_state(str(state_path))
    assert new_state.stage == Stage.DONE
    assert submitted_self == []


@pytest.mark.parametrize("terminal_stage", [Stage.FAILED, Stage.DONE])
def test_run_cycle_does_nothing_for_terminal_states(monkeypatch, config_file, tmp_path,
                                                    terminal_stage):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.008", stage=terminal_stage,
        branch_number=8, year=2060,
    ))
    calls = []
    for name in ("build_climatology", "run_check_warming", "create_branch_case", "submit_case",
                 "resubmit_case", "flip_mcb_off", "set_batch_mail",
                 "configure_case_for_orchestration", "submit_orchestrator_self"):
        monkeypatch.setattr(jobs, name,
                            lambda *a, _name=name, **k: calls.append(_name) or {})

    orch.run_cycle(str(state_path), config_file)

    assert calls == []
    assert load_state(str(state_path)).stage == terminal_stage


def bootstrap_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "configure_case_for_orchestration",
                         lambda casedir: calls.append(("configure", casedir)))
    monkeypatch.setattr(jobs, "set_batch_mail",
                         lambda casedir, email: calls.append(("set_batch_mail", casedir, email)))
    monkeypatch.setattr(jobs, "resubmit_case",
                         lambda casedir, stop_n: calls.append(("resubmit_case", casedir, stop_n)) or "44444")
    return calls


def test_bootstrap_creates_initial_state_and_submits_first_segment(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "bootstrap_state.json"
    calls = bootstrap_recorder(monkeypatch)
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email, project=None, queue=None:
                             submitted_self.update(job_id=job_id, project=project, queue=queue))

    orch.bootstrap(str(state_path), config_file, "enso_mcb_1051", "initial-case", 2050)

    new_state = load_state(str(state_path))
    assert new_state.lineage_name == "enso_mcb_1051"
    assert new_state.case_name == "initial-case"
    assert new_state.stage == Stage.RUNNING
    assert new_state.branch_number == 0
    assert new_state.year == 2050
    # The pipeline-required XML settings and the mail settings must both be
    # applied before the first submission.
    assert [call[0] for call in calls] == ["configure", "set_batch_mail", "resubmit_case"]
    assert calls[0][1].endswith("/cases/initial-case")
    assert calls[1][2] == "jabrzenski@ucsd.edu"
    assert calls[2] == ("resubmit_case", calls[2][1], 12)
    assert submitted_self["job_id"] == "44444"
    assert submitted_self["project"] == "UCSD0083"
    assert submitted_self["queue"] == "main"


def test_bootstrap_records_non_default_branch_number(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "bootstrap_state.json"
    bootstrap_recorder(monkeypatch)
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)

    orch.bootstrap(str(state_path), config_file, "enso_mcb_1051", "branch.009", 2054,
                   branch_number=9)

    assert load_state(str(state_path)).branch_number == 9


def test_main_bootstrap_threads_branch_number_from_cli(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "bootstrap_state.json"
    bootstrap_recorder(monkeypatch)
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", [
        "enso_mcb_orchestrator.py",
        "--state-file", str(state_path), "--config-file", config_file,
        "--bootstrap", "--lineage-name", "enso_mcb_1051",
        "--initial-refcase", "branch.009", "--start-year", "2054",
        "--branch-number", "9",
    ])

    orch.main()

    assert load_state(str(state_path)).branch_number == 9


def test_main_marks_failed_and_does_not_resubmit_on_error(monkeypatch, config_file, state_file):
    def boom(*a, **k):
        raise RuntimeError("case.submit blew up")

    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming", boom)
    submitted_self = []
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: submitted_self.append(True))
    monkeypatch.setattr(
        "sys.argv",
        ["enso_mcb_orchestrator.py", "--state-file", state_file, "--config-file", config_file],
    )

    with pytest.raises(SystemExit) as exc_info:
        orch.main()

    assert exc_info.value.code == 1
    new_state = load_state(state_file)
    assert new_state.stage == Stage.FAILED
    assert submitted_self == []


def test_main_records_failing_stage_and_reason(monkeypatch, config_file, state_file):
    def boom(*a, **k):
        raise RuntimeError("check_warming.py failed: history file not found")

    monkeypatch.setattr(jobs, "build_climatology", lambda *a, **k: "/fake/climatology.nc")
    monkeypatch.setattr(jobs, "run_check_warming", boom)
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: None)
    monkeypatch.setattr(
        "sys.argv",
        ["enso_mcb_orchestrator.py", "--state-file", state_file, "--config-file", config_file],
    )

    with pytest.raises(SystemExit):
        orch.main()

    new_state = load_state(state_file)
    assert new_state.stage == Stage.FAILED
    assert new_state.failed_from_stage == Stage.RUNNING
    assert "history file not found" in new_state.failure_reason


def test_mark_failed_preserves_original_stage_when_called_twice(tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.009", stage=Stage.MCB_ON,
        branch_number=9, year=2054,
    ))

    orch.mark_failed(str(state_path), RuntimeError("first failure"))
    orch.mark_failed(str(state_path), RuntimeError("second failure"))

    state = load_state(str(state_path))
    assert state.stage == Stage.FAILED
    assert state.failed_from_stage == Stage.MCB_ON
    assert "second failure" in state.failure_reason
