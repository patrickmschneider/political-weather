"""Central configuration for the electoral swing contour pipeline.

Importing this module FIRST (before numpy/scipy) also caps BLAS thread pools:
nested parallelism (BLAS threads inside already-parallel numeric loops) causes
catastrophic oversubscription here, turning <1s work into minutes.
"""
import os as _os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_v, "1")

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"
OUTPUT = ROOT / "output"
DOCS = ROOT / "docs"

for _d in (DATA_PROC, OUTPUT, DOCS):
    _d.mkdir(parents=True, exist_ok=True)

# --- Coordinate reference systems -------------------------------------------
# Source data CRS (Census cartographic boundaries): NAD83 geographic.
CRS_GEOGRAPHIC = "EPSG:4269"
# Working CRS for all distance / interpolation maths: CONUS Albers Equal Area.
# Equal-area + metres => honest distances and areas across the contiguous US.
CRS_WORKING = "EPSG:5070"

# --- Geographic scope -------------------------------------------------------
# Continental US only for the continuous surface. Alaska / Hawaii / territories
# are geographically detached and would force the interpolator to bridge oceans,
# so they are excluded from the CONUS surface (documented as a limitation).
EXCLUDE_STATEFP = {"02", "15", "60", "66", "69", "72", "78"}  # AK, HI, AS, GU, MP, PR, VI

# --- Interpolation grid -----------------------------------------------------
GRID_RES_M = 15_000  # 15 km grid cell -> crisp isolines for the 75 km kernel

# Web level-of-detail: coarser surface when zoomed out, finer revealed on zoom.
# (name, gaussian bandwidth m, grid resolution m, min zoom scale to show)
# --- Web app smoothing (computed in the browser) ---------------------------
# Each county's votes are spread over its 2020 census tracts' population
# centres (Census CenPop2020), so the surface sits where people live rather
# than at a county's geometric centre (big, empty Western counties).
TRACT_CENPOP = DATA_RAW / "cenpop" / "CenPop2020_Mean_TR.txt"
# Small-county shrinkage: a county's value is pulled toward its regional
# (wide-bandwidth) mean as v' = (w*v + K*r)/(w + K), w = two-party votes.
# A 2,000-vote county keeps ~2/7 of its own value; 100k+ vote counties ~all.
SHRINK_K_VOTES = 5000
SHRINK_BW_M = 150_000
WEB_LODS = [
    ("coarse", 75_000, 18_000, 0.0),
    ("fine",   40_000, 11_000, 3.0),
]

# --- Inset regions (own equal-area projections) -----------------------------
CRS_AK = "EPSG:3338"  # Alaska Albers Equal Area
# Hawaii Albers Equal Area (no standard EPSG; proj4 centred on the islands).
CRS_HI = ("+proj=aea +lat_1=19 +lat_2=22 +lat_0=20.5 +lon_0=-157 "
          "+x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs")
HI_GRID_RES_M = 1_500
HI_BANDWIDTH_M = 30_000

# --- Method hyperparameters (tuned/validated in cross_validate.py) ----------
GAUSSIAN_BANDWIDTH_M = 75_000    # kernel std dev (metres); reveals metro structure
IDW_POWER = 2.0
IDW_K = 32                       # nearest neighbours used per grid point
IDW_MIN_DIST_M = 5_000           # avoid singularity at a station
TPS_SMOOTHING = 1.0              # RBFInterpolator smoothing (regularisation)
TPS_NEIGHBORS = 64               # local TPS neighbours (stability + speed)

# --- 2026 results source (PROVISIONAL - swap this file to re-run) -----------
# To refresh with official/updated returns, replace this single JSON file with a
# newer copy in the same schema and re-run run_pipeline.py. Nothing else changes.
SOURCE_2026 = DATA_RAW / "elections2026" / "county_shifts.json"
SOURCE_2026_OVERVIEW = DATA_RAW / "elections2026" / "overview.json"
SOURCE_2026_COMMIT = DATA_RAW / "elections2026" / "source_commit.json"  # from fetch_2026.py
SOURCE_2026_PROVENANCE = (
    "mike10010100/elections-2026, site_data/county_shifts.json "
    "(compiles NYT precinct/county returns). PROVISIONAL, pre-certification."
)

# County geometry: 2021 cartographic boundaries keep Connecticut's TRADITIONAL
# counties, whose FIPS match the election returns (CT switched to planning
# regions in 2022, which the 2023 boundaries use and the returns do not).
COUNTY_SHP = DATA_RAW / "geo" / "counties2021" / "cb_2021_us_county_20m.shp"
STATE_SHP = DATA_RAW / "geo" / "states2021" / "cb_2021_us_state_20m.shp"

# --- Data-quality thresholds ------------------------------------------------
CONTEST_MIN_PCT = 2.0   # a county-cycle is "contested" if min(Dem%, Rep%) >= this
EEVP_MIN = 50           # drop 2026 counties with < this % of expected vote counted
# Abort the build if fewer CONUS counties than this carry a 2026 House margin:
# a degraded upstream snapshot must never be smoothed into a national surface.
MIN_2026_COUNTIES = 2500
# Same-party districts (CA/WA top-two D-vs-D or R-vs-R, unopposed seats) are
# summed into county House totals by the feed, inflating one party in every
# county they touch. In a state with such a district that year, a county is
# excluded when its House margin sits more than this many points beyond the
# same-ballot statewide race (Pres/Sen/Gov), in that party's direction,
# relative to that state's typical House-minus-statewide gap. The cutoff adapts
# per year: the 98th percentile of that gap in states WITHOUT such districts
# (ticket-splitting years like 2016 are much noisier), floored at this value.
ONE_PARTY_RESID_PTS = 12.0
ONE_PARTY_RESID_Q = 0.98

# --- Year surfaces offered in the web app's base/comparison pickers ---------
# Each becomes one smoothed margin surface; the app differences any two.
OFFER_HOUSE_YEARS = [2014, 2016, 2018, 2020, 2022, 2024, 2026]
OFFER_PRES_YEARS = [2008, 2012, 2016, 2020, 2024]

# --- Reproducibility --------------------------------------------------------
RANDOM_SEED = 20261103
