"""
Phase 2 - Construct a continuous electoral swing surface.

Three independent spatial methods, all operating in CONUS Albers Equal Area
(metres) and all population-aware:

  1. Gaussian kernel smoothing (Nadaraya-Watson), weighted by two-party votes.
  2. Inverse-distance weighting (IDW), k-nearest, weighted by two-party votes.
  3. Thin-plate-spline RBF with per-station regularisation that downweights
     low-population counties (population-aware smoothing).

The evaluation grid is masked to the CONUS land polygon so no isoline is drawn
across oceans. (Cross-water *influence* in the weighting is mitigated by a
moderate bandwidth and documented as a limitation; a true geodesic barrier is
out of scope.)
"""
from __future__ import annotations
import config as C  # first: caps BLAS threads before numpy/scipy load
import numpy as np
from scipy.spatial import cKDTree
from scipy.interpolate import RBFInterpolator
import geopandas as gpd
import shapely


def make_grid(land_gdf: gpd.GeoDataFrame, res_m: float = C.GRID_RES_M):
    land = land_gdf.geometry.iloc[0]
    minx, miny, maxx, maxy = land.bounds
    xs = np.arange(minx, maxx + res_m, res_m)
    ys = np.arange(miny, maxy + res_m, res_m)
    GX, GY = np.meshgrid(xs, ys)
    # Land mask: keep only grid centres inside CONUS (no ocean isolines).
    inside = shapely.contains_xy(land, GX.ravel(), GY.ravel()).reshape(GX.shape)
    extent = (minx, maxx, miny, maxy)
    return xs, ys, GX, GY, inside, extent


def _as_arrays(stations):
    x = stations["x"].to_numpy(float)
    y = stations["y"].to_numpy(float)
    w = stations["weight"].to_numpy(float)
    return x, y, w


def gaussian_surface(stations, value_col, GX, GY, inside,
                     bandwidth=C.GAUSSIAN_BANDWIDTH_M, weight_col="weight"):
    x = stations["x"].to_numpy(float)
    y = stations["y"].to_numpy(float)
    w = stations[weight_col].to_numpy(float)
    v = stations[value_col].to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(w)
    x, y, w, v = x[ok], y[ok], w[ok], v[ok]
    P = np.column_stack([GX.ravel(), GY.ravel()])
    Z = np.full(P.shape[0], np.nan)
    idx = np.where(inside.ravel())[0]
    h2 = 2.0 * bandwidth ** 2
    # Chunk the grid to keep the dense distance matrix small.
    for s in range(0, idx.size, 2000):
        blk = idx[s:s + 2000]
        d2 = (P[blk, 0][:, None] - x[None, :]) ** 2 + (P[blk, 1][:, None] - y[None, :]) ** 2
        k = np.exp(-d2 / h2) * w[None, :]
        num = k @ v
        den = k.sum(axis=1)
        Z[blk] = np.where(den > 0, num / den, np.nan)
    return Z.reshape(GX.shape)


def idw_surface(stations, value_col, GX, GY, inside,
                power=C.IDW_POWER, k=C.IDW_K, min_dist=C.IDW_MIN_DIST_M):
    x, y, w = _as_arrays(stations)
    v = stations[value_col].to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(w)
    x, y, w, v = x[ok], y[ok], w[ok], v[ok]
    tree = cKDTree(np.column_stack([x, y]))
    P = np.column_stack([GX.ravel(), GY.ravel()])
    Z = np.full(P.shape[0], np.nan)
    idx = np.where(inside.ravel())[0]
    kk = min(k, len(x))
    dist, nn = tree.query(P[idx], k=kk)
    dist = np.maximum(dist, min_dist)
    wgt = (w[nn] / dist ** power)
    num = (wgt * v[nn]).sum(axis=1)
    den = wgt.sum(axis=1)
    Z[idx] = np.where(den > 0, num / den, np.nan)
    return Z.reshape(GX.shape)


def tps_surface(stations, value_col, GX, GY, inside,
                base_smoothing=C.TPS_SMOOTHING, neighbors=C.TPS_NEIGHBORS):
    x, y, w = _as_arrays(stations)
    v = stations[value_col].to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(w)
    x, y, w, v = x[ok], y[ok], w[ok], v[ok]
    # Population-aware regularisation: smaller counties get MORE smoothing
    # (trusted less), larger counties pin the surface more firmly.
    wmed = np.median(w)
    smoothing = base_smoothing * np.clip(wmed / np.clip(w, 1, None), 0.1, 10.0)
    XY = np.column_stack([x, y])
    rbf = RBFInterpolator(XY, v, kernel="thin_plate_spline",
                          smoothing=smoothing, neighbors=neighbors)
    P = np.column_stack([GX.ravel(), GY.ravel()])
    Z = np.full(P.shape[0], np.nan)
    idx = np.where(inside.ravel())[0]
    Z[idx] = rbf(P[idx])
    return Z.reshape(GX.shape)


METHODS = {
    "gaussian": gaussian_surface,
    "idw": idw_surface,
    "tps": tps_surface,
}


def build_all(stations, value_col, land_gdf):
    xs, ys, GX, GY, inside, extent = make_grid(land_gdf)
    surfaces = {name: fn(stations, value_col, GX, GY, inside)
                for name, fn in METHODS.items()}
    return {"xs": xs, "ys": ys, "GX": GX, "GY": GY, "inside": inside,
            "extent": extent, "surfaces": surfaces}


if __name__ == "__main__":
    import pandas as pd, time, sys
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"county_fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    t0 = time.time()
    xs, ys, GX, GY, inside, extent = make_grid(land)
    print(f"grid {GX.shape}, land cells {int(inside.sum())} / {inside.size}  ({time.time()-t0:.1f}s)", flush=True)
    for col in ["swing_H24_H26", "swing_H24_H26_dev", "swing_P20_P24"]:
        for name, fn in METHODS.items():
            t = time.time()
            Z = fn(stations, col, GX, GY, inside)
            vals = Z[np.isfinite(Z)]
            print(f"{col:18s} {name:8s} range [{vals.min():6.1f}, {vals.max():6.1f}]  mean {vals.mean():6.2f}  ({time.time()-t:.1f}s)", flush=True)
