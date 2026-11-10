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
import shapely.ops
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
    meta["source_commit"] = log["provenance"].get("source_commit")

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

    meta["smoothing"] = {"shrink_k_votes": C.SHRINK_K_VOTES, "shrink_bw_km": C.SHRINK_BW_M / 1000,
                         "truncate_sigma": 5}

    # Population placement: each county (in counties.json order) -> the grid
    # cells holding its census tracts' population centres, with population
    # fractions. The browser deposits a county's votes into those cells and
    # Gaussian-blurs the grid (vote-weighted Nadaraya-Watson, as before).
    tr = pd.read_csv(C.TRACT_CENPOP, dtype={"STATEFP": str, "COUNTYFP": str}, encoding="utf-8-sig")
    tr["fips"] = tr["STATEFP"] + tr["COUNTYFP"]
    tr = tr[tr["POPULATION"] > 0]
    tp = gpd.GeoSeries(gpd.points_from_xy(tr["LONGITUDE"], tr["LATITUDE"]),
                       crs=C.CRS_GEOGRAPHIC).to_crs(C.CRS_WORKING)
    tr["X"], tr["Y"] = tp.x.values, tp.y.values
    by_fips = {f: g for f, g in tr.groupby("fips")}
    no_tracts = 0
    for name, bw, res, zmin in C.WEB_LODS:
        GX, GY, (x0, y0) = _grid(land, res)
        nx, ny = GX.shape[1], GX.shape[0]
        meta["lods"].append({"name": name, "bw_km": bw / 1000, "zmin": zmin,
                             "x0": x0, "y0": y0, "dx": res, "dy": res, "nx": nx, "ny": ny})
        off, idx, frac = [0], [], []
        for _, r in stations.iterrows():
            g = by_fips.get(r["fips"])
            if g is None or g["POPULATION"].sum() <= 0:
                xs, ys, ps = np.array([r["x"]]), np.array([r["y"]]), np.array([1.0])
                no_tracts += 1
            else:
                xs, ys, ps = g["X"].to_numpy(), g["Y"].to_numpy(), g["POPULATION"].to_numpy(float)
            ci = np.clip(np.rint((xs - x0) / res).astype(int), 0, nx - 1)
            cj = np.clip(np.rint((ys - y0) / res).astype(int), 0, ny - 1)
            cell = cj * nx + ci
            agg = pd.Series(ps).groupby(cell).sum()
            agg = agg / agg.sum()
            idx += agg.index.astype(int).tolist()
            frac += np.round(agg.to_numpy(), 4).tolist()
            off.append(len(idx))
        json.dump({"off": off, "i": idx, "f": frac}, open(WEB_DATA / f"cells_{name}.json", "w"))
        print(f"cells_{name}: {len(idx)} county-cell entries")
    print(f"Counties without tracts (placed at their own point): {no_tracts // len(C.WEB_LODS)}")
    for f in WEB_DATA.glob("margin_*_*.json"):   # superseded by in-browser smoothing
        f.unlink()

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
    # State-code label anchors: an interior point of each state's LARGEST part
    # (so MI sits on the Lower Peninsula), with area to prioritise big states.
    slabels = []
    for _, r in states.iterrows():
        g = r.geometry
        main = max(getattr(g, "geoms", [g]), key=lambda p: p.area)
        pt = shapely.ops.polylabel(main, tolerance=2000) if hasattr(shapely.ops, "polylabel") else main.representative_point()
        slabels.append({"n": str(r["STUSPS"]), "x": round(pt.x), "y": round(pt.y),
                        "a": round(g.area / 1e9)})
    json.dump(slabels, open(WEB_DATA / "state_labels.json", "w"))
    json.dump(_fc(land), open(WEB_DATA / "land.json", "w"))

    # County per-year margins (null where uncontested/missing) and two-party
    # votes. The app smooths SWING from these directly, over only the counties
    # valid in BOTH years of a pair — differencing two per-year surfaces built
    # on different county sets invents swings where one year is uncontested.
    cj = []
    for _, r in stations.iterrows():
        m, w = {}, {}
        for key, label, typ, mcol, wcol, ccol in specs:
            ok = pd.notna(r[mcol]) and pd.notna(r[wcol]) and (not ccol or bool(r[ccol]))
            m[key] = None if not ok else round(float(r[mcol]), 2)
            w[key] = None if not ok else int(round(float(r[wcol])))
        cj.append({"x": round(r["x"]), "y": round(r["y"]), "n": r["name"], "s": r["state"], "m": m, "w": w})
    json.dump(cj, open(WEB_DATA / "counties.json", "w"))

    # capitals + majors
    tr = Transformer.from_crs(C.CRS_GEOGRAPHIC, C.CRS_WORKING, always_xy=True)
    def project(rows):
        return [{"n": n, "s": s, "x": round(tr.transform(lon, lat)[0]),
                 "y": round(tr.transform(lon, lat)[1]), "p": pop}
                for n, s, lat, lon, pop in rows]
    json.dump(project(CAP.CAPITALS), open(WEB_DATA / "capitals.json", "w"))
    json.dump(project(CAP.MAJORS), open(WEB_DATA / "majors.json", "w"))
    towns = CAP.load_towns(C.DATA_RAW / CAP.TOWNS_SRC, CAP.CAPITALS + CAP.MAJORS)
    json.dump(project(towns), open(WEB_DATA / "towns.json", "w"))
    print(f"Towns for zoom labels: {len(towns)}")

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
