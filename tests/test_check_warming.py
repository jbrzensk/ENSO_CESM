import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest
import xarray as xr

from check_warming import compute_anomaly, compute_nino34_sst, is_warming

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "check_warming.py")


def make_synthetic_history_file(path, sst_value_inside_box, sst_value_outside_box):
    lat = np.array([-10.0, -2.5, 2.5, 10.0])
    lon = np.array([100.0, 200.0, 300.0])
    lat2d, lon2d = np.meshgrid(lat, lon, indexing="ij")
    inside = (lat2d >= -5.0) & (lat2d <= 5.0) & (lon2d >= 190.0) & (lon2d <= 240.0)
    sst = np.where(inside, sst_value_inside_box, sst_value_outside_box)
    area = np.ones_like(sst)
    ds = xr.Dataset(
        {
            "SST": (("nlat", "nlon"), sst),
            "TAREA": (("nlat", "nlon"), area),
        },
        coords={
            "TLAT": (("nlat", "nlon"), lat2d),
            "TLONG": (("nlat", "nlon"), lon2d),
        },
    )
    ds.to_netcdf(path)


def test_compute_nino34_sst_averages_only_inside_the_box(tmp_path):
    history_file = tmp_path / "history.nc"
    make_synthetic_history_file(history_file, sst_value_inside_box=28.0, sst_value_outside_box=15.0)

    result = compute_nino34_sst(str(history_file))

    assert result == pytest.approx(28.0)


def test_compute_anomaly_is_difference_from_climatology():
    assert compute_anomaly(sst_value=29.0, climatology_value=27.5) == pytest.approx(1.5)


def test_is_warming_true_at_or_above_threshold():
    assert is_warming(anomaly_c=1.0, threshold_c=1.0) is True
    assert is_warming(anomaly_c=1.5, threshold_c=1.0) is True


def test_is_warming_false_below_threshold():
    assert is_warming(anomaly_c=0.9, threshold_c=1.0) is False


def test_cli_prints_warming_json(tmp_path):
    history_file = tmp_path / "history.nc"
    climatology_file = tmp_path / "clim.nc"
    make_synthetic_history_file(history_file, sst_value_inside_box=29.0, sst_value_outside_box=15.0)
    make_synthetic_history_file(climatology_file, sst_value_inside_box=27.5, sst_value_outside_box=15.0)

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--history-file", str(history_file),
         "--climatology-file", str(climatology_file),
         "--year", "2054", "--threshold", "1.0"],
        capture_output=True, text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["year"] == 2054
    assert payload["anomaly_c"] == pytest.approx(1.5, abs=0.01)
    assert payload["warming"] is True


def test_cli_fails_clearly_on_missing_history_file(tmp_path):
    climatology_file = tmp_path / "clim.nc"
    make_synthetic_history_file(climatology_file, sst_value_inside_box=27.5, sst_value_outside_box=15.0)

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--history-file", str(tmp_path / "does_not_exist.nc"),
         "--climatology-file", str(climatology_file),
         "--year", "2054"],
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert "error" in payload
