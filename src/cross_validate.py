"""
Phase 2 (evaluation) - quantitatively compare the three interpolation methods
by spatial k-fold cross-validation on the REAL 2020->2024 swing.

For each fold we hide a subset of counties, predict their swing from the rest
using each method at the held-out county locations, and score the predictions.
This is the honest way to say which method generalises best; eyeballing the
maps is not enough. (CV is run on real data only - the synthetic layer would
just be scoring the method against its own construction.)
"""
from __future__ import annotations
import config as C
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.interpolate import RBFInterpolator


def gaussian_predict(xtr, ytr, vtr, wtr, xq, yq, bandwidth=C.GAUSSIAN_BANDWIDTH_M):
    out = np.empty(len(xq))
    h2 = 2.0 * bandwidth ** 2
    for s in range(0, len(xq), 2000):
        bx, by = xq[s:s+2000], yq[s:s+2000]
        d2 = (bx[:, None]-xtr[None, :])**2 + (by[:, None]-ytr[None, :])**2
        k = np.exp(-d2/h2) * wtr[None, :]
        out[s:s+2000] = (k @ vtr) / np.maximum(k.sum(1), 1e-12)
    return out


def idw_predict(xtr, ytr, vtr, wtr, xq, yq, power=C.IDW_POWER, k=C.IDW_K, min_dist=C.IDW_MIN_DIST_M):
    tree = cKDTree(np.column_stack([xtr, ytr]))
    kk = min(k, len(xtr))
    dist, nn = tree.query(np.column_stack([xq, yq]), k=kk)
    dist = np.maximum(dist, min_dist)
    wgt = wtr[nn] / dist**power
    return (wgt * vtr[nn]).sum(1) / wgt.sum(1)


def tps_predict(xtr, ytr, vtr, wtr, xq, yq, base_smoothing=C.TPS_SMOOTHING, neighbors=C.TPS_NEIGHBORS):
    wmed = np.median(wtr)
    smoothing = base_smoothing * np.clip(wmed/np.clip(wtr, 1, None), 0.1, 10.0)
    rbf = RBFInterpolator(np.column_stack([xtr, ytr]), vtr,
                          kernel="thin_plate_spline", smoothing=smoothing,
                          neighbors=min(neighbors, len(xtr)))
    return rbf(np.column_stack([xq, yq]))


PREDICTORS = {"gaussian": gaussian_predict, "idw": idw_predict, "tps": tps_predict}


def kfold(stations, value_col="swing_H24_H26", n_splits=10, seed=C.RANDOM_SEED):
    df = stations.dropna(subset=[value_col, "weight"]).reset_index(drop=True)
    x = df["x"].to_numpy(float); y = df["y"].to_numpy(float)
    v = df[value_col].to_numpy(float); w = df["weight"].to_numpy(float)
    rng = np.random.default_rng(seed)
    folds = rng.integers(0, n_splits, size=len(df))

    rows = []
    for name, fn in PREDICTORS.items():
        err = np.empty(len(df))
        for f in range(n_splits):
            te = folds == f; tr = ~te
            pred = fn(x[tr], y[tr], v[tr], w[tr], x[te], y[te])
            err[te] = pred - v[te]
        rmse = float(np.sqrt(np.mean(err**2)))
        mae = float(np.mean(np.abs(err)))
        # vote-weighted RMSE: accuracy where the voters actually are
        wrmse = float(np.sqrt(np.average(err**2, weights=w)))
        rows.append({"method": name, "RMSE_pts": rmse, "MAE_pts": mae,
                     "vote_wtd_RMSE_pts": wrmse})
    res = pd.DataFrame(rows).sort_values("vote_wtd_RMSE_pts").reset_index(drop=True)
    return res


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    for col in ["swing_H24_H26", "swing_P20_P24"]:
        res = kfold(stations, value_col=col)
        res.to_csv(C.DATA_PROC / f"cross_validation_{col}.csv", index=False)
        print(f"=== 10-fold spatial cross-validation: {col} ===")
        print(res.to_string(index=False))
        print(f"best (vote-weighted RMSE): {res.iloc[0]['method']}\n")


if __name__ == "__main__":
    main()
