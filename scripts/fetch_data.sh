#!/usr/bin/env bash
# Download all raw inputs into data/raw/. Safe to re-run (idempotent).
# Keeps downloaded (untrusted) data out of git; the pipeline reads from here.
set -euo pipefail
cd "$(dirname "$0")/.."
RAW="data/raw"
GEO="$RAW/geo"
mkdir -p "$RAW" "$GEO" "$RAW/elections2026"

echo "[1/4] County presidential returns (2008-2024) — tonmcg"
base="https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master"
curl -fsSL -o "$RAW/2024_county_pres.csv" "$base/2024_US_County_Level_Presidential_Results.csv"
curl -fsSL -o "$RAW/2020_county_pres.csv" "$base/2020_US_County_Level_Presidential_Results.csv"
curl -fsSL -o "$RAW/2016_county_pres.csv" "$base/2016_US_County_Level_Presidential_Results.csv"
curl -fsSL -o "$RAW/pres_08_16.csv"       "$base/US_County_Level_Presidential_Results_08-16.csv"

echo "[2/4] Census cartographic boundaries 2021 (county + state, 1:20m)"
cb="https://www2.census.gov/geo/tiger/GENZ2021/shp"
curl -fsSL -o "$GEO/cb_2021_us_county_20m.zip" "$cb/cb_2021_us_county_20m.zip"
curl -fsSL -o "$GEO/cb_2021_us_state_20m.zip"  "$cb/cb_2021_us_state_20m.zip"
rm -rf "$GEO/counties2021" "$GEO/states2021"
unzip -o -q "$GEO/cb_2021_us_county_20m.zip" -d "$GEO/counties2021"
unzip -o -q "$GEO/cb_2021_us_state_20m.zip"  -d "$GEO/states2021"

echo "[2b] Census 2020 tract population centres (places county votes where people live)"
mkdir -p "$RAW/cenpop"
curl -fsSL -o "$RAW/cenpop/CenPop2020_Mean_TR.txt" "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR.txt"

echo "[3/4] Place names for zoom-in labels — GeoNames cities15000 (CC BY 4.0)"
mkdir -p "$RAW/geonames"
curl -fsSL -o "$RAW/geonames/cities15000.zip" "https://download.geonames.org/export/dump/cities15000.zip"
unzip -o -q "$RAW/geonames/cities15000.zip" -d "$RAW/geonames"

echo "[4/4] 2026 provisional returns — mike10010100/elections-2026 (NYT-compiled)"
# Validates coverage and falls back to the newest good upstream commit if the
# latest snapshot is degraded (the feed auto-updates and has regressed before).
python3 scripts/fetch_2026.py "$RAW/elections2026" "${MIN_H26_COUNTIES:-2500}"
echo "Done. Raw inputs in $RAW/"
