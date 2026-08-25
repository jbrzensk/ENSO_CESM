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
        climatology_file: "/tmp/clim.nc"
        warming_threshold_c: 1.0
        end_year: 2100
        notification_email: "walkerl@example.edu"
        python_exe: "python3"
        check_warming_script: "check_warming.py"
        create_branch_case_script: "create_branch_case.sh"
        orchestrator_wrapper_script: "orchestrator_wrapper.sh"
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
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2054, "anomaly_c": 1.4, "warming": True})
    monkeypatch.setattr(jobs, "create_branch_case", lambda *a, **k: "/cases/branch.009")
    monkeypatch.setattr(jobs, "submit_case", lambda casedir: "11111")
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email: submitted_self.update(
                             wrapper=wrapper, job_id=job_id, state_file=sf, email=email))

    orch.run_cycle(state_file, config_file)

    new_state = load_state(state_file)
    assert new_state.stage == Stage.MCB_ON
    assert new_state.case_name == "branch.009"
    assert new_state.branch_number == 9
    assert new_state.year == 2054
    assert submitted_self["job_id"] == "11111"


def test_run_cycle_resubmits_next_year_when_no_warming(monkeypatch, config_file, state_file):
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
    monkeypatch.setattr(jobs, "run_check_warming",
                         lambda *a, **k: {"year": 2100, "anomaly_c": 0.1, "warming": False})
    submitted_self = []
    monkeypatch.setattr(jobs, "submit_orchestrator_self", lambda *a, **k: submitted_self.append(True))

    orch.run_cycle(str(state_path), config_file)

    new_state = load_state(str(state_path))
    assert new_state.stage == Stage.DONE
    assert submitted_self == []


def test_run_cycle_does_nothing_for_terminal_states(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "state.json"
    save_state(str(state_path), CycleState(
        lineage_name="l", case_name="branch.008", stage=Stage.FAILED,
        branch_number=8, year=2060,
    ))
    calls = []
    monkeypatch.setattr(jobs, "run_check_warming", lambda *a, **k: calls.append("check") or {})

    orch.run_cycle(str(state_path), config_file)

    assert calls == []


def test_bootstrap_creates_initial_state_and_submits_first_segment(monkeypatch, config_file, tmp_path):
    state_path = tmp_path / "bootstrap_state.json"
    calls = []
    monkeypatch.setattr(jobs, "set_batch_mail",
                         lambda casedir, email: calls.append(("set_batch_mail", casedir, email)))
    monkeypatch.setattr(jobs, "resubmit_case",
                         lambda casedir, stop_n: calls.append(("resubmit_case", casedir, stop_n)) or "44444")
    submitted_self = {}
    monkeypatch.setattr(jobs, "submit_orchestrator_self",
                         lambda wrapper, job_id, sf, email: submitted_self.update(job_id=job_id))

    orch.bootstrap(str(state_path), config_file, "enso_mcb_1051", "initial-case", 2050)

    new_state = load_state(str(state_path))
    assert new_state.lineage_name == "enso_mcb_1051"
    assert new_state.case_name == "initial-case"
    assert new_state.stage == Stage.RUNNING
    assert new_state.branch_number == 0
    assert new_state.year == 2050
    assert calls[0][0] == "set_batch_mail"
    assert calls[0][2] == "walkerl@example.edu"
    assert calls[1] == ("resubmit_case", calls[1][1], 12)
    assert submitted_self["job_id"] == "44444"


def test_main_marks_failed_and_does_not_resubmit_on_error(monkeypatch, config_file, state_file):
    def boom(*a, **k):
        raise RuntimeError("case.submit blew up")

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
