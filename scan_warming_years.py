#!/usr/bin/env python3
"""Scan a CESM2-LE member's SST archive for June Nino3.4 warming years.

This pre-flight tool uses the same climatology and anomaly logic as
``build_climatology.py`` and ``check_warming.py`` to preview a member's
internal ENSO cycle before selecting a ``--start-year`` or hybrid-case
restart date.

Inputs
------
sst_dir : str
    Directory containing the CESM2-LE SST archive.
member : str
    CESM2-LE ensemble member identifier.
variant : str
    Forcing variant, such as ``"smbb"``.
start_year, end_year : int
    Inclusive range of years to scan.
threshold : float
    Nino3.4 anomaly threshold in degrees Celsius.
cache_dir : str
    Directory used to cache climatology files.

Outputs
-------
list of dict
    Results containing each year and its anomaly, warming flag, or error.

Author
------
Jared Brzenski, Sept 2026

Example
-------
Command line usage::

    python scan_warming_years.py --sst-dir /path/to/sst \\
        --member LE2-1091.005 --start-year 1950 --end-year 2000
        --threshold 1.5
"""
import argparse
import json
import os
import tempfile

import xarray as xr

# Use existing build_climatology scripts
from build_climatology import build_climatology, find_sst_files, nominal_year_month
from check_warming import compute_anomaly, compute_nino34_sst, is_warming


def extract_june_file(sst_dir: str, member: str, variant: str, year: int, output_path: str) -> None:
    """Write `year`'s actual June SST field to output_path, in the same
    SST/TAREA/TLAT/TLONG shape build_climatology.py's output uses, so
    check_warming.compute_nino34_sst() can be reused unchanged."""
    time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)
    for path in find_sst_files(sst_dir, member, variant, year, year):
        with xr.open_dataset(path, decode_times=time_coder) as ds:
            for i in range(ds.sizes["time"]):
                nominal_year, nominal_month = nominal_year_month(ds, i)
                if nominal_year != year or nominal_month != 6:
                    continue
                sst = ds["SST"]
                if "z_t" in sst.dims:
                    sst = sst.isel(z_t=0)
                out = xr.Dataset(
                    {
                        "SST": (("nlat", "nlon"), sst.isel(time=i).values.copy()),
                        "TAREA": (("nlat", "nlon"), ds["TAREA"].values.copy()),
                    },
                    coords={
                        "TLAT": (("nlat", "nlon"), ds["TLAT"].values.copy()),
                        "TLONG": (("nlat", "nlon"), ds["TLONG"].values.copy()),
                    },
                )
                out.to_netcdf(output_path)
                return
    raise ValueError(f"no June {year} SST found for member {member} (variant {variant}) in {sst_dir}")


def scan(sst_dir: str, member: str, variant: str, start_year: int, end_year: int,
         threshold: float, cache_dir: str) -> list:
    os.makedirs(cache_dir, exist_ok=True)
    results = []
    for year in range(start_year, end_year + 1):
        climatology_path = os.path.join(cache_dir, f"climatology_{variant}_{member}_{year}.nc")
        actual_path = os.path.join(cache_dir, f"actual_june_{variant}_{member}_{year}.nc")
        try:
            if not os.path.exists(climatology_path):
                build_climatology(sst_dir, member, variant, year, climatology_path)
            extract_june_file(sst_dir, member, variant, year, actual_path)
            sst_value = compute_nino34_sst(actual_path)
            climatology_value = compute_nino34_sst(climatology_path)
            anomaly_c = compute_anomaly(sst_value, climatology_value)
            results.append({
                "year": year,
                "anomaly_c": round(anomaly_c, 3),
                "warming": is_warming(anomaly_c, threshold),
            })
        except ValueError as exc:
            results.append({"year": year, "error": str(exc)})
        finally:
            if os.path.exists(actual_path):
                os.remove(actual_path)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sst-dir", required=True)
    parser.add_argument("--member", required=True, help='e.g. "LE2-1091.005"')
    parser.add_argument("--forcing-variant", default="smbb")
    parser.add_argument("--start-year", type=int, required=True,
                         help="first year to check (needs BASELINE_YEARS of prior June data available)")
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--threshold", type=float, default=1.0)
    parser.add_argument("--cache-dir", default=os.path.join(tempfile.gettempdir(), "scan_warming_years_cache"),
                         help="climatology files are cached here across years/runs (default: a temp dir)")
    args = parser.parse_args()

    results = scan(args.sst_dir, args.member, args.forcing_variant,
                    args.start_year, args.end_year, args.threshold, args.cache_dir)

    for r in results:
        if "error" in r:
            print(f"{r['year']}: ERROR — {r['error']}")
        else:
            flag = " <-- WARMING" if r["warming"] else ""
            print(f"{r['year']}: anomaly={r['anomaly_c']:+.3f}C{flag}")

    print(json.dumps(results))


if __name__ == "__main__":
    main()
