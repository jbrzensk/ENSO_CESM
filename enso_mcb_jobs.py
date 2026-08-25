import json
import os
import re
import subprocess

JOB_ID_RE = re.compile(r"(\d+)(?:\.\S+)?\s*$")
CASEDIR_RE = re.compile(r"^CASEDIR=(.+)$", re.MULTILINE)


def parse_last_job_id(submit_output: str) -> str:
    lines = [line for line in submit_output.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("case.submit produced no output to parse a job ID from")
    match = JOB_ID_RE.search(lines[-1])
    if not match:
        raise ValueError(f"could not parse job ID from case.submit output: {lines[-1]!r}")
    return match.group(1)


def submit_case(case_dir: str) -> str:
    result = subprocess.run(
        ["./case.submit"], cwd=case_dir, capture_output=True, text=True, check=True,
    )
    return parse_last_job_id(result.stdout)


def set_stop_n(case_dir: str, stop_n: int) -> None:
    subprocess.run(["./xmlchange", f"STOP_N={stop_n}"], cwd=case_dir, check=True)


def resubmit_case(case_dir: str, stop_n: int) -> str:
    set_stop_n(case_dir, stop_n)
    return submit_case(case_dir)


def flip_mcb_off(case_dir: str) -> None:
    nl_path = os.path.join(case_dir, "user_nl_cam")
    with open(nl_path) as f:
        lines = f.readlines()
    lines = [line for line in lines if not line.strip().startswith("MCB_seeding_amt")]
    lines.append("MCB_seeding_amt = 0\n")
    with open(nl_path, "w") as f:
        f.writelines(lines)
    subprocess.run(["./preview_namelists"], cwd=case_dir, check=True)


def set_batch_mail(case_dir: str, email: str) -> None:
    subprocess.run(["./xmlchange", f"BATCH_MAIL_TO={email}"], cwd=case_dir, check=True)
    subprocess.run(["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], cwd=case_dir, check=True)


def run_check_warming(python_exe: str, script_path: str, history_file: str,
                       climatology_file: str, year: int, threshold: float) -> dict:
    result = subprocess.run(
        [python_exe, script_path,
         "--history-file", history_file,
         "--climatology-file", climatology_file,
         "--year", str(year),
         "--threshold", str(threshold)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"check_warming.py failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def create_branch_case(script_path: str, ens: str, refcase: str, branch_number: int,
                        startdate: str, stop_n: int, mcb_on: bool, caseroot: str,
                        email: str) -> str:
    env = os.environ.copy()
    env.update({
        "ENS": ens,
        "REFCASE": refcase,
        "BRANCH_NUMBER": str(branch_number),
        "STARTDATE": startdate,
        "STOP_N": str(stop_n),
        "MCB_ON": "1" if mcb_on else "0",
        "CASEROOT": caseroot,
        "NOTIFICATION_EMAIL": email,
    })
    result = subprocess.run(
        ["bash", script_path], env=env, capture_output=True, text=True, check=True,
    )
    match = CASEDIR_RE.search(result.stdout)
    if not match:
        raise ValueError(f"create_branch_case.sh did not report a CASEDIR: {result.stdout!r}")
    return match.group(1)


def submit_orchestrator_self(wrapper_script: str, depend_job_id: str, state_file: str,
                              email: str) -> str:
    result = subprocess.run(
        ["qsub", "-W", f"depend=afterok:{depend_job_id}", "-m", "ae", "-M", email,
         "-v", f"STATE_FILE={state_file}", wrapper_script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()
