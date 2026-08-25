import dataclasses
from typing import Optional

from enso_mcb_state import CycleState, Stage


@dataclasses.dataclass
class Transition:
    action: str
    next_stage: str
    ref_case: str
    start_date: str
    stop_n: int
    mcb_on: bool
    next_branch_number: int
    next_year: int


def decide_transition(state: CycleState, warming_result: Optional[dict], end_year: int) -> Transition:
    if state.stage == Stage.RUNNING:
        if warming_result is None:
            raise ValueError("warming_result is required when stage is RUNNING")
        if warming_result["warming"]:
            return Transition(
                action="branch_mcb_on",
                next_stage=Stage.MCB_ON,
                ref_case=state.case_name,
                start_date=f"{state.year}-06-01",
                stop_n=3,
                mcb_on=True,
                next_branch_number=state.branch_number + 1,
                next_year=state.year,
            )
        return _resubmit_next_year(state, end_year)

    if state.stage == Stage.MCB_ON:
        return Transition(
            action="flip_mcb_off_resubmit",
            next_stage=Stage.MCB_COOLDOWN,
            ref_case=state.case_name,
            start_date=f"{state.year}-09-01",
            stop_n=4,
            mcb_on=False,
            next_branch_number=state.branch_number,
            next_year=state.year,
        )

    if state.stage == Stage.MCB_COOLDOWN:
        return _resubmit_next_year(state, end_year)

    raise ValueError(f"Cannot decide a transition from stage {state.stage!r}")


def _resubmit_next_year(state: CycleState, end_year: int) -> Transition:
    next_year = state.year + 1
    if next_year > end_year:
        return Transition(
            action="stop",
            next_stage=Stage.DONE,
            ref_case=state.case_name,
            start_date="",
            stop_n=0,
            mcb_on=False,
            next_branch_number=state.branch_number,
            next_year=state.year,
        )
    return Transition(
        action="resubmit_running",
        next_stage=Stage.RUNNING,
        ref_case=state.case_name,
        start_date=f"{next_year}-01-01",
        stop_n=12,
        mcb_on=False,
        next_branch_number=state.branch_number,
        next_year=next_year,
    )
