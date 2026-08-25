#!/usr/bin/env python3
import argparse
import logging
import os
import sys

import enso_mcb_jobs as jobs
from enso_mcb_config import load_config
from enso_mcb_decision import decide_transition
from enso_mcb_state import CycleState, Stage, load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enso_mcb_orchestrator")


def history_file_path(config: dict, case_name: str, year: int) -> str:
    return os.path.join(
        config["scratchroot"], "archive", case_name, "ocn", "hist",
        f"{case_name}.pop.h.{year:04d}-06.nc",
    )


def run_cycle(state_file: str, config_file: str) -> None:
    config = load_config(config_file)
    state = load_state(state_file)

    if state.stage in (Stage.FAILED, Stage.DONE):
        log.info("Lineage %s is in terminal stage %s; nothing to do.", state.lineage_name, state.stage)
        return

    warming_result = None
    if state.stage == Stage.RUNNING:
        warming_result = jobs.run_check_warming(
            config["python_exe"], config["check_warming_script"],
            history_file_path(config, state.case_name, state.year),
            config["climatology_file"], state.year, config["warming_threshold_c"],
        )
        log.info("Warming check for %s year %s: %s", state.case_name, state.year, warming_result)

    transition = decide_transition(state, warming_result, config["end_year"])

    if transition.action == "stop":
        state.stage = Stage.DONE
        save_state(state_file, state)
        log.info("Reached end year %s; lineage %s complete.", config["end_year"], state.lineage_name)
        return

    if transition.action == "branch_mcb_on":
        casedir = jobs.create_branch_case(
            config["create_branch_case_script"], config["ens"], transition.ref_case,
            transition.next_branch_number, transition.start_date, transition.stop_n,
            transition.mcb_on, config["caseroot"], config["notification_email"],
            config["resoln"], config["compset"], config["project"],
            config["srcdir"], config["tagdir"], config["scratchroot"],
        )
        job_id = jobs.submit_case(casedir)
        state.case_name = os.path.basename(casedir)
        state.branch_number = transition.next_branch_number
    elif transition.action == "flip_mcb_off_resubmit":
        casedir = os.path.join(config["caseroot"], state.case_name)
        jobs.flip_mcb_off(casedir)
        job_id = jobs.resubmit_case(casedir, transition.stop_n)
    elif transition.action == "resubmit_running":
        casedir = os.path.join(config["caseroot"], state.case_name)
        job_id = jobs.resubmit_case(casedir, transition.stop_n)
    else:
        raise ValueError(f"Unknown transition action: {transition.action}")

    state.stage = transition.next_stage
    state.year = transition.next_year
    save_state(state_file, state)

    jobs.submit_orchestrator_self(
        config["orchestrator_wrapper_script"], job_id, state_file, config["notification_email"],
        config["project"], config["orchestrator_queue"],
    )


def bootstrap(state_file: str, config_file: str, lineage_name: str,
              initial_refcase: str, start_year: int, branch_number: int = 0) -> None:
    config = load_config(config_file)
    state = CycleState(
        lineage_name=lineage_name, case_name=initial_refcase,
        stage=Stage.RUNNING, branch_number=branch_number, year=start_year,
    )
    save_state(state_file, state)

    casedir = os.path.join(config["caseroot"], initial_refcase)
    # The adopted case was created outside this automation and may carry
    # settings (notably RESUBMIT>0) that conflict with orchestrated running,
    # so force the pipeline's requirements before the first submission.
    jobs.configure_case_for_orchestration(casedir)
    jobs.set_batch_mail(casedir, config["notification_email"])
    job_id = jobs.resubmit_case(casedir, 12)
    jobs.submit_orchestrator_self(
        config["orchestrator_wrapper_script"], job_id, state_file, config["notification_email"],
        config["project"], config["orchestrator_queue"],
    )


def mark_failed(state_file: str, error: BaseException = None) -> None:
    try:
        state = load_state(state_file)
        if state.stage != Stage.FAILED:
            # Preserve which stage the lineage was in: it is the one piece of
            # state an operator needs to resume the chain after a fix.
            state.failed_from_stage = state.stage
        if error is not None:
            state.failure_reason = f"{type(error).__name__}: {error}"
        state.stage = Stage.FAILED
        save_state(state_file, state)
    except Exception:
        log.exception("Could not record FAILED state for %s", state_file)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--config-file", default="enso_mcb_config.yaml")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--lineage-name")
    parser.add_argument("--initial-refcase")
    parser.add_argument("--start-year", type=int)
    parser.add_argument(
        "--branch-number", type=int, default=0,
        help="branch number of the case being bootstrapped from; the first MCB "
             "branch this lineage creates will be this number + 1 (default: 0)",
    )
    args = parser.parse_args()

    try:
        if args.bootstrap:
            if not (args.lineage_name and args.initial_refcase and args.start_year):
                parser.error("--bootstrap requires --lineage-name, --initial-refcase, and --start-year")
            bootstrap(args.state_file, args.config_file, args.lineage_name,
                      args.initial_refcase, args.start_year, args.branch_number)
        else:
            run_cycle(args.state_file, args.config_file)
    except Exception as exc:
        log.exception("Cycle failed for state file %s; halting chain.", args.state_file)
        mark_failed(args.state_file, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
