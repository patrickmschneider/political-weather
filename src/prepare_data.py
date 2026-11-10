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


def _tp(x):
    if not x or x.get("d") is None or x.get("r") is None or (x["d"] + x["r"]) <= 0:
        return None
    return (x["d"] - x["r"]) / (x["d"] + x["r"]) * 100.0


def one_party_states(overview) -> dict:
    """{year: {state: {'D','R'}}} - states with a one-party / unopposed House
    district that year, and which party it inflates. From the feed's per-district
    flags (2026) and office_history 'op' flags (earlier cycles)."""
    out = {}
    for r in overview.get("house_races", []):
        st = r["state"]
        for yr, h in (r.get("office_history") or {}).items():
            if h.get("op") and h.get("m") is not None:
                out.setdefault(int(yr), {}).setdefault(st, set()).add("D" if h["m"] > 0 else "R")
        if r.get("one_party") or r.get("uncontested"):
            parties = {c.get("party") for c in r.get("candidates", []) if c.get("votes")}
            for p, lab in (("DEM", "D"), ("GOP", "R")):
                if parties and parties <= {p, "IND", "NPP", "OTH", None} and p in parties:
                    out.setdefault(2026, {}).setdefault(st, set()).add(lab)
            if "DEM" in parties and "GOP" not in parties:
                out.setdefault(2026, {}).setdefault(st, set()).add("D")
            if "GOP" in parties and "DEM" not in parties:
                out.setdefault(2026, {}).setdefault(st, set()).add("R")
    return out


# Same-ballot statewide comparators per House year (first contested one wins).
_STATEWIDE = {2014: ["s14", "g14"], 2016: ["p16", "s16", "g16"], 2018: ["s18", "g18"],
              2020: ["p20", "s20", "g20"], 2022: ["s22", "g22"], 2024: ["p24", "s24", "g24"],
              2026: ["g26", "s26"]}


def contaminated_house(src, overview, years) -> dict:
    """{(fips, year): True} for county House results distorted by a same-party
    district (see config.ONE_PARTY_RESID_PTS)."""
    cs = json.load(open(src))["counties"]
    ops = one_party_states(overview)
    bad, log = {}, {}
    for yr in years:
        key = "h" + str(yr)[2:]
        resid = {}
        for fips, c in cs.items():
            hm = _tp(c.get(key))
            if hm is None:
                continue
            for k in _STATEWIDE.get(yr, []):
                x = c.get(k)
                if x and not x.get("op") and _tp(x) is not None and min(x["d"], x["r"]) >= C.CONTEST_MIN_PCT:
                    resid[str(fips).zfill(5)] = (c.get("state"), hm - _tp(x))
                    break
        if not resid:
            continue
        # Baseline per state absorbs statewide candidate effects (a popular
        # governor shifts every county). Where a state HAS a one-party district,
        # contamination only pushes one way, so use the opposite quartile.
        by_st = {}
        for st, r in resid.values():
            by_st.setdefault(st, []).append(r)
        st_ops = ops.get(yr, {})
        base = {}
        for st, rs in by_st.items():
            p = st_ops.get(st, set())
            q = 0.25 if p == {"D"} else 0.75 if p == {"R"} else 0.5
            base[st] = float(np.quantile(rs, q))
        clean = [abs(r - base[st]) for st, r in resid.values() if st not in st_ops]
        thr = max(C.ONE_PARTY_RESID_PTS, float(np.quantile(clean, C.ONE_PARTY_RESID_Q))) if clean else C.ONE_PARTY_RESID_PTS
        n = 0
        for fips, (st, r) in resid.items():
            parties = st_ops.get(st, set())
            d = r - base[st]
            if ("D" in parties and d > thr) or ("R" in parties and d < -thr):
                bad[(fips, yr)] = True
                n += 1
        log[yr] = {"excluded": n, "cutoff_pts": round(thr, 1)}
    return bad, log


def _pres_cols(df, fips_col, dem_col, gop_col, year) -> pd.DataFrame:
    fips = (df[fips_col].astype(str).str.split(".").str[0].str.zfill(5))
    out = pd.DataFrame({"fips": fips})
    out[f"pmargin_{year}"] = _tp_margin(df[dem_col], df[gop_col])
    out[f"pvotes_{year}"] = df[dem_col].astype(float) + df[gop_col].astype(float)
    return out


def load_pres_year(path, year, fips_col="county_fips") -> pd.DataFrame:
    """Per-year presidential file (2016 uses combined_fips, 2020/24 county_fips)."""
    df = pd.read_csv(path, dtype={fips_col: str})
    return _pres_cols(df, fips_col, "votes_dem", "votes_gop", year)


def load_pres_combined(path, years) -> pd.DataFrame:
    """Wide 2008-2016 file: dem_YYYY / gop_YYYY columns keyed by fips_code."""
    df = pd.read_csv(path, dtype={"fips_code": str})
    merged = None
    for y in years:
        part = _pres_cols(df, "fips_code", f"dem_{y}", f"gop_{y}", y)
        merged = part if merged is None else merged.merge(part, on="fips", how="outer")
    return merged


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
    if C.SOURCE_2026_COMMIT.exists():
        log["provenance"]["source_commit"] = json.load(open(C.SOURCE_2026_COMMIT))
    log["provenance"]["baseline_pres"] = "tonmcg/US_County_Level_Election_Results_08-24"
    log["provenance"]["geometry"] = "US Census CB 2021 county/state 1:20m (traditional CT counties)"

    house = load_house(C.SOURCE_2026)
    bad, badlog = contaminated_house(C.SOURCE_2026, ov, C.OFFER_HOUSE_YEARS)
    for yr in C.OFFER_HOUSE_YEARS:
        hit = house["fips"].map(lambda f: (f, yr) in bad)
        house[f"hcontested_{yr}"] &= ~hit
    log["data_quality"]["one_party_contaminated_counties"] = {str(k): v for k, v in badlog.items()}
    print("Counties excluded for same-party-district contamination:", badlog)
    conus_h26 = int((house["hmargin_2026"].notna()
                     & ~house["fips"].str[:2].isin(EXCLUDE)).sum())
    if conus_h26 < C.MIN_2026_COUNTIES:
        raise SystemExit(
            f"ABORT: only {conus_h26} CONUS counties have a 2026 House margin "
            f"(< {C.MIN_2026_COUNTIES}). The 2026 feed looks degraded; refusing to "
            f"build a surface that would be extrapolated from a few states.")
    pres = [
        load_pres_year(C.DATA_RAW / "2024_county_pres.csv", 2024),
        load_pres_year(C.DATA_RAW / "2020_county_pres.csv", 2020),
        load_pres_year(C.DATA_RAW / "2016_county_pres.csv", 2016, fips_col="combined_fips"),
        load_pres_combined(C.DATA_RAW / "pres_08_16.csv", [2008, 2012]),
    ]
    df = house
    for p in pres:
        df = df.merge(p, on="fips", how="left")

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
