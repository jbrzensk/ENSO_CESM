import pytest

from enso_mcb_decision import decide_transition
from enso_mcb_state import CycleState, Stage


def make_state(**overrides):
    defaults = dict(
        lineage_name="enso_mcb_1051",
        case_name="b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
        stage=Stage.RUNNING,
        branch_number=8,
        year=2054,
    )
    defaults.update(overrides)
    return CycleState(**defaults)


def test_running_with_warming_branches_to_mcb_on():
    state = make_state(stage=Stage.RUNNING, year=2054, branch_number=8)

    transition = decide_transition(state, {"warming": True, "anomaly_c": 1.5}, end_year=2100)

    assert transition.action == "branch_mcb_on"
    assert transition.next_stage == Stage.MCB_ON
    assert transition.ref_case == state.case_name
    assert transition.start_date == "2054-06-01"
    assert transition.stop_n == 3
    assert transition.mcb_on is True
    assert transition.next_branch_number == 9
    assert transition.next_year == 2054


def test_running_without_warming_resubmits_next_year():
    state = make_state(stage=Stage.RUNNING, year=2054, branch_number=8)

    transition = decide_transition(state, {"warming": False, "anomaly_c": 0.2}, end_year=2100)

    assert transition.action == "resubmit_running"
    assert transition.next_stage == Stage.RUNNING
    assert transition.start_date == "2055-01-01"
    assert transition.stop_n == 12
    assert transition.mcb_on is False
    assert transition.next_branch_number == 8
    assert transition.next_year == 2055


def test_running_requires_warming_result():
    state = make_state(stage=Stage.RUNNING)

    with pytest.raises(ValueError, match="warming_result is required"):
        decide_transition(state, None, end_year=2100)


def test_mcb_on_flips_off_and_runs_sept_through_dec():
    state = make_state(stage=Stage.MCB_ON, year=2054, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "flip_mcb_off_resubmit"
    assert transition.next_stage == Stage.MCB_COOLDOWN
    assert transition.start_date == "2054-09-01"
    assert transition.stop_n == 4
    assert transition.mcb_on is False
    assert transition.next_year == 2054


def test_mcb_cooldown_resubmits_next_year_running():
    state = make_state(stage=Stage.MCB_COOLDOWN, year=2054, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "resubmit_running"
    assert transition.next_stage == Stage.RUNNING
    assert transition.start_date == "2055-01-01"
    assert transition.next_year == 2055


def test_stops_when_next_year_exceeds_end_year_from_running():
    state = make_state(stage=Stage.RUNNING, year=2100, branch_number=8)

    transition = decide_transition(state, {"warming": False, "anomaly_c": 0.1}, end_year=2100)

    assert transition.action == "stop"
    assert transition.next_stage == Stage.DONE


def test_stops_when_next_year_exceeds_end_year_from_cooldown():
    state = make_state(stage=Stage.MCB_COOLDOWN, year=2100, branch_number=9)

    transition = decide_transition(state, None, end_year=2100)

    assert transition.action == "stop"
    assert transition.next_stage == Stage.DONE


@pytest.mark.parametrize("terminal_stage", [Stage.FAILED, Stage.DONE])
def test_cannot_transition_from_terminal_stage(terminal_stage):
    state = make_state(stage=terminal_stage)

    with pytest.raises(ValueError, match="Cannot decide a transition"):
        decide_transition(state, None, end_year=2100)
