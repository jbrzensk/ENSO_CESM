import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest
import xarray as xr

from build_climatology import build_climatology, find_sst_files, file_year_range
from check_warming import compute_nino34_sst

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "build_climatology.py")

LAT = np.array([-10.0, -2.5, 2.5, 10.0])
LON = np.array([100.0, 200.0, 300.0])
LAT2D, LON2D = np.meshgrid(LAT, LON, indexing="ij")
INSIDE_BOX = (LAT2D >= -5.0) & (LAT2D <= 5.0) & (LON2D >= 190.0) & (LON2D <= 240.0)


def make_synthetic_sst_file(path, start_year, n_years, june_value_by_year,
                             outside_value=15.0, end_of_interval_stamps=True):
    """A synthetic CESM2-LE-style SST tseries file: monthly, noleap calendar,
    with a size-1 z_t dimension (matching the real ncdump the user provided).

    POP stamps a monthly mean's `time` value at the *end* of its averaging
    interval (a June mean's `time` can fall on July 1), not within the
    averaged month — `end_of_interval_stamps=True` (the default) reproduces
    that real convention, with a proper `time_bound` giving the true
    [start, end) interval, exactly like the real archive. This is what lets
    the tests actually catch a "picked May instead of June" bug; a fixture
    stamped at interval-start could not.
    """
    n_months = n_years * 12
    interval_starts = xr.date_range(start=f"{start_year}-01-01", periods=n_months,
                                     freq="MS", calendar="noleap", use_cftime=True)
    interval_ends = xr.date_range(start=f"{start_year}-02-01", periods=n_months,
                                   freq="MS", calendar="noleap", use_cftime=True)
    time_values = interval_ends if end_of_interval_stamps else interval_starts
    area = np.ones_like(LAT2D)

    sst = np.full((n_months, 1, *LAT2D.shape), outside_value)
    for i, interval_start in enumerate(interval_starts):
        if interval_start.month == 6:
            value = june_value_by_year.get(interval_start.year, outside_value)
            sst[i, 0] = np.where(INSIDE_BOX, value, outside_value)

    ds = xr.Dataset(
        {
            "SST": (("time", "z_t", "nlat", "nlon"), sst),
            "TAREA": (("nlat", "nlon"), area),
            "time_bound": (("time", "d2"), np.stack(
                [np.array(interval_starts), np.array(interval_ends)], axis=1,
            )),
        },
        coords={
            "time": time_values,
            "TLAT": (("nlat", "nlon"), LAT2D),
            "TLONG": (("nlat", "nlon"), LON2D),
        },
    )
    ds["time"].attrs["bounds"] = "time_bound"
    ds.to_netcdf(path)


def sst_filename(case_prefix, member, start_year, n_years):
    end_year = start_year + n_years - 1
    return f"b.e21.{case_prefix}.f09_g17.{member}.pop.h.SST.{start_year}01-{end_year}12.nc"


def test_file_year_range_parses_filename_suffix():
    assert file_year_range("b.e21.BHISTcmip6.f09_g17.LE2-1281.003.pop.h.SST.191001-191912.nc") == (1910, 1919)


def test_file_year_range_raises_on_unparseable_name():
    with pytest.raises(ValueError, match="could not parse"):
        file_year_range("not_a_tseries_file.nc")


def test_find_sst_files_matches_only_the_requested_member(tmp_path):
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", "LE2-1011.001", 2015, 10),
                             2015, 10, {})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", "LE2-1051.001", 2015, 10),
                             2015, 10, {})

    found = find_sst_files(str(tmp_path), "LE2-1011.001", "smbb", 2015, 2024)

    assert len(found) == 1
    assert "LE2-1011.001" in found[0]


def test_find_sst_files_excludes_files_entirely_outside_the_window(tmp_path):
    make_synthetic_sst_file(tmp_path / sst_filename("BHISTsmbb", "LE2-1011.001", 2000, 10),
                             2000, 10, {})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", "LE2-1011.001", 2015, 10),
                             2015, 10, {})

    found = find_sst_files(str(tmp_path), "LE2-1011.001", "smbb", 2015, 2024)

    assert len(found) == 1
    assert "201501" in found[0]


def test_find_sst_files_excludes_a_different_forcing_variant(tmp_path):
    member = "LE2-1011.001"
    # Same member, same years, but the "cmip6" forcing ensemble rather than
    # this experiment's "smbb" one -- must not be picked up.
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370cmip6", member, 2015, 30),
                             2015, 30, {})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 30),
                             2015, 30, {})

    found = find_sst_files(str(tmp_path), member, "smbb", 2015, 2044)

    assert len(found) == 1
    assert "smbb" in found[0]
    assert "cmip6" not in found[0]


def test_build_climatology_averages_30_junes_across_three_files(tmp_path):
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 10),
                             2015, 10, {y: 20.0 for y in range(2015, 2025)})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2025, 10),
                             2025, 10, {y: 22.0 for y in range(2025, 2035)})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2035, 10),
                             2035, 10, {y: 24.0 for y in range(2035, 2045)})
    output_path = tmp_path / "climatology.nc"

    # Target year 2045 -> baseline [2015, 2044], 30 years across the 3 files.
    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    with xr.open_dataset(output_path) as ds:
        assert "SST" in ds
        assert "TAREA" in ds
        assert "TLAT" in ds
        assert "TLONG" in ds
        inside_value = float(ds["SST"].values[INSIDE_BOX][0])
        outside_value = float(ds["SST"].values[~INSIDE_BOX][0])

    # (20*10 + 22*10 + 24*10) / 30 = 22.0
    assert inside_value == pytest.approx(22.0)
    assert outside_value == pytest.approx(15.0)


def test_build_climatology_selects_june_not_may_under_end_of_interval_stamps(tmp_path):
    """Regression test for the POP end-of-interval time-stamp convention:
    a naive `time.dt.month == 6` filter on the raw (undecoded-via-bounds)
    time coordinate would select May's data instead of June's."""
    member = "LE2-1011.001"

    def make_file_with_distinct_months(path, start_year, n_years):
        n_months = n_years * 12
        interval_starts = xr.date_range(start=f"{start_year}-01-01", periods=n_months,
                                         freq="MS", calendar="noleap", use_cftime=True)
        interval_ends = xr.date_range(start=f"{start_year}-02-01", periods=n_months,
                                       freq="MS", calendar="noleap", use_cftime=True)
        area = np.ones_like(LAT2D)
        sst = np.full((n_months, 1, *LAT2D.shape), 15.0)
        for i, interval_start in enumerate(interval_starts):
            if interval_start.month == 5:
                sst[i, 0] = np.where(INSIDE_BOX, 99.0, 15.0)  # May: sentinel wrong value
            elif interval_start.month == 6:
                sst[i, 0] = np.where(INSIDE_BOX, 26.7, 15.0)  # June: correct value
        ds = xr.Dataset(
            {
                "SST": (("time", "z_t", "nlat", "nlon"), sst),
                "TAREA": (("nlat", "nlon"), area),
                "time_bound": (("time", "d2"), np.stack(
                    [np.array(interval_starts), np.array(interval_ends)], axis=1,
                )),
            },
            coords={
                "time": interval_ends,  # end-of-interval stamping, like real POP output
                "TLAT": (("nlat", "nlon"), LAT2D),
                "TLONG": (("nlat", "nlon"), LON2D),
            },
        )
        ds["time"].attrs["bounds"] = "time_bound"
        ds.to_netcdf(path)

    make_file_with_distinct_months(
        tmp_path / sst_filename("BSSP370smbb", member, 2015, 30), 2015, 30,
    )
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    with xr.open_dataset(output_path) as ds:
        inside_value = float(ds["SST"].values[INSIDE_BOX][0])

    assert inside_value == pytest.approx(26.7)


def test_build_climatology_falls_back_to_raw_time_without_time_bound(tmp_path):
    """Without a bounds variable, the raw (start-of-interval-stamped, in
    this fixture) time coordinate is used directly."""
    member = "LE2-1011.001"
    path = tmp_path / sst_filename("BSSP370smbb", member, 2015, 30)
    n_months = 30 * 12
    time = xr.date_range(start="2015-01-01", periods=n_months,
                          freq="MS", calendar="noleap", use_cftime=True)
    area = np.ones_like(LAT2D)
    sst = np.full((n_months, 1, *LAT2D.shape), 15.0)
    for i, t in enumerate(time):
        if t.month == 6:
            sst[i, 0] = np.where(INSIDE_BOX, 21.5, 15.0)
    ds = xr.Dataset(
        {
            "SST": (("time", "z_t", "nlat", "nlon"), sst),
            "TAREA": (("nlat", "nlon"), area),
        },
        coords={
            "time": time,
            "TLAT": (("nlat", "nlon"), LAT2D),
            "TLONG": (("nlat", "nlon"), LON2D),
        },
    )
    ds.to_netcdf(path)
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    with xr.open_dataset(output_path) as ds:
        inside_value = float(ds["SST"].values[INSIDE_BOX][0])
    assert inside_value == pytest.approx(21.5)


def test_build_climatology_raises_when_no_files_found_for_member(tmp_path):
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", "LE2-1051.001", 2015, 30),
                             2015, 30, {})

    with pytest.raises(ValueError, match="no SST tseries files found"):
        build_climatology(str(tmp_path), "LE2-1011.001", "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_raises_when_years_are_missing_from_the_window(tmp_path):
    member = "LE2-1011.001"
    # Only covers 2015-2034 (20 years); baseline for year 2045 needs 2015-2044.
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 20),
                             2015, 20, {y: 20.0 for y in range(2015, 2035)})

    with pytest.raises(ValueError, match="missing June SST data"):
        build_climatology(str(tmp_path), member, "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_raises_on_duplicate_june_from_overlapping_files(tmp_path):
    member = "LE2-1011.001"
    # Two files whose year ranges overlap at 2020-2024 -- both would supply
    # a June 2022 value.
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 10),
                             2015, 10, {y: 20.0 for y in range(2015, 2025)})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2020, 25),
                             2020, 25, {y: 20.0 for y in range(2020, 2045)})

    with pytest.raises(ValueError, match="duplicate June"):
        build_climatology(str(tmp_path), member, "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_output_is_readable_by_check_warming(tmp_path):
    """End-to-end structural check: check_warming.py itself was not changed,
    so its compute_nino34_sst() must be able to read build_climatology's
    output directly, with no leftover z_t dimension or shape mismatch."""
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 30),
                             2015, 30, {y: 23.25 for y in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert compute_nino34_sst(str(output_path)) == pytest.approx(23.25)


def test_build_climatology_cli_writes_output_and_prints_json(tmp_path):
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 30),
                             2015, 30, {y: 21.0 for y in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--sst-dir", str(tmp_path), "--member", member,
         "--year", "2045", "--output", str(output_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["output"] == str(output_path)
    assert output_path.exists()


def test_build_climatology_cli_forcing_variant_flag_defaults_to_smbb(tmp_path):
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370cmip6", member, 2015, 30),
                             2015, 30, {y: 20.0 for y in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--sst-dir", str(tmp_path), "--member", member,
         "--year", "2045", "--output", str(output_path)],
        capture_output=True, text=True,
    )

    # Default variant is "smbb"; only a "cmip6" file exists, so this must
    # fail loudly rather than silently using the wrong forcing variant.
    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert "no SST tseries files found" in payload["error"]


def test_build_climatology_cli_fails_clearly_when_no_files_found(tmp_path):
    output_path = tmp_path / "climatology.nc"

    result = subprocess.run(
        [sys.executable, SCRIPT,
         "--sst-dir", str(tmp_path), "--member", "LE2-1011.001",
         "--year", "2045", "--output", str(output_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert "error" in payload
    assert not output_path.exists()


def test_build_climatology_does_not_leave_a_truncated_file_key(tmp_path):
    """The atomic tmp-then-rename write must not leave a stray .tmp file."""
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 30),
                             2015, 30, {y: 21.0 for y in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert output_path.exists()
    assert not (tmp_path / "climatology.nc.tmp").exists()
