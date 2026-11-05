"""
Phase 1 - Data acquisition, validation, margin & swing calculation.

Builds a projected table of county "stations" from REAL returns:
  - 2026 US House results (provisional, mike10010100/elections-2026 -> NYT),
  - same-office baselines: 2024 House and 2022 House,
  - a cross-election baseline: 2024 Presidential (tonmcg compilation),
and derived swings as Democratic TWO-PARTY margin changes, plus each swing's
DEVIATION FROM NATIONAL swing (uniform-swing residual).

Integrity rules enforced here:
  * Two-party margin = (D - R)/(D + R); never computed where a party is absent.
  * Uncontested / same-party (top-two) county-cycles are flagged and EXCLUDED
    from any swing that uses them - never silently treated as a real margin.
  * 2026 counties below an expected-vote-counted threshold are excluded.
  * Counties missing an endpoint are dropped from that swing and reported.
Nothing missing is ever coerced to zero.
"""
from __future__ import annotations
import config as C  # first: caps BLAS threads before numpy/scipy load
import json
import numpy as np
import pandas as pd
import geopandas as gpd

EXCLUDE = C.EXCLUDE_STATEFP


def _tp_margin(d, r):
    """Democratic two-party margin in points; NaN if no two-party vote."""
    d = np.asarray(d, float); r = np.asarray(r, float)
    tp = d + r
    return np.where(tp > 0, (d - r) / tp * 100.0, np.nan)


def load_house(src) -> pd.DataFrame:
    """Flatten county_shifts.json into one row per county with per-cycle
    two-party margins, two-party votes and contested/completeness flags."""
    cs = json.load(open(src))
    rows = []
    cycles = [("h" + str(yr)[2:], yr) for yr in C.OFFER_HOUSE_YEARS]
    for fips, c in cs["counties"].items():
        row = {"fips": str(fips).zfill(5), "state": c.get("state"),
               "name": c.get("name")}
        for cyc, yr in cycles:
            h = c.get(cyc) or {}
            d, r, v = h.get("d"), h.get("r"), h.get("v")
            row[f"hmargin_{yr}"] = _tp_margin(d, r) if d is not None and r is not None else np.nan
            row[f"hvotes_{yr}"] = (v * (d + r) / 100.0) if (v and d is not None and r is not None) else np.nan
            # contested iff both major parties clear the floor (excludes
            # uncontested seats and same-party top-two races).
            row[f"hcontested_{yr}"] = bool(
                d is not None and r is not None
                and min(d, r) >= C.CONTEST_MIN_PCT)
            if cyc == "h26":
                row["eevp_2026"] = h.get("eevp")
        rows.append(row)
    return pd.DataFrame(rows)


def load_pres(path, year) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"county_fips": str})
    df["fips"] = df["county_fips"].str.zfill(5)
    df[f"pmargin_{year}"] = _tp_margin(df["votes_dem"], df["votes_gop"])
    df[f"pvotes_{year}"] = df["votes_dem"] + df["votes_gop"]
    return df[["fips", f"pmargin_{year}", f"pvotes_{year}"]]


def national_swing(df, m_from, m_to, w_to, valid):
    """National swing from AGGREGATE two-party votes over the valid set, plus
    the vote-weighted mean county swing (should be close)."""
    v = df[valid]
    # National margins = two-party-vote-weighted mean of county margins; the
    # national swing used for deviations is the vote-weighted mean county swing.
    nat_from = float(np.average(v[m_from], weights=v[w_to]))
    nat_to = float(np.average(v[m_to], weights=v[w_to]))
    nat = float(np.average(v[m_to] - v[m_from], weights=v[w_to]))
    return nat, nat_from, nat_to


def main():
    log = {"provenance": {}, "data_quality": {}, "national": {}}
    ov = json.load(open(C.SOURCE_2026_OVERVIEW))
    log["provenance"]["source_2026"] = C.SOURCE_2026_PROVENANCE
    log["provenance"]["fetched_at"] = ov.get("fetched_at")
    log["provenance"]["baseline_pres"] = "tonmcg/US_County_Level_Election_Results_08-24"
    log["provenance"]["geometry"] = "US Census CB 2021 county/state 1:20m (traditional CT counties)"

    house = load_house(C.SOURCE_2026)
    p24 = load_pres(C.DATA_RAW / "2024_county_pres.csv", 2024)
    p20 = load_pres(C.DATA_RAW / "2020_county_pres.csv", 2020)
    df = house.merge(p24, on="fips", how="left").merge(p20, on="fips", how="left")

    # --- Geometry for ALL counties (geographic rep points) ------------------
    # One all-states table drives both the CONUS surface and the AK/HI insets;
    # store lon/lat so each consumer reprojects into its own equal-area CRS.
    cty_all = gpd.read_file(C.COUNTY_SHP).to_crs(C.CRS_GEOGRAPHIC)
    rep = cty_all.geometry.representative_point()
    cty_all = cty_all.assign(lon=rep.x, lat=rep.y)
    allpts = cty_all[["GEOID", "STATEFP", "lon", "lat"]].merge(
        df, left_on="GEOID", right_on="fips", how="left")

    states = gpd.read_file(C.STATE_SHP)
    states = states[~states["STATEFP"].isin(EXCLUDE)].to_crs(C.CRS_WORKING)

    # --- Weight, 2026 usability flag, swings (on ALL counties) -------------
    allpts["weight"] = allpts["hvotes_2026"].fillna(allpts["pvotes_2024"])
    allpts["ok_2026"] = (allpts["hcontested_2026"]
                         & (allpts["eevp_2026"].fillna(0) >= C.EEVP_MIN)
                         & allpts["hmargin_2026"].notna())

    swings = {
        # same office, consecutive election
        "swing_H24_H26": ("hmargin_2024", "hmargin_2026", "hvotes_2026",
                          allpts["ok_2026"] & allpts["hcontested_2024"] & allpts["hmargin_2024"].notna()),
        # same office, midterm-to-midterm (cleanest turnout match)
        "swing_H22_H26": ("hmargin_2022", "hmargin_2026", "hvotes_2026",
                          allpts["ok_2026"] & allpts["hcontested_2022"] & allpts["hmargin_2022"].notna()),
        # cross-election: 2026 House vs 2024 President (full baseline coverage)
        "swing_P24_H26": ("pmargin_2024", "hmargin_2026", "hvotes_2026",
                          allpts["ok_2026"] & allpts["pmargin_2024"].notna()),
        # fully-real validation surface (presidential, no uncontested problem)
        "swing_P20_P24": ("pmargin_2020", "pmargin_2024", "pvotes_2024",
                          allpts["pmargin_2020"].notna() & allpts["pmargin_2024"].notna()),
    }
    # National swing computed over CONUS only (consistent reference scalar); the
    # inset deviations then use the same national level as the main map.
    conus_mask = ~allpts["STATEFP"].isin(EXCLUDE)
    for name, (mf, mt, wt, valid) in swings.items():
        allpts[name] = np.where(valid, allpts[mt] - allpts[mf], np.nan)
        nat, nf, nt = national_swing(allpts, mf, mt, wt, valid & conus_mask)
        allpts[name + "_dev"] = allpts[name] - nat   # deviation from national swing
        log["national"][name] = {
            "national_swing_pts": round(nat, 3),
            "stations_valid_conus": int((valid & conus_mask).sum()),
            "margin_from_natl": round(nf, 3), "margin_to_natl": round(nt, 3),
        }

    # --- CONUS working-CRS coordinates for the main surface ----------------
    conus = allpts[conus_mask].copy()
    cpts = gpd.GeoSeries(gpd.points_from_xy(conus["lon"], conus["lat"]),
                         crs=C.CRS_GEOGRAPHIC).to_crs(C.CRS_WORKING)
    conus["x"] = cpts.x.values; conus["y"] = cpts.y.values
    log["data_quality"]["conus_county_geometries"] = int(len(conus))
    log["data_quality"]["geometries_without_2026"] = int(conus["hmargin_2026"].isna().sum())

    # --- Persist ------------------------------------------------------------
    year_cols = []
    for yr in C.OFFER_HOUSE_YEARS:
        year_cols += [f"hmargin_{yr}", f"hvotes_{yr}", f"hcontested_{yr}"]
    for yr in C.OFFER_PRES_YEARS:
        year_cols += [f"pmargin_{yr}", f"pvotes_{yr}"]
    base = (["fips", "state", "name", "STATEFP", "weight", "eevp_2026", "ok_2026"]
            + [k for k in swings] + [k + "_dev" for k in swings] + year_cols)
    common = list(dict.fromkeys(base))   # dedupe, keep order
    conus[["x", "y"] + common].to_csv(C.DATA_PROC / "stations.csv", index=False)
    allpts[["lon", "lat"] + common].to_csv(C.DATA_PROC / "stations_all.csv", index=False)
    gpd.GeoDataFrame({"name": ["CONUS"]},
                     geometry=[states.dissolve().geometry.iloc[0].buffer(0)],
                     crs=C.CRS_WORKING).to_file(C.DATA_PROC / "conus_land.gpkg", driver="GPKG")
    # Keep only geometry + a plain-str STUSPS: newer pandas string dtypes break
    # fiona's GPKG schema inference, so cast explicitly to object strings.
    states_out = states[["STUSPS", "geometry"]].copy()
    states_out["STUSPS"] = states_out["STUSPS"].astype(str).astype(object)
    states_out.to_file(C.DATA_PROC / "conus_states.gpkg", driver="GPKG")
    json.dump(log, open(C.DATA_PROC / "data_quality_log.json", "w"), indent=2)

    print("=== Phase 1 complete (REAL provisional 2026 returns) ===")
    print(f"fetched_at: {log['provenance']['fetched_at']}")
    print(f"CONUS county geometries           : {len(conus)}")
    print(f"  with a 2026 House margin        : {int(conus['hmargin_2026'].notna().sum())}")
    print(f"  usable 2026 (contested+counted) : {int(conus['ok_2026'].sum())}")
    for name in swings:
        n = log["national"][name]
        print(f"{name:14s} national={n['national_swing_pts']:+6.2f} pts   valid stations={n['stations_valid_conus']}")
    print("Wrote stations.csv, stations_all.csv, conus_land.gpkg, conus_states.gpkg, data_quality_log.json")


if __name__ == "__main__":
    main()
