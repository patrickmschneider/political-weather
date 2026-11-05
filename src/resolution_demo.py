"""
Show how the Gaussian bandwidth - not the grid or the data - sets the apparent
resolution. Same real 2024->2026 House swing, same 12 km grid, three bandwidths.
"""
from __future__ import annotations
import config as C
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import interpolate as I
import render as R

COL = "swing_H24_H26"
BANDWIDTHS = [(120_000, "120 km  (current)"), (75_000, "75 km"), (45_000, "45 km")]
FINE_RES = 12_000


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    states = gpd.read_file(C.DATA_PROC / "conus_states.gpkg")

    xs, ys, GX, GY, inside, extent = I.make_grid(land, res_m=FINE_RES)
    grid = {"GX": GX, "GY": GY, "extent": extent}
    vmax = 32.0

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.3))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.82, bottom=0.14, wspace=0.02)
    cf = None
    for ax, (bw, lab) in zip(axes, BANDWIDTHS):
        Z = I.gaussian_surface(stations, COL, GX, GY, inside, bandwidth=bw)
        cf = R._draw_panel(ax, grid, Z, states, vmax, f"Bandwidth {lab}",
                           step_fill=1.0, step_line=4.0)
    fig.suptitle("Apparent resolution is the Gaussian bandwidth, not the grid",
                 fontsize=16, fontweight="bold", y=0.975)
    fig.text(0.5, 0.88, "2024→ 2026 House swing · identical 12 km grid & county data · "
             "only the kernel width changes", ha="center", fontsize=10.5, color="#555")
    cbar = fig.colorbar(cf, ax=axes, orientation="horizontal", fraction=0.045, pad=0.03, aspect=55)
    cbar.set_label("Swing (pts)   ← Republican      Democratic →", fontsize=10)
    out = C.OUTPUT / "resolution_bandwidth_compare.png"
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    main()
