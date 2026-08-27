#!/usr/bin/env python3
"""Builds a rolling climatological June Nino3.4 SST field for a CESM2-LE
ensemble member from the archive's monthly SST tseries files, and writes it
as a NetCDF file with the same SST/TAREA/TLAT/TLONG shape check_warming.py
already expects (so check_warming.py itself needs no changes to consume it).

The climatology for simulation year Y is the mean of June SST over the
BASELINE_YEARS years immediately preceding Y: [Y - BASELINE_YEARS, Y - 1].
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
    "duplicate June" errors) or a silently-wrong background trajectory
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
    (e.g. a June mean's raw `time` value can fall on July 1), not within
    the averaged month itself — using the raw `time` coordinate's month
    directly would silently select the wrong month. `time_bound` (CF
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
    start_year = year - BASELINE_YEARS
    end_year = year - 1
    expected_years = set(range(start_year, end_year + 1))

    files = find_sst_files(sst_dir, member, variant, start_year, end_year)
    if not files:
        raise ValueError(
            f"no SST tseries files found for member {member} (variant {variant}) "
            f"covering {start_year}-{end_year} in {sst_dir}"
        )

    time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)

    june_by_year = {}
    area = lat = lon = None
    for path in files:
        with xr.open_dataset(path, decode_times=time_coder) as ds:
            sst = ds["SST"]
            if "z_t" in sst.dims:
                sst = sst.isel(z_t=0)
            for i in range(ds.sizes["time"]):
                nominal_year, nominal_month = nominal_year_month(ds, i)
                if nominal_month != 6 or nominal_year not in expected_years:
                    continue
                if nominal_year in june_by_year:
                    raise ValueError(
                        f"duplicate June {nominal_year} value found across SST files "
                        f"for member {member} — overlapping tseries files in {sst_dir}?"
                    )
                june_by_year[nominal_year] = sst.isel(time=i).values.copy()
            if area is None:
                area = ds["TAREA"].values.copy()
                lat = ds["TLAT"].values.copy()
                lon = ds["TLONG"].values.copy()

    missing = sorted(expected_years - june_by_year.keys())
    if missing:
        raise ValueError(
            f"missing June SST data for years {missing} (member {member}, "
            f"baseline {start_year}-{end_year}, searched {len(files)} file(s) in {sst_dir})"
        )

    stacked = np.stack([june_by_year[y] for y in sorted(june_by_year)], axis=0)
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
    parser.add_argument("--year", type=int, required=True)
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
