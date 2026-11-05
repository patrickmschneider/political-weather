"""
Export the smoothed swing surfaces + base layers for the interactive web app.

Everything is emitted in a single planar coordinate space - GRID-INDEX units of
the CONUS Albers (EPSG:5070) evaluation grid - so the browser needs no map
projection: one linear transform maps grid units to screen, d3-contour builds
the isoline bands from the grid, and d3.zoom handles pan/zoom.

Only ABSOLUTE swing grids are shipped (one per baseline); the app derives the
"deviation from national" view by subtracting the national swing in-browser.
"""
from __future__ import annotations
import config as C
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import transform as shp_transform

import interpolate as I

WEB_DATA = C.ROOT / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

BASELINES = {  # value column -> label shown in the app
    "swing_H24_H26": "2024 → 2026 House",
    "swing_H22_H26": "2022 → 2026 House (midterm-to-midterm)",
    "swing_P24_H26": "2024 President → 2026 House (cross-election)",
}


def _full_grid(land):
    """Grid over the land bounding box; evaluate the kernel at EVERY cell
    (no land mask) so contour bands are clean to the coast - the app clips to
    the land outline for display."""
    xs, ys, GX, GY, inside, extent = I.make_grid(land)
    allin = np.ones(GX.shape, bool)
    return xs, ys, GX, GY, inside, allin, extent


def _to_idx(x0, dx, y0, dy):
    return lambda x, y, z=None: ((x - x0) / dx, (y - y0) / dy)


def _geom_to_idx_geojson(gdf, fn, props=None):
    feats = []
    for i, row in gdf.reset_index(drop=True).iterrows():
        g = shp_transform(fn, row.geometry)
        feats.append({"type": "Feature",
                      "properties": {k: row[k] for k in (props or [])},
                      "geometry": g.__geo_interface__})
    return {"type": "FeatureCollection", "features": feats}


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    states = gpd.read_file(C.DATA_PROC / "conus_states.gpkg")
    log = json.load(open(C.DATA_PROC / "data_quality_log.json"))

    xs, ys, GX, GY, inside, allin, extent = _full_grid(land)
    nx, ny = len(xs), len(ys)
    x0, y0 = xs[0], ys[0]
    dx = xs[1] - xs[0]; dy = ys[1] - ys[0]
    to_idx = _to_idx(x0, dx, y0, dy)

    meta = {"nx": nx, "ny": ny, "fetched_at": log["provenance"]["fetched_at"],
            "provenance": log["provenance"]["source_2026"], "baselines": {}}

    for col, label in BASELINES.items():
        Zfull = I.gaussian_surface(stations, col, GX, GY, allin)
        # stats inside land only (for colour-scale domains)
        Zin = I.gaussian_surface(stations, col, GX, GY, inside)
        vin = Zin[np.isfinite(Zin)]
        natl = log["national"][col]["national_swing_pts"]
        abs_vmax = float(np.ceil(np.percentile(np.abs(vin), 99)))
        dev_vmax = float(np.ceil(np.percentile(np.abs(vin - natl), 99)))
        # row-major z[j*nx + i], rounded to save space
        z = np.round(Zfull, 2).ravel(order="C").tolist()
        json.dump({"z": z}, open(WEB_DATA / f"grid_{col}.json", "w"))
        meta["baselines"][col] = {"label": label, "national": round(natl, 2),
                                  "abs_vmax": abs_vmax, "dev_vmax": dev_vmax}

    # base layers in grid-index space
    json.dump(_geom_to_idx_geojson(states, to_idx, ["STUSPS"]),
              open(WEB_DATA / "states.json", "w"))
    json.dump(_geom_to_idx_geojson(land, to_idx),
              open(WEB_DATA / "land.json", "w"))

    # county points (grid-index) with per-baseline absolute swing for tooltips
    cj = []
    for _, r in stations.iterrows():
        ix, iy = to_idx(r["x"], r["y"])
        rec = {"x": round(ix, 2), "y": round(iy, 2), "n": r["name"], "s": r["state"],
               "v": {c: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in BASELINES}}
        cj.append(rec)
    json.dump(cj, open(WEB_DATA / "counties.json", "w"))

    json.dump(meta, open(WEB_DATA / "meta.json", "w"), indent=2)
    sz = sum(f.stat().st_size for f in WEB_DATA.glob("*.json"))
    print(f"Exported web data to {WEB_DATA}  ({sz/1e6:.2f} MB, grid {nx}x{ny})")
    for c, m in meta["baselines"].items():
        print(f"  {c}: national {m['national']:+.1f}  abs_vmax {m['abs_vmax']:.0f}  dev_vmax {m['dev_vmax']:.0f}")


if __name__ == "__main__":
    main()
