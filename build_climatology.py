#!/usr/bin/env python3
"""Builds a rolling climatological DJF (Dec-Jan-Feb) Nino3.4 SST field for a
CESM2-LE ensemble member from the archive's monthly SST tseries files, and
writes it as a NetCDF file with the same SST/TAREA/TLAT/TLONG shape
check_warming.py expects.

DJF season Y is December of year Y plus January and February of year Y+1.
The climatology for season Y is the mean over the BASELINE_YEARS seasons
immediately preceding it, [Y - BASELINE_YEARS, Y - 1], i.e. every monthly
field from December (Y - BASELINE_YEARS) through February Y, each month
weighted equally.
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import xarray as xr

BASELINE_YEARS = 30
FILENAME_RANGE_RE = re.compile(r"\.(\d{6})-(\d{6})\.nc$")

# (offset from the season year, calendar month) for each month of DJF season Y.
DJF_MONTHS = ((0, 12), (1, 1), (1, 2))


def season_months(season_year: int) -> list:
    """The (year, month) pairs making up DJF season `season_year`."""
    return [(season_year + offset, month) for offset, month in DJF_MONTHS]


def file_year_range(path: str) -> tuple:
    match = FILENAME_RANGE_RE.search(path)
    if not match:
        raise ValueError(f"could not parse a YYYYMM-YYYYMM date range from filename: {path}")
    start_year = int(match.group(1)[:4])
    end_year = int(match.group(2)[:4])
    return start_year, end_year


def find_sst_files(sst_dir: str, member: str, variant: str,
                    start_year: int, end_year: int) -> list:
    """Find this member's SST tseries files overlapping [start_year, end_year].

    `variant` (e.g. "smbb") narrows the case-name prefix so this never
    silently pulls data from a different CESM2-LE forcing variant (the
    archive holds both a "cmip6" and an "smbb" ensemble for the same
    member numbers) — this experiment's own scripts are all built on the
    "smbb" variant (see create_ENSO_controller_case.sh's refcase), so
    matching the wrong one would mean either a hard failure (both present,
    "duplicate" month errors) or a silently-wrong background trajectory
    (only the other one present).
    """
    pattern = os.path.join(sst_dir, f"*{variant}*.{member}.pop.h.SST.*.nc")
    candidates = sorted(glob.glob(pattern))
    selected = []
    for path in candidates:
        file_start, file_end = file_year_range(path)
        if file_end >= start_year and file_start <= end_year:
            selected.append(path)
    return selected


def nominal_year_month(ds: xr.Dataset, index: int) -> tuple:
    """The calendar (year, month) a time step's monthly mean represents.

    POP timestamps a monthly mean at the *end* of its averaging interval
    (e.g. a November mean's raw `time` value can fall on December 1), not
    within the averaged month itself — using the raw `time` coordinate's
    month directly would silently select the wrong month. `time_bound` (CF
    `bounds` attribute on `time`) gives the true [start, end) interval;
    its start always falls exactly on the 1st of the actual averaged
    month regardless of the `time` stamp convention. Fall back to the raw
    `time` value only if `time_bound` is absent — unverified against the
    real archive; see the pre-flight checklist in docs/RUNBOOK.md.
    """
    if "time_bound" in ds:
        interval_start = ds["time_bound"].values[index, 0]
        return interval_start.year, interval_start.month
    t = ds["time"].values[index]
    return t.year, t.month


def build_climatology(sst_dir: str, member: str, variant: str, year: int,
                       output_path: str) -> None:
    first_season = year - BASELINE_YEARS
    last_season = year - 1
    expected_months = {
        year_month
        for season in range(first_season, last_season + 1)
        for year_month in season_months(season)
    }

    # Seasons [first_season, last_season] span December first_season through
    # February `year`.
    files = find_sst_files(sst_dir, member, variant, first_season, year)
    if not files:
        raise ValueError(
            f"no SST tseries files found for member {member} (variant {variant}) "
            f"covering {first_season}-{year} in {sst_dir}"
        )

    time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)

    sst_by_month = {}
    area = lat = lon = None
    for path in files:
        with xr.open_dataset(path, decode_times=time_coder) as ds:
            sst = ds["SST"]
            if "z_t" in sst.dims:
                sst = sst.isel(z_t=0)
            for i in range(ds.sizes["time"]):
                year_month = nominal_year_month(ds, i)
                if year_month not in expected_months:
                    continue
                if year_month in sst_by_month:
                    raise ValueError(
                        f"duplicate SST value for {year_month[0]:04d}-{year_month[1]:02d} "
                        f"across SST files for member {member} — overlapping tseries "
                        f"files in {sst_dir}?"
                    )
                sst_by_month[year_month] = sst.isel(time=i).values.copy()
            if area is None:
                area = ds["TAREA"].values.copy()
                lat = ds["TLAT"].values.copy()
                lon = ds["TLONG"].values.copy()

    missing = sorted(expected_months - sst_by_month.keys())
    if missing:
        missing_labels = [f"{y:04d}-{m:02d}" for y, m in missing]
        raise ValueError(
            f"missing DJF SST data for months {missing_labels} (member {member}, "
            f"baseline DJF seasons {first_season}-{last_season}, searched "
            f"{len(files)} file(s) in {sst_dir})"
        )

    stacked = np.stack([sst_by_month[ym] for ym in sorted(sst_by_month)], axis=0)
    climatological_sst = stacked.mean(axis=0)

    out = xr.Dataset(
        {
            "SST": (("nlat", "nlon"), climatological_sst),
            "TAREA": (("nlat", "nlon"), area),
        },
        coords={
            "TLAT": (("nlat", "nlon"), lat),
            "TLONG": (("nlat", "nlon"), lon),
        },
    )
    # Write to a sibling temp file and rename into place atomically, so a job
    # killed mid-write (PBS walltime, node failure) never leaves a truncated
    # file at output_path for a later cycle to pick up as if it were valid.
    tmp_path = output_path + ".tmp"
    out.to_netcdf(tmp_path)
    os.replace(tmp_path, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sst-dir", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--forcing-variant", default="smbb",
                         help="substring narrowing the case-name prefix, e.g. "
                              "'smbb' vs 'cmip6' (default: smbb)")
    parser.add_argument("--year", type=int, required=True,
                         help="DJF season year Y (Dec Y, Jan-Feb Y+1) to build the "
                              "climatology for")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        build_climatology(args.sst_dir, args.member, args.forcing_variant,
                           args.year, args.output)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"output": args.output}))


if __name__ == "__main__":
    main()
