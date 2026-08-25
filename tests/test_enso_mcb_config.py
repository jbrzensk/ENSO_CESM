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
    climatology_file: "/tmp/clim.nc"
    warming_threshold_c: 1.0
    end_year: 2100
    notification_email: "test@example.edu"
    python_exe: "python3"
    check_warming_script: "check_warming.py"
    create_branch_case_script: "create_branch_case.sh"
    orchestrator_wrapper_script: "orchestrator_wrapper.sh"
""")


def test_load_config_reads_all_required_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(VALID_CONFIG)

    config = load_config(str(config_path))

    assert config["ens"] == "1051"
    assert config["warming_threshold_c"] == 1.0
    assert config["end_year"] == 2100


def test_load_config_raises_on_missing_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('ens: "1051"\n')

    with pytest.raises(ValueError, match="missing required keys"):
        load_config(str(config_path))
