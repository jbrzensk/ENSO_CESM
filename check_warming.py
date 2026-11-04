#!/usr/bin/env python3
"""Computes the Nino3.4 SST anomaly for a CESM ocean history file against
a fixed climatology reference file, and reports whether it crosses the
configured warming threshold."""
import argparse
import json
import sys

import numpy as np
import xarray as xr

NINO34_LAT_BOUNDS = (-5.0, 5.0)
NINO34_LON_BOUNDS = (190.0, 240.0)  # 170 W - 120 W in 0-360 convention


def compute_nino34_sst(history_file: str, sst_var: str = "SST",
                        area_var: str = "TAREA", lat_var: str = "TLAT",
                        lon_var: str = "TLONG") -> float:
    with xr.open_dataset(history_file) as ds:
        lat = ds[lat_var]
        lon = ds[lon_var] % 360
        mask = (
            (lat >= NINO34_LAT_BOUNDS[0]) & (lat <= NINO34_LAT_BOUNDS[1]) &
            (lon >= NINO34_LON_BOUNDS[0]) & (lon <= NINO34_LON_BOUNDS[1])
        )
        sst = ds[sst_var]
        if "z_t" in sst.dims:
            sst = sst.isel(z_t=0)
        area = ds[area_var].where(mask)
        total_area = area.sum().values
        if total_area == 0:
            raise ValueError(
                f"Nino3.4 region mask matched no grid cells in {history_file} — "
                "check lat/lon variable names and box bounds"
            )
        weighted_mean = (sst.where(mask) * area).sum() / total_area
        result = float(weighted_mean.values)
    if not np.isfinite(result):
        raise ValueError(
            f"Nino3.4 SST computation produced non-finite value ({result}) "
            f"from {history_file} — check data quality and variable names"
        )
    return result


def compute_anomaly(sst_value: float, climatology_value: float) -> float:
    return sst_value - climatology_value


def is_warming(anomaly_c: float, threshold_c: float) -> bool:
    return anomaly_c >= threshold_c


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-file", required=True)
    parser.add_argument("--climatology-file", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--threshold", type=float, default=1.0)
    # The two files carry sea-surface temperature under different names. A
    # CESM2 POP monthly history file has no 2-D SST, only 3-D TEMP, whose top
    # level is the surface value (confirmed against a real pop.h file on
    # 2026-11-04); build_climatology.py's output carries 2-D SST, as in the
    # CESM2-LE tseries it is built from. The grid variables are shared.
    parser.add_argument("--history-sst-var", default="TEMP",
                        help="history-file temperature variable (default: TEMP, top level used)")
    parser.add_argument("--climatology-sst-var", default="SST",
                        help="climatology-file SST variable (default: SST)")
    parser.add_argument("--area-var", default="TAREA", help="cell-area variable name (default: TAREA)")
    parser.add_argument("--lat-var", default="TLAT", help="latitude variable name (default: TLAT)")
    parser.add_argument("--lon-var", default="TLONG", help="longitude variable name (default: TLONG)")
    args = parser.parse_args()

    grid_names = dict(area_var=args.area_var, lat_var=args.lat_var, lon_var=args.lon_var)

    try:
        sst_value = compute_nino34_sst(
            args.history_file, sst_var=args.history_sst_var, **grid_names)
        climatology_value = compute_nino34_sst(
            args.climatology_file, sst_var=args.climatology_sst_var, **grid_names)
        anomaly_c = compute_anomaly(sst_value, climatology_value)
        warming = is_warming(anomaly_c, args.threshold)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"year": args.year, "anomaly_c": round(anomaly_c, 3), "warming": warming}))


if __name__ == "__main__":
    main()
