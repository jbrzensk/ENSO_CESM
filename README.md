# ENSO-MCB Automated Cycle

Automation for a CESM2-LE Marine Cloud Brightening (MCB) experiment: it
watches a running ensemble member for central-Pacific (Niño3.4) warming
and, when detected, automatically branches off a new case with MCB seeding
turned on for that year's June–August, then returns to the normal
year-by-year run. It runs unattended on the HPC system (Derecho) as a
self-chaining sequence of PBS jobs, for the life of the experiment (through
2100 by default).

See [WORKFLOW.md](WORKFLOW.md) for the full explanation of the experiment
cycle, the warming check, and how each piece fits together (with diagrams).

## Repository layout

| File | Purpose |
| --- | --- |
| `enso_mcb_orchestrator.py` | PBS job entry point; drives one state transition per invocation. |
| `enso_mcb_decision.py` | The branch/state-machine decision logic (pure function, fully unit-tested). |
| `enso_mcb_jobs.py` | All side-effecting operations: CIME `xmlchange`/`case.submit`, subprocess calls, self-chaining `qsub`. |
| `enso_mcb_state.py` | Lineage state (`CycleState`, `Stage`) and its JSON persistence. |
| `enso_mcb_config.py`, `enso_mcb_config.yaml` | Config loading/validation and this deployment's fixed settings. |
| `check_warming.py` | Computes the Niño3.4 SST anomaly and compares it to the warming threshold. |
| `build_climatology.py` | Builds/caches the rolling 30-year June Niño3.4 climatology baseline. |
| `create_branch_case.sh` | Parameterized CESM branch-case creator, called by the orchestrator (`DRY_RUN=1` supported). |
| `create_ENSO_controller_case.sh` | Original hand-edited script; still used manually for a lineage's first case. |
| `orchestrator_wrapper.sh` | The PBS script actually submitted to the scheduler. |
| `docs/RUNBOOK.md` | Operator's guide: pre-flight checklist, bootstrapping, monitoring, failure recovery. |
| `docs/superpowers/specs/` | Original design spec and implementation plan. |
| `tests/` | Pytest suite — decision logic, orchestrator cycles, and shell-script behavior, all without touching PBS or `/glade`. |

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest
```

OR 

```bash
ml conda
conda activate ENSO_Control
pytest
```


The test suite runs in seconds: the branch/warming decision logic and the
orchestrator's per-cycle behavior are tested with real CESM/PBS calls
mocked out, and `create_branch_case.sh` has a `DRY_RUN=1` mode so its shell
logic can be exercised without creating or building a real case.

## Status

This automation has not yet run a real production cycle on Derecho. Several
integration points are explicitly unverified against the real system —
`case.submit`'s job-ID output format, POP history file naming, and real
`case.build` timing — and must be confirmed before the first bootstrap.
See the **pre-flight checklist** at
the top of [docs/RUNBOOK.md](docs/RUNBOOK.md#pre-flight-checklist-do-this-once-before-the-first-bootstrap)
before relying on this for a real experiment.

## Further reading

- [WORKFLOW.md](WORKFLOW.md) — how the automation works, with diagrams.
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — how to operate it: bootstrapping a
  lineage, monitoring, and recovering from failures.
- [docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md](docs/superpowers/specs/2026-08-17-enso-mcb-automation-design.md) —
  the original design rationale.
