"""
Export smoothed swing surfaces + base layers for the interactive web app.

Everything is in projected METRES (EPSG:5070 CONUS Albers). The app applies one
linear metres->screen transform plus d3.zoom, and builds contour bands with
d3-contour. Each baseline ships at two levels of detail (a coarse 75 km-kernel
surface and a finer 40 km one) so the browser can reveal finer structure as the
viewer zooms in. Only ABSOLUTE swing grids are shipped; the app derives the
deviation-from-national view by subtracting the national swing in-browser.
"""
from __future__ import annotations
import config as C
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely

import interpolate as I

WEB_DATA = C.ROOT / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

BASELINES = {
    "swing_H24_H26": "2024 → 2026 House",
    "swing_H22_H26": "2022 → 2026 House (midterm-to-midterm)",
    "swing_P24_H26": "2024 President → 2026 House (cross-election)",
}


def _round_coords(geom, nd=-2):   # round metres to nearest 100 m to shrink files
    return shapely.transform(geom, lambda a: np.round(a, nd))


def _fc(gdf, props=None):
    feats = []
    for _, row in gdf.reset_index(drop=True).iterrows():
        feats.append({"type": "Feature",
                      "properties": {k: str(row[k]) for k in (props or [])},
                      "geometry": _round_coords(row.geometry).__geo_interface__})
    return {"type": "FeatureCollection", "features": feats}


def _grid(land, res):
    minx, miny, maxx, maxy = land.geometry.iloc[0].bounds
    xs = np.arange(minx, maxx + res, res)
    ys = np.arange(miny, maxy + res, res)
    GX, GY = np.meshgrid(xs, ys)
    return xs, ys, GX, GY, (minx, miny)


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    states = gpd.read_file(C.DATA_PROC / "conus_states.gpkg")
    log = json.load(open(C.DATA_PROC / "data_quality_log.json"))
    land_geom = land.geometry.iloc[0]
    minx, miny, maxx, maxy = land_geom.bounds

    meta = {"bounds": [minx, miny, maxx, maxy], "fetched_at": log["provenance"]["fetched_at"],
            "provenance": log["provenance"]["source_2026"], "lods": [], "baselines": {}}

    # colour-scale domains from the coarse surface (inside land only)
    name0, bw0, res0, _ = C.WEB_LODS[0]
    xs, ys, GX, GY, _ = _grid(land, res0)
    inside = shapely.contains_xy(land_geom, GX.ravel(), GY.ravel()).reshape(GX.shape)
    for col, label in BASELINES.items():
        Zin = I.gaussian_surface(stations, col, GX, GY, inside, bandwidth=bw0)
        v = Zin[np.isfinite(Zin)]
        natl = log["national"][col]["national_swing_pts"]
        meta["baselines"][col] = {
            "label": label, "national": round(natl, 2),
            "abs_vmax": float(np.ceil(np.percentile(np.abs(v), 99))),
            "dev_vmax": float(np.ceil(np.percentile(np.abs(v - natl), 99)))}

    # per-LOD grids (full rectangle, evaluated everywhere; app clips to land)
    for name, bw, res, zmin in C.WEB_LODS:
        xs, ys, GX, GY, (x0, y0) = _grid(land, res)
        nx, ny = len(xs), len(ys)
        meta["lods"].append({"name": name, "bw_km": bw / 1000, "zmin": zmin,
                             "x0": x0, "y0": y0, "dx": res, "dy": res, "nx": nx, "ny": ny})
        for col in BASELINES:
            Z = I.gaussian_surface(stations, col, GX, GY, np.ones(GX.shape, bool), bandwidth=bw)
            json.dump({"z": np.round(Z, 2).ravel(order="C").tolist()},
                      open(WEB_DATA / f"grid_{col}_{name}.json", "w"))

    json.dump(_fc(states, ["STUSPS"]), open(WEB_DATA / "states.json", "w"))
    json.dump(_fc(land), open(WEB_DATA / "land.json", "w"))

    counties = [{"x": round(r["x"]), "y": round(r["y"]), "n": r["name"], "s": r["state"],
                 "v": {c: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in BASELINES}}
                for _, r in stations.iterrows()]
    json.dump(counties, open(WEB_DATA / "counties.json", "w"))
    json.dump(meta, open(WEB_DATA / "meta.json", "w"), indent=1)

    sz = sum(f.stat().st_size for f in WEB_DATA.glob("*.json")) / 1e6
    print(f"Exported web data ({sz:.2f} MB). LODs: " +
          ", ".join(f"{l['name']} {l['bw_km']:.0f}km {l['nx']}x{l['ny']}" for l in meta["lods"]))


if __name__ == "__main__":
    main()
