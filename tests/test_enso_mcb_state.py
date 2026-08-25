from enso_mcb_state import CycleState, Stage, load_state, save_state


def test_save_and_load_state_round_trip(tmp_path):
    state_path = tmp_path / "state.json"
    state = CycleState(
        lineage_name="enso_mcb_1051",
        case_name="b.e21.BSSP370smbb.f09_g17.ENSO_JJASONDJF_375cm3.1051.branch.008",
        stage=Stage.RUNNING,
        branch_number=8,
        year=2054,
    )

    save_state(str(state_path), state)
    loaded = load_state(str(state_path))

    assert loaded == state


def test_save_state_is_atomic_leaves_no_tmp_file(tmp_path):
    state_path = tmp_path / "state.json"
    state = CycleState(
        lineage_name="l", case_name="c", stage=Stage.RUNNING,
        branch_number=1, year=2050,
    )

    save_state(str(state_path), state)

    assert not (tmp_path / "state.json.tmp").exists()
    assert state_path.exists()
