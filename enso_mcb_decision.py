"""Pure stage-transition logic for one ENSO-MCB lineage.

A lineage year Y is the 12-month segment from Mar 1 Y to Mar 1 Y+1, so it
ends right after DJF season Y (Dec Y, Jan Y+1, Feb Y+1):

RUNNING (segment Mar Y -> Mar Y+1 finished)
  -> DJF Y Nino3.4 anomaly >= threshold:
       new branch case from the Y-06-01 restart, MCB on for JJASONDJF
       (STOP_N=9, ending Mar 1 Y+1)                       -> MCB_ON, year Y
  -> otherwise: resubmit the same case for Mar Y+1 -> Mar Y+2
                                                          -> RUNNING, year Y+1
MCB_ON (the 9-month MCB segment finished, at Mar 1 Y+1)
  -> turn MCB off in that branch case and run it Mar Y+1 -> Mar Y+2
                                                          -> RUNNING, year Y+1
"""
import dataclasses
from typing import Optional

from enso_mcb_state import CycleState, Stage

# MCB is on June through February: JJASONDJF.
MCB_START_MONTH_DAY = "06-01"
MCB_MONTHS = 9
SEGMENT_START_MONTH_DAY = "03-01"
SEGMENT_MONTHS = 12


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
                start_date=f"{state.year}-{MCB_START_MONTH_DAY}",
                stop_n=MCB_MONTHS,
                mcb_on=True,
                next_branch_number=state.branch_number + 1,
                next_year=state.year,
            )
        return _next_segment(state, end_year, action="resubmit_running")

    if state.stage == Stage.MCB_ON:
        return _next_segment(state, end_year, action="flip_mcb_off_resubmit")

    raise ValueError(f"Cannot decide a transition from stage {state.stage!r}")


def _next_segment(state: CycleState, end_year: int, action: str) -> Transition:
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
        action=action,
        next_stage=Stage.RUNNING,
        ref_case=state.case_name,
        start_date=f"{next_year}-{SEGMENT_START_MONTH_DAY}",
        stop_n=SEGMENT_MONTHS,
        mcb_on=False,
        next_branch_number=state.branch_number,
        next_year=next_year,
    )
