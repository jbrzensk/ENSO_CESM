import pathlib
import textwrap

import pytest

from enso_mcb_config import load_config


VALID_CONFIG = textwrap.dedent("""\
    ens: "1051"
    resoln: "f09_g17"
    compset: "BSSP370smbb"
    project: "UCSD0083"
    srcdir: "/tmp/srcdir"
    tagdir: "/tmp/tagdir"
    caseroot: "/tmp/caseroot"
    scratchroot: "/tmp/scratchroot"
    climatology_sst_dir: "/tmp/sst_tseries"
    climatology_cache_dir: "/tmp/climatology_cache"
    build_climatology_script: "build_climatology.py"
    warming_threshold_c: 1.0
    end_year: 2100
    notification_email: "test@example.edu"
    python_exe: "python3"
    check_warming_script: "check_warming.py"
    create_branch_case_script: "create_branch_case.sh"
    orchestrator_wrapper_script: "orchestrator_wrapper.sh"
    orchestrator_queue: "main"
""")


def test_load_config_reads_all_required_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG)

    config = load_config(str(config_path))

    assert config["ens"] == "1051"
    assert config["warming_threshold_c"] == 1.0
    assert config["end_year"] == 2100
    assert config["orchestrator_queue"] == "main"


def test_shipped_config_file_has_every_required_key():
    repo_config = pathlib.Path(__file__).resolve().parent.parent / "enso_mcb_config.yaml"

    config = load_config(str(repo_config))

    assert config["orchestrator_queue"]


def test_load_config_raises_on_missing_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('ens: "1051"\n')

    with pytest.raises(ValueError, match="missing required keys"):
        load_config(str(config_path))


def test_load_config_raises_clear_error_on_empty_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("")

    with pytest.raises(ValueError, match="did not parse to a YAML mapping"):
        load_config(str(config_path))


def test_load_config_raises_clear_error_when_yaml_is_not_a_mapping(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- just\n- a\n- list\n")

    with pytest.raises(ValueError, match="did not parse to a YAML mapping"):
        load_config(str(config_path))
