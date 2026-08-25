import dataclasses
import json
import os


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


def load_state(path: str) -> CycleState:
    with open(path) as f:
        data = json.load(f)
    return CycleState(**data)


def save_state(path: str, state: CycleState) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(dataclasses.asdict(state), f, indent=2)
    os.replace(tmp_path, path)
