"""
Phase 3 - Render the swing surfaces as meteorological-style contour charts.

Filled contours + labelled isolines (isobar style), diverging red/blue centred
on zero (blue = toward Democrats, red = toward Republicans), state overlay,
clipped to CONUS land. Two framings per the brief:
  * ABSOLUTE swing (Democratic two-party margin change), and
  * DEVIATION from the national swing (uniform-swing residual).
Every figure is stamped with the provisional data provenance.
"""
from __future__ import annotations
import config as C
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

import interpolate as I
import insets as INS

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.edgecolor": "#444444", "figure.facecolor": "white"})

METHOD_TITLES = {"gaussian": "Gaussian kernel smoothing",
                 "idw": "Inverse-distance weighting",
                 "tps": "Thin-plate spline"}


def _sym_vmax(surfaces, q=98):
    allv = np.concatenate([Z[np.isfinite(Z)].ravel() for Z in surfaces.values()])
    return float(np.percentile(np.abs(allv), q))


def _draw_panel(ax, grid, Z, states, vmax, title, step_fill, step_line):
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    fill_levels = np.arange(-vmax, vmax + step_fill, step_fill)
    cf = ax.contourf(grid["GX"], grid["GY"], Z, levels=fill_levels,
                     cmap="RdBu", norm=norm, extend="both")
    lv = np.arange(-np.floor(vmax/step_line)*step_line,
                   np.floor(vmax/step_line)*step_line + step_line, step_line)
    cs = ax.contour(grid["GX"], grid["GY"], Z, levels=lv,
                    colors="#33333366", linewidths=0.6)
    ax.clabel(cs, inline=True, fontsize=6, fmt="%+.0f")
    states.boundary.plot(ax=ax, color="#2b2b2b", linewidth=0.5)
    ax.set_xlim(grid["extent"][0], grid["extent"][1])
    ax.set_ylim(grid["extent"][2], grid["extent"][3])
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    if title:
        ax.set_title(title, fontsize=11, pad=6)
    return cf


def _draw_hi_inset(ax, hi, vmax, cmap="RdBu"):
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    if np.isfinite(hi["Z"]).any():
        ax.contourf(hi["GX"], hi["GY"], hi["Z"],
                    levels=np.arange(-vmax, vmax + 0.5, 0.5), cmap=cmap,
                    norm=norm, extend="both")
    hi["land"].boundary.plot(ax=ax, color="#2b2b2b", linewidth=0.4)
    ax.set_xlim(hi["extent"][0], hi["extent"][1])
    ax.set_ylim(hi["extent"][2], hi["extent"][3])
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Hawaiʻi", fontsize=8, pad=1)
    for s in ax.spines.values():
        s.set_color("#999999"); s.set_linewidth(0.5)


def _draw_ak_inset(ax, ak_geom):
    ak_geom.plot(ax=ax, color="#e9e9e9", edgecolor="#9a9a9a", linewidth=0.4)
    b = ak_geom.total_bounds
    ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3])
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Alaska", fontsize=8, pad=1)
    ax.text(0.5, 0.42, "2026 at-large\nresult pending\n(RCV)", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.0, color="#777777", style="italic")
    for s in ax.spines.values():
        s.set_color("#999999"); s.set_linewidth(0.5)


def render_hero(stations, land, states, value_col, method, out_png, title,
                subtitle, footer, vmax=None, step_fill=0.5, step_line=2.0,
                show_dots=True, watermark=None, stations_all=None):
    grid = I.build_all(stations, value_col, land)
    if vmax is None:
        vmax = max(2.0, round(_sym_vmax({method: grid["surfaces"][method]})))
    fig, ax = plt.subplots(figsize=(13, 8.6))
    cf = _draw_panel(ax, grid, grid["surfaces"][method], states, vmax, "",
                     step_fill, step_line)
    if show_dots:
        s = stations.dropna(subset=[value_col])
        ax.scatter(s["x"], s["y"], s=1.0, c="#00000018", linewidths=0)
    if stations_all is not None:
        ax_ak = ax.inset_axes([0.005, 0.01, 0.17, 0.20])
        _draw_ak_inset(ax_ak, INS.ak_geometry())
        ax_hi = ax.inset_axes([0.185, 0.01, 0.13, 0.13])
        _draw_hi_inset(ax_hi, INS.build_hi_surface(stations_all, value_col), vmax)
    ax.set_title(title, fontsize=18, fontweight="bold", pad=10)
    fig.text(0.5, 0.905, subtitle, ha="center", fontsize=11, color="#555555")
    cbar = fig.colorbar(cf, ax=ax, orientation="vertical", fraction=0.03, pad=0.01)
    cbar.set_label("Swing (pts)   ← Republican   Democratic →", fontsize=9)
    fig.text(0.5, 0.045, footer, ha="center", fontsize=7.5, color="#888888")
    if watermark:
        ax.text(0.5, 0.5, watermark, transform=ax.transAxes, fontsize=46,
                color="#80808033", ha="center", va="center", rotation=20,
                fontweight="bold", zorder=50)
    fig.savefig(out_png, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return out_png


def render_comparison(stations, land, states, value_col, out_png, suptitle,
                      subtitle, footer, watermark=None):
    grid = I.build_all(stations, value_col, land)
    vmax = max(2.0, round(_sym_vmax({"gaussian": grid["surfaces"]["gaussian"]})))
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.3))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.80, bottom=0.16, wspace=0.02)
    cf = None
    for ax, name in zip(axes, ["gaussian", "idw", "tps"]):
        cf = _draw_panel(ax, grid, grid["surfaces"][name], states, vmax,
                         METHOD_TITLES[name], step_fill=1.0, step_line=3.0)
    fig.suptitle(suptitle, fontsize=17, fontweight="bold", y=0.975)
    fig.text(0.5, 0.875, subtitle, ha="center", fontsize=10.5, color="#555555")
    cbar = fig.colorbar(cf, ax=axes, orientation="horizontal",
                        fraction=0.045, pad=0.03, aspect=55)
    cbar.set_label("Swing (percentage points)   ← toward Republicans      "
                   "toward Democrats →", fontsize=10)
    fig.text(0.5, 0.02, footer, ha="center", fontsize=7.5, color="#888888")
    if watermark:
        fig.text(0.5, 0.5, watermark, fontsize=62, color="#80808022",
                 ha="center", va="center", rotation=20, fontweight="bold", zorder=50)
    fig.savefig(out_png, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return out_png


def main():
    stations = pd.read_csv(C.DATA_PROC / "stations.csv", dtype={"fips": str})
    stations_all = pd.read_csv(C.DATA_PROC / "stations_all.csv", dtype={"fips": str})
    land = gpd.read_file(C.DATA_PROC / "conus_land.gpkg")
    states = gpd.read_file(C.DATA_PROC / "conus_states.gpkg")
    log = json.load(open(C.DATA_PROC / "data_quality_log.json"))
    fetched = log["provenance"]["fetched_at"]
    natl = log["national"]["swing_H24_H26"]["national_swing_pts"]
    foot = (f"PROVISIONAL unofficial returns · source: mike10010100/elections-2026 (NYT) · "
            f"fetched {fetched[:16]} · CONUS Albers Equal Area · "
            f"county observations weighted by 2026 two-party votes · uncontested seats excluded")

    # (1) PROTOTYPE - absolute 2024->2026 House swing, Gaussian hero
    render_hero(stations, land, states, "swing_H24_H26", "gaussian",
                C.OUTPUT / "swing_H24_H26_hero.png",
                "U.S. House Swing, 2024 → 2026",
                f"Change in Democratic two-party margin  ·  national swing {natl:+.1f} pts toward Democrats",
                foot, watermark="PROVISIONAL", stations_all=stations_all)

    # (2) deviation from national swing (uniform-swing residual)
    render_hero(stations, land, states, "swing_H24_H26_dev", "gaussian",
                C.OUTPUT / "swing_H24_H26_deviation_hero.png",
                "2026 House Swing — Deviation from National",
                f"County swing minus the national {natl:+.1f}-pt swing  ·  "
                "blue = swung MORE Democratic than nation, red = less",
                foot, watermark="PROVISIONAL", stations_all=stations_all)

    # (3) three-method comparison (absolute swing)
    render_comparison(stations, land, states, "swing_H24_H26",
                      C.OUTPUT / "swing_H24_H26_methods.png",
                      "U.S. House Swing, 2024 → 2026  —  three interpolation methods",
                      "Democratic two-party margin change by county",
                      foot, watermark="PROVISIONAL")

    # (4) fully-real validation surface: 2020 -> 2024 presidential
    vfoot = ("REAL certified-era returns · 2020 & 2024 presidential (tonmcg) · "
             "CONUS Albers Equal Area · weighted by 2024 two-party votes")
    render_hero(stations, land, states, "swing_P20_P24", "gaussian",
                C.OUTPUT / "validation_swing_P20_P24_hero.png",
                "Validation — U.S. Presidential Swing, 2020 → 2024 (Real)",
                "Gaussian-smoothed Democratic two-party margin change  ·  "
                "same pipeline, fully-real data",
                vfoot)
    print("Rendered 4 figures to", C.OUTPUT)


if __name__ == "__main__":
    main()
