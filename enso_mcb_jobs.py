import json
import os
import re
import subprocess

JOB_ID_RE = re.compile(r"(\d+)(?:\.\S+)?\s*$")
CASEDIR_RE = re.compile(r"^CASEDIR=(.+)$", re.MULTILINE)

# Environment variables passed through from the ambient environment when
# invoking create_branch_case.sh. The script shells out to real CESM/CIME
# tooling (create_newcase, case.setup, case.build), which needs a working
# PATH, HOME and module environment. Everything the script itself reads as
# configuration is set explicitly in create_branch_case()'s env dict, so a
# stray PROJECT/CASEROOT/SCRATCHROOT in the PBS job environment can never
# silently override the configured values.
PASSTHROUGH_ENV_VARS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TMPDIR",
    "LD_LIBRARY_PATH", "PYTHONPATH",
    "MODULEPATH", "MODULESHOME", "LMOD_CMD", "LMOD_PKG", "LMOD_SYSTEM_NAME",
)


def _run_checked(cmd, cwd=None, env=None):
    """Run a command, raising a RuntimeError that *includes the captured output*.

    `subprocess.CalledProcessError.__str__()` is only "returned non-zero exit
    status N" — the actual CIME/qsub error text lives in the captured
    stdout/stderr and would otherwise be thrown away.
    """
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        where = f" (in {cwd})" if cwd else ""
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"Command {' '.join(cmd)}{where} failed with exit status {exc.returncode}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}"
        ) from exc


def parse_last_job_id(submit_output: str) -> str:
    """Extract the job ID the orchestrator should depend on from case.submit output.

    case.submit prints one line per submitted job (the run job, then the
    short-term archive job). The orchestrator must depend on the *archive*
    job, since the warming check reads archived output — so prefer the
    `st_archive` job's line when one is present, rather than blindly
    trusting the last line to be the archive job.

    The match is deliberately on `st_archive` (CIME's actual archive job
    name) and not on the bare word "archive": case.submit output also
    contains archive *paths* (`DOUT_S_ROOT` is
    `/glade/derecho/scratch/<user>/archive/b.e21...`), and JOB_ID_RE would
    happily pull a digit fragment such as "21" out of `b.e21.` on such a
    line. A candidate line must both name `st_archive` and yield a job ID;
    otherwise we fall back to the last line, which is correct for
    single-line output and is the pre-existing behaviour. The real CIME
    output format is still unverified against Derecho — see the pre-flight
    checklist in docs/RUNBOOK.md.
    """
    lines = [line for line in submit_output.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("case.submit produced no output to parse a job ID from")

    for line in reversed(lines):
        if "st_archive" not in line.lower():
            continue
        match = JOB_ID_RE.search(line)
        if match:
            return match.group(1)

    match = JOB_ID_RE.search(lines[-1])
    if not match:
        raise ValueError(f"could not parse job ID from case.submit output: {lines[-1]!r}")
    return match.group(1)


def submit_case(case_dir: str) -> str:
    result = _run_checked(["./case.submit"], cwd=case_dir)
    return parse_last_job_id(result.stdout)


def set_stop_n(case_dir: str, stop_n: int) -> None:
    _run_checked(["./xmlchange", f"STOP_N={stop_n}"], cwd=case_dir)


def set_continue_run(case_dir: str, continue_run: bool) -> None:
    value = "TRUE" if continue_run else "FALSE"
    _run_checked(["./xmlchange", f"CONTINUE_RUN={value}"], cwd=case_dir)


def configure_case_for_orchestration(case_dir: str) -> None:
    """Force the XML settings this pipeline depends on onto an existing case.

    The bootstrap case is created outside this automation (by the manual
    `create_ENSO_controller_case.sh`, which sets `RESUBMIT=3` and never sets
    `DOUT_S`/`STOP_OPTION`/restart frequency). Left alone, CIME's own
    auto-resubmit would advance the case concurrently with the orchestrator's
    explicit resubmissions — two chains driving one case — and no June 1
    restart file would ever be written for the MCB branch to start from.

    CONTINUE_RUN is deliberately *not* touched here. An adopted case already
    has run history, so it must end up CONTINUE_RUN=TRUE (continue from the
    existing restart); setting it FALSE even transiently would leave the case
    configured to re-initialize and overwrite that history if anything
    between here and the submission failed. `resubmit_case` sets it TRUE
    right before submitting, which is the only value this pipeline ever wants.
    """
    _run_checked(["./xmlchange", "RESUBMIT=0"], cwd=case_dir)
    _run_checked(["./xmlchange", "STOP_OPTION=nmonths"], cwd=case_dir)
    _run_checked(["./xmlchange", "DOUT_S=TRUE"], cwd=case_dir)
    # Monthly restarts: the MCB branch case starts from the June 1 restart of
    # the RUNNING segment, which CIME only writes if asked for explicitly.
    _run_checked(["./xmlchange", "REST_OPTION=nmonths"], cwd=case_dir)
    _run_checked(["./xmlchange", "REST_N=1"], cwd=case_dir)


def resubmit_case(case_dir: str, stop_n: int) -> str:
    set_stop_n(case_dir, stop_n)
    # RESUBMIT=0 means CIME never advances CONTINUE_RUN itself. Without this,
    # every resubmission would re-run the same segment from its start date
    # instead of continuing forward.
    set_continue_run(case_dir, True)
    return submit_case(case_dir)


def flip_mcb_off(case_dir: str) -> None:
    nl_path = os.path.join(case_dir, "user_nl_cam")
    with open(nl_path) as f:
        lines = f.readlines()
    lines = [line for line in lines if not line.strip().startswith("MCB_seeding_amt")]
    lines.append("MCB_seeding_amt = 0\n")
    with open(nl_path, "w") as f:
        f.writelines(lines)
    _run_checked(["./preview_namelists"], cwd=case_dir)


def set_batch_mail(case_dir: str, email: str) -> None:
    # NOTE: BATCH_MAIL_TO/BATCH_MAIL_TYPE are the assumed CIME xmlchange IDs;
    # see the pre-flight checklist in docs/RUNBOOK.md for how to verify them
    # against a real case (they may be MAIL_USER/MAIL_TYPE on this CIME version).
    _run_checked(["./xmlchange", f"BATCH_MAIL_TO={email}"], cwd=case_dir)
    _run_checked(["./xmlchange", "BATCH_MAIL_TYPE=begin,end,fail"], cwd=case_dir)


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
                        email: str, resoln: str, compset: str, project: str,
                        srcdir: str, tagdir: str, scratchroot: str) -> str:
    env = {
        name: os.environ[name]
        for name in PASSTHROUGH_ENV_VARS
        if name in os.environ
    }
    env.update({
        "ENS": ens,
        "REFCASE": refcase,
        "BRANCH_NUMBER": str(branch_number),
        "STARTDATE": startdate,
        "STOP_N": str(stop_n),
        "MCB_ON": "1" if mcb_on else "0",
        "RESOLN": resoln,
        "COMPSET": compset,
        "PROJECT": project,
        "SRCDIR": srcdir,
        "TAGDIR": tagdir,
        "CASEROOT": caseroot,
        "SCRATCHROOT": scratchroot,
        "NOTIFICATION_EMAIL": email,
    })
    result = _run_checked(["bash", script_path], env=env)
    match = CASEDIR_RE.search(result.stdout)
    if not match:
        raise ValueError(f"create_branch_case.sh did not report a CASEDIR: {result.stdout!r}")
    return match.group(1)


def submit_orchestrator_self(wrapper_script: str, depend_job_id: str, state_file: str,
                              email: str, project: str = None, queue: str = None) -> str:
    cmd = ["qsub", "-W", f"depend=afterok:{depend_job_id}", "-m", "ae", "-M", email]
    # -A/-q override the static #PBS lines in orchestrator_wrapper.sh so the
    # account and queue stay tunable from enso_mcb_config.yaml.
    if project:
        cmd += ["-A", project]
    if queue:
        cmd += ["-q", queue]
    cmd += ["-v", f"STATE_FILE={state_file}", wrapper_script]
    result = _run_checked(cmd)
    return result.stdout.strip()
