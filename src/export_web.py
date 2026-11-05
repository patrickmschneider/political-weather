"""
Export per-YEAR smoothed margin surfaces + base layers for the interactive app.

Each offered election year (House 2014-2026, President 2020/2024) becomes one
Gaussian-smoothed Democratic two-party margin grid (coarse + fine LOD), smoothed
over that year's CONTESTED counties and weighted by that year's two-party votes.
The browser differences any two years it is shown -> swing = margin(comparison) -
margin(base) - so the viewer can pick both the base and the comparison year.
County-level per-year margins drive the exact colour scale and tooltips.

Coordinates are projected METRES (EPSG:5070).
"""
from __future__ import annotations
import config as C
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from pyproj import Transformer

import interpolate as I
import capitals as CAP

WEB_DATA = C.ROOT / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)


def year_specs():
    out = []
    for yr in C.OFFER_HOUSE_YEARS:
        out.append((f"H{yr}", f"{yr} House", "house",
                    f"hmargin_{yr}", f"hvotes_{yr}", f"hcontested_{yr}"))
    for yr in C.OFFER_PRES_YEARS:
        out.append((f"P{yr}", f"{yr} President", "pres",
                    f"pmargin_{yr}", f"pvotes_{yr}", None))
    return out


def _round_coords(geom, nd=-2):
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
    return GX, GY, (minx, miny)


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    states = gpd.read_file(C.DATA_PROC / "conus_states.gpkg")
    minx, miny, maxx, maxy = land.geometry.iloc[0].bounds
    specs = year_specs()

    meta = {"bounds": [minx, miny, maxx, maxy], "fetched_at": None, "provenance": None,
            "lods": [], "years": {}, "default": {"base": "H2024", "comparison": "H2026"}}
    log = json.load(open(C.DATA_PROC / "data_quality_log.json"))
    meta["fetched_at"] = log["provenance"]["fetched_at"]
    meta["provenance"] = log["provenance"]["source_2026"]

    # subset of contested+present stations per year, and national margin
    subs = {}
    for key, label, typ, mcol, wcol, ccol in specs:
        mask = stations[mcol].notna() & stations[wcol].notna()
        if ccol:
            mask &= stations[ccol].astype(bool)
        sub = stations[mask].copy()
        subs[key] = (sub, mcol, wcol)
        natl = float(np.average(sub[mcol], weights=sub[wcol]))
        meta["years"][key] = {"label": label, "type": typ, "national": round(natl, 2)}

    # per-LOD, per-year margin grids (full rectangle; app clips to land)
    for name, bw, res, zmin in C.WEB_LODS:
        GX, GY, (x0, y0) = _grid(land, res)
        nx, ny = GX.shape[1], GX.shape[0]
        meta["lods"].append({"name": name, "bw_km": bw / 1000, "zmin": zmin,
                             "x0": x0, "y0": y0, "dx": res, "dy": res, "nx": nx, "ny": ny})
        allin = np.ones(GX.shape, bool)
        for key, (sub, mcol, wcol) in subs.items():
            Z = I.gaussian_surface(sub, mcol, GX, GY, allin, bandwidth=bw, weight_col=wcol)
            json.dump({"z": np.round(Z, 2).ravel(order="C").tolist()},
                      open(WEB_DATA / f"margin_{key}_{name}.json", "w"))

    # land mask for the coarse grid: lets the app set the colour-scale domain
    # over land only (offshore extrapolated cells would otherwise inflate it).
    land_geom = land.geometry.iloc[0]
    name0, bw0, res0, _ = C.WEB_LODS[0]
    GX, GY, _ = _grid(land, res0)
    inside = shapely.contains_xy(land_geom, GX.ravel(), GY.ravel())
    json.dump({"nx": GX.shape[1], "ny": GX.shape[0],
               "mask": "".join("1" if b else "0" for b in inside)},
              open(WEB_DATA / "landmask_coarse.json", "w"))

    # base layers
    json.dump(_fc(states, ["STUSPS"]), open(WEB_DATA / "states.json", "w"))
    json.dump(_fc(land), open(WEB_DATA / "land.json", "w"))

    # county per-year margins (null where uncontested/missing) for tooltips + scale
    cj = []
    for _, r in stations.iterrows():
        m = {}
        for key, label, typ, mcol, wcol, ccol in specs:
            ok = pd.notna(r[mcol]) and (not ccol or bool(r[ccol]))
            m[key] = None if not ok else round(float(r[mcol]), 1)
        cj.append({"x": round(r["x"]), "y": round(r["y"]), "n": r["name"], "s": r["state"], "m": m})
    json.dump(cj, open(WEB_DATA / "counties.json", "w"))

    # capitals + majors
    tr = Transformer.from_crs(C.CRS_GEOGRAPHIC, C.CRS_WORKING, always_xy=True)
    def project(rows):
        return [{"n": n, "s": s, "x": round(tr.transform(lon, lat)[0]),
                 "y": round(tr.transform(lon, lat)[1]), "p": pop}
                for n, s, lat, lon, pop in rows]
    json.dump(project(CAP.CAPITALS), open(WEB_DATA / "capitals.json", "w"))
    json.dump(project(CAP.MAJORS), open(WEB_DATA / "majors.json", "w"))

    json.dump(meta, open(WEB_DATA / "meta.json", "w"), indent=1)
    # drop stale single-baseline grids from the previous model
    for f in WEB_DATA.glob("grid_swing_*.json"):
        f.unlink()

    sz = sum(f.stat().st_size for f in WEB_DATA.glob("*.json")) / 1e6
    print(f"Exported web data ({sz:.2f} MB). Years: " + ", ".join(meta["years"].keys()))
    for k, v in meta["years"].items():
        print(f"  {k}: {v['label']:16s} national margin {v['national']:+.1f}")


if __name__ == "__main__":
    main()
