import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest
import xarray as xr

from build_climatology import build_climatology, find_sst_files, file_year_range, season_months
from check_warming import compute_nino34_sst

SCRIPT = str(pathlib.Path(__file__).resolve().parent.parent / "build_climatology.py")

LAT = np.array([-10.0, -2.5, 2.5, 10.0])
LON = np.array([100.0, 200.0, 300.0])
LAT2D, LON2D = np.meshgrid(LAT, LON, indexing="ij")
INSIDE_BOX = (LAT2D >= -5.0) & (LAT2D <= 5.0) & (LON2D >= 190.0) & (LON2D <= 240.0)


def djf_season_of(year, month):
    """The DJF season year a calendar month belongs to, or None."""
    if month == 12:
        return year
    if month in (1, 2):
        return year - 1
    return None


def write_sst_file(path, start_year, n_years, value_for_month, outside_value=15.0,
                   end_of_interval_stamps=True, with_time_bound=True):
    """A synthetic CESM2-LE-style SST tseries file: monthly, noleap calendar,
    with a size-1 z_t dimension (matching the real archive).

    `value_for_month(year, month)` gives the Nino3.4-box value for each
    month (None -> `outside_value`).

    POP stamps a monthly mean's `time` value at the *end* of its averaging
    interval (a November mean's `time` can fall on December 1), not within
    the averaged month. `end_of_interval_stamps=True` (the default)
    reproduces that real convention, with a proper `time_bound` giving the
    true [start, end) interval. This is what lets the tests catch a
    "picked November instead of December" bug.
    """
    n_months = n_years * 12
    interval_starts = xr.date_range(start=f"{start_year}-01-01", periods=n_months,
                                     freq="MS", calendar="noleap", use_cftime=True)
    interval_ends = xr.date_range(start=f"{start_year}-02-01", periods=n_months,
                                   freq="MS", calendar="noleap", use_cftime=True)
    time_values = interval_ends if end_of_interval_stamps else interval_starts

    sst = np.full((n_months, 1, *LAT2D.shape), outside_value)
    for i, start in enumerate(interval_starts):
        value = value_for_month(start.year, start.month)
        if value is not None:
            sst[i, 0] = np.where(INSIDE_BOX, value, outside_value)

    data_vars = {
        "SST": (("time", "z_t", "nlat", "nlon"), sst),
        "TAREA": (("nlat", "nlon"), np.ones_like(LAT2D)),
    }
    if with_time_bound:
        data_vars["time_bound"] = (("time", "d2"), np.stack(
            [np.array(interval_starts), np.array(interval_ends)], axis=1,
        ))
    ds = xr.Dataset(
        data_vars,
        coords={
            "time": time_values,
            "TLAT": (("nlat", "nlon"), LAT2D),
            "TLONG": (("nlat", "nlon"), LON2D),
        },
    )
    if with_time_bound:
        ds["time"].attrs["bounds"] = "time_bound"
    ds.to_netcdf(path)


def make_synthetic_sst_file(path, start_year, n_years, djf_value_by_season, **kwargs):
    """Every month of DJF season k gets djf_value_by_season[k]; other months
    get the outside value."""
    def value_for_month(year, month):
        season = djf_season_of(year, month)
        return djf_value_by_season.get(season) if season is not None else None

    write_sst_file(path, start_year, n_years, value_for_month, **kwargs)


def sst_filename(case_prefix, member, start_year, n_years):
    end_year = start_year + n_years - 1
    return f"b.e21.{case_prefix}.f09_g17.{member}.pop.h.SST.{start_year}01-{end_year}12.nc"


def test_season_months_are_december_then_next_january_and_february():
    assert season_months(2032) == [(2032, 12), (2033, 1), (2033, 2)]


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


SEASON_VALUES_2015_2044 = {
    **{k: 20.0 for k in range(2015, 2025)},
    **{k: 22.0 for k in range(2025, 2035)},
    **{k: 24.0 for k in range(2035, 2045)},
}


def test_build_climatology_averages_30_djf_seasons_across_files(tmp_path):
    """Season 2045's baseline is DJF 2015..2044: Dec 2015 through Feb 2045.
    Seasons straddle file boundaries (e.g. Dec 2024 / Jan-Feb 2025)."""
    member = "LE2-1011.001"
    for start, n in ((2015, 10), (2025, 10), (2035, 11)):
        make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, start, n),
                                 start, n, SEASON_VALUES_2015_2044)
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    with xr.open_dataset(output_path) as ds:
        assert {"SST", "TAREA", "TLAT", "TLONG"} <= set(ds.variables)
        inside_value = float(ds["SST"].values[INSIDE_BOX][0])
        outside_value = float(ds["SST"].values[~INSIDE_BOX][0])

    # (20*10 + 22*10 + 24*10) / 30 = 22.0
    assert inside_value == pytest.approx(22.0)
    assert outside_value == pytest.approx(15.0)


def test_build_climatology_excludes_the_season_being_checked_and_older_ones(tmp_path):
    """Only DJF 2015..2044 count for season 2045: the Jan-Feb 2015 months
    (season 2014) and Dec 2045 (season 2045 itself) must be ignored."""
    member = "LE2-1011.001"
    values = {k: 25.0 for k in range(2015, 2045)}
    values[2014] = 99.0
    values[2045] = 99.0
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31),
                             2015, 31, values)
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert compute_nino34_sst(str(output_path)) == pytest.approx(25.0)


def test_build_climatology_selects_djf_not_ndj_under_end_of_interval_stamps(tmp_path):
    """Regression test for the POP end-of-interval time-stamp convention: a
    naive filter on the raw time coordinate would pick the November mean as
    December, the December mean as January, and so on."""
    member = "LE2-1011.001"

    def value_for_month(year, month):
        if month == 11:
            return 99.0  # sentinel: must never be used
        if month in (12, 1, 2):
            return 26.7
        return None

    write_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31), 2015, 31,
                   value_for_month)
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert compute_nino34_sst(str(output_path)) == pytest.approx(26.7)


def test_build_climatology_falls_back_to_raw_time_without_time_bound(tmp_path):
    """Without a bounds variable, the raw (start-of-interval-stamped, in
    this fixture) time coordinate is used directly."""
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31),
                             2015, 31, {k: 21.5 for k in range(2015, 2045)},
                             end_of_interval_stamps=False, with_time_bound=False)
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert compute_nino34_sst(str(output_path)) == pytest.approx(21.5)


def test_build_climatology_raises_when_no_files_found_for_member(tmp_path):
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", "LE2-1051.001", 2015, 31),
                             2015, 31, {})

    with pytest.raises(ValueError, match="no SST tseries files found"):
        build_climatology(str(tmp_path), "LE2-1011.001", "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_raises_when_months_are_missing_from_the_window(tmp_path):
    member = "LE2-1011.001"
    # Covers 2015-2044, so Jan-Feb 2045 (the end of season 2044) is missing.
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 30),
                             2015, 30, {k: 20.0 for k in range(2015, 2045)})

    with pytest.raises(ValueError, match=r"missing DJF SST data.*2045-01.*2045-02"):
        build_climatology(str(tmp_path), member, "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_raises_on_duplicate_month_from_overlapping_files(tmp_path):
    member = "LE2-1011.001"
    # Two files whose year ranges overlap at 2020-2024.
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 10),
                             2015, 10, {})
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2020, 26),
                             2020, 26, {})

    with pytest.raises(ValueError, match="duplicate SST value"):
        build_climatology(str(tmp_path), member, "smbb", 2045, str(tmp_path / "out.nc"))


def test_build_climatology_output_is_readable_by_check_warming(tmp_path):
    """check_warming.py's compute_nino34_sst() must read build_climatology's
    output directly, with no leftover z_t dimension or shape mismatch."""
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31),
                             2015, 31, {k: 23.25 for k in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert compute_nino34_sst(str(output_path)) == pytest.approx(23.25)


def test_build_climatology_cli_writes_output_and_prints_json(tmp_path):
    member = "LE2-1011.001"
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31),
                             2015, 31, {k: 21.0 for k in range(2015, 2045)})
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
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370cmip6", member, 2015, 31),
                             2015, 31, {k: 20.0 for k in range(2015, 2045)})
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
    make_synthetic_sst_file(tmp_path / sst_filename("BSSP370smbb", member, 2015, 31),
                             2015, 31, {k: 21.0 for k in range(2015, 2045)})
    output_path = tmp_path / "climatology.nc"

    build_climatology(str(tmp_path), member, "smbb", 2045, str(output_path))

    assert output_path.exists()
    assert not (tmp_path / "climatology.nc.tmp").exists()
