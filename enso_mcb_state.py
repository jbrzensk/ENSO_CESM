import dataclasses
import json
import os
from typing import Optional


class Stage:
    RUNNING = "RUNNING"
    MCB_ON = "MCB_ON"
    MCB_COOLDOWN = "MCB_COOLDOWN"
    FAILED = "FAILED"
    DONE = "DONE"


@dataclasses.dataclass
class CycleState:
    lineage_name: str
    case_name: str
    stage: str
    branch_number: int
    year: int
    # Recovery breadcrumbs, only set when the orchestrator marks a lineage
    # FAILED. Both default so state files written before these fields existed
    # still load through CycleState(**data).
    failed_from_stage: Optional[str] = None
    failure_reason: Optional[str] = None


def load_state(path: str) -> CycleState:
    with open(path) as f:
        data = json.load(f)
    return CycleState(**data)


def save_state(path: str, state: CycleState) -> None:
    # The repo's state/ directory is not tracked by git, so the first save
    # on a fresh checkout (bootstrap's) has to create it.
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(dataclasses.asdict(state), f, indent=2)
    os.replace(tmp_path, path)
