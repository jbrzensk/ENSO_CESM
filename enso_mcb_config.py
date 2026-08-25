import yaml

REQUIRED_KEYS = [
    "ens", "resoln", "compset", "project", "srcdir", "tagdir",
    "caseroot", "scratchroot", "climatology_file", "warming_threshold_c",
    "end_year", "notification_email", "python_exe", "check_warming_script",
    "create_branch_case_script", "orchestrator_wrapper_script",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"{path} is missing required keys: {missing}")
    return config
