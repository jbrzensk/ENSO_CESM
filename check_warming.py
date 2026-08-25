#!/usr/bin/env python3
"""Computes the Nino3.4 SST anomaly for a CESM ocean history file against
a fixed climatology reference file, and reports whether it crosses the
configured warming threshold."""
import argparse
import json
import sys

import xarray as xr

NINO34_LAT_BOUNDS = (-5.0, 5.0)
NINO34_LON_BOUNDS = (190.0, 240.0)  # 170 W - 120 W in 0-360 convention


def compute_nino34_sst(history_file: str, sst_var: str = "SST",
                        area_var: str = "TAREA", lat_var: str = "TLAT",
                        lon_var: str = "TLONG") -> float:
    ds = xr.open_dataset(history_file)
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
    weighted_mean = (sst.where(mask) * area).sum() / area.sum()
    return float(weighted_mean.values)


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
    args = parser.parse_args()

    try:
        sst_value = compute_nino34_sst(args.history_file)
        climatology_value = compute_nino34_sst(args.climatology_file)
        anomaly_c = compute_anomaly(sst_value, climatology_value)
        warming = is_warming(anomaly_c, args.threshold)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"year": args.year, "anomaly_c": round(anomaly_c, 3), "warming": warming}))


if __name__ == "__main__":
    main()
