"""
Alaska / Hawaii inset surfaces for the contour maps.

Hawaii: 4 island counties carry real 2026 House results, so a (small-bandwidth)
Gaussian surface is built per island in a Hawaii-centred equal-area projection
and clipped to each island's land.

Alaska: the single at-large RCV seat has essentially no borough-level 2026
returns in this feed (and its historical data is reported by legislative
district, not borough), so NO Alaska swing surface is produced - the renderer
draws a greyed "result pending" box instead. Honest, not fabricated.
"""
from __future__ import annotations
import config as C
import numpy as np
import geopandas as gpd
import shapely

import interpolate as I


def _region_stations(stations_all, statefp, region_crs, value_col):
    sel = stations_all[(stations_all["STATEFP"] == statefp)
                       & stations_all[value_col].notna()
                       & stations_all["weight"].notna()].copy()
    if len(sel):
        p = gpd.GeoSeries(gpd.points_from_xy(sel["lon"], sel["lat"]),
                          crs=C.CRS_GEOGRAPHIC).to_crs(region_crs)
        sel["x"] = p.x.values
        sel["y"] = p.y.values
    return sel


def _region_land(statefp, region_crs):
    st = gpd.read_file(C.STATE_SHP)
    return st[st["STATEFP"] == statefp].to_crs(region_crs)


def build_hi_surface(stations_all, value_col):
    sel = _region_stations(stations_all, "15", C.CRS_HI, value_col)
    land = _region_land("15", C.CRS_HI)
    land_geom = land.dissolve().geometry.iloc[0].buffer(0)
    minx, miny, maxx, maxy = land_geom.bounds
    res = C.HI_GRID_RES_M
    xs = np.arange(minx, maxx + res, res)
    ys = np.arange(miny, maxy + res, res)
    GX, GY = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(land_geom, GX.ravel(), GY.ravel()).reshape(GX.shape)
    Z = (I.gaussian_surface(sel, value_col, GX, GY, inside, bandwidth=C.HI_BANDWIDTH_M)
         if len(sel) else np.full(GX.shape, np.nan))
    return {"GX": GX, "GY": GY, "Z": Z, "land": land,
            "extent": (minx, maxx, miny, maxy), "n": len(sel)}


def ak_geometry():
    return _region_land("02", C.CRS_AK)
