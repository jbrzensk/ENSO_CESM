import yaml

REQUIRED_KEYS = [
    "ens", "resoln", "compset", "project", "srcdir", "tagdir",
    "caseroot", "scratchroot", "climatology_sst_dir", "climatology_cache_dir",
    "climatology_forcing_variant", "build_climatology_script", "warming_threshold_c",
    "end_year", "notification_email", "python_exe", "check_warming_script",
    "create_branch_case_script", "orchestrator_wrapper_script",
    "orchestrator_queue",
]


def load_config(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(
            f"{path} did not parse to a YAML mapping (got {type(config).__name__}); "
            "an empty or malformed config file is the usual cause"
        )
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"{path} is missing required keys: {missing}")
    return config
