import os
import pathlib
import stat
import subprocess

import pytest

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "orchestrator_wrapper.sh")


@pytest.fixture
def fake_python(tmp_path):
    """An executable standing in for the ENSO_Control interpreter.

    It records the PATH it was started with and its arguments, so a test
    can see exactly what environment the orchestrator (and therefore every
    CIME subprocess it spawns) would inherit.
    """
    record = tmp_path / "record.txt"
    exe = tmp_path / "envbin" / "python3"
    exe.parent.mkdir()
    exe.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "PATH=%s\\n" "$PATH" > "{record}"\n'
        f'printf "ARGS=%s\\n" "$*" >> "{record}"\n'
        f'printf "PWD=%s\\n" "$PWD" >> "{record}"\n'
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe, record


def run_wrapper(env_overrides):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    env.update(env_overrides)
    return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)


def read_record(record):
    return dict(line.split("=", 1) for line in record.read_text().splitlines())


def test_runs_orchestrator_with_configured_interpreter_from_workdir(fake_python, tmp_path):
    exe, record = fake_python

    result = run_wrapper({
        "PBS_O_WORKDIR": str(tmp_path), "STATE_FILE": "/glade/state.json",
        "ENSO_PYTHON": str(exe),
    })

    assert result.returncode == 0, result.stderr
    got = read_record(record)
    assert got["ARGS"] == ("enso_mcb_orchestrator.py --state-file /glade/state.json "
                           "--config-file enso_mcb_config.yaml")
    assert got["PWD"] == str(tmp_path)


def test_does_not_put_the_conda_environment_on_path(fake_python, tmp_path):
    """CIME's scripts run under whatever `python` is first on PATH, and
    CESM 2.1.5's CIME imports `imp`, which Python 3.12 removed. If the
    wrapper activated ENSO_Control, every xmlchange/case.submit/case.build
    the orchestrator spawns would run under that environment's 3.12 and
    fail with `No module named 'imp'`. PATH must reach the orchestrator
    unchanged."""
    exe, record = fake_python
    original_path = os.environ["PATH"]

    result = run_wrapper({
        "PBS_O_WORKDIR": str(tmp_path), "STATE_FILE": "/glade/state.json",
        "ENSO_PYTHON": str(exe),
    })

    assert result.returncode == 0, result.stderr
    got = read_record(record)
    assert got["PATH"] == original_path
    assert str(exe.parent) not in got["PATH"].split(":")


def test_fails_clearly_when_interpreter_missing(tmp_path):
    missing = tmp_path / "nope" / "python3"

    result = run_wrapper({
        "PBS_O_WORKDIR": str(tmp_path), "STATE_FILE": "/glade/state.json",
        "ENSO_PYTHON": str(missing),
    })

    assert result.returncode != 0
    assert str(missing) in result.stderr


def test_fails_clearly_when_state_file_unset(fake_python, tmp_path):
    exe, _ = fake_python

    result = run_wrapper({"PBS_O_WORKDIR": str(tmp_path), "ENSO_PYTHON": str(exe)})

    assert result.returncode != 0
    assert "STATE_FILE" in result.stderr
